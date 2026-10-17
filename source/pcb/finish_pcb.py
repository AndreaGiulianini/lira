"""Imports the Freerouting session into the placed board, completes what the autorouter left (pcb/repair.py), pours
GND on both layers and saves the final PCB.

    $KPY pcb/finish_pcb.py placed.kicad_pcb routes.ses final.kicad_pcb
"""
import shutil
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_pcb import patch_project  # noqa: E402
from repair import drc, repair  # noqa: E402


def mm(v):
    return pcbnew.FromMM(v)


def add_ground_pour(b, layer):
    gnd = b.FindNet("GND")
    if gnd is None:
        return None
    bbox = b.GetBoardEdgesBoundingBox()
    z = pcbnew.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(gnd)
    z.SetLocalClearance(mm(0.3))
    z.SetMinThickness(mm(0.25))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z.SetThermalReliefGap(mm(0.3))
    z.SetThermalReliefSpokeWidth(mm(0.4))
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetAssignedPriority(0)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((bbox.GetLeft(), bbox.GetTop()), (bbox.GetRight(), bbox.GetTop()),
                 (bbox.GetRight(), bbox.GetBottom()), (bbox.GetLeft(), bbox.GetBottom())):
        o.Append(x, y)
    b.Add(z)
    return z


def stitch_ground(b, pitch=5.0, via_d=0.6, drill=0.3, clearance=0.35):
    """GND vias on a grid wherever both layers are free, so the two ground pours become one."""
    gnd = b.FindNet("GND")
    bbox = b.GetBoardEdgesBoundingBox()
    shapes = []  # (layerset, shape) of every copper object and hole
    for t in b.GetTracks():
        for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
            if t.IsOnLayer(layer):
                shapes.append((layer, t.GetEffectiveShape(layer)))
    blocked = []
    for fp in b.GetFootprints():
        for p in fp.Pads():
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if p.IsOnLayer(layer) or p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                    shapes.append((layer, p.GetEffectiveShape(layer)))
            if p.HasHole():
                blocked.append(p.GetEffectiveHoleShape())
        crt = fp.GetCourtyard(pcbnew.B_CrtYd)  # never under bottom-side parts (module, sockets, ICs)
        if crt.OutlineCount():
            blocked.append(crt)
    keepouts = []  # rule areas (antenna), grown by 1 mm
    for z in b.Zones():
        if z.GetIsRuleArea():
            bb = z.GetBoundingBox()
            bb.Inflate(pcbnew.FromMM(1.0))
            keepouts.append(bb)
    r = pcbnew.FromMM(via_d / 2)
    cl = pcbnew.FromMM(clearance)
    edge = pcbnew.FromMM(1.5)
    vias = []
    step = pcbnew.FromMM(pitch)
    y = bbox.GetTop() + edge
    while y < bbox.GetBottom() - edge:
        x = bbox.GetLeft() + edge
        while x < bbox.GetRight() - edge:
            c = pcbnew.VECTOR2I(int(x), int(y))
            circle = pcbnew.SHAPE_CIRCLE(c, r)
            ok = not any(k.Contains(c) for k in keepouts)
            ok = ok and not any(s.Collide(circle, cl) for _, s in shapes)
            ok = ok and not any(s.Collide(circle, cl) if hasattr(s, "Collide") else s.Contains(c) for s in blocked)
            if ok:
                v = pcbnew.PCB_VIA(b)
                v.SetPosition(c)
                v.SetDrill(pcbnew.FromMM(drill))
                v.SetWidth(pcbnew.FromMM(via_d))
                v.SetNet(gnd)
                b.Add(v)
                vias.append(v)
            x += step
        y += step
    return vias


def prune_dangling_vias(b, vias):
    """Remove stitching vias that the filled ground pours do not reach. They pass the collision test before the
    pour exists, but a via can end up on a copper island that island_removal then deletes; left in, it would show as
    an unconnected item in the DRC. Returns (kept, removed)."""
    gnd = [z for z in b.Zones() if not z.GetIsRuleArea() and z.GetNetname() == "GND"]

    def covered(v):
        p = v.GetPosition()
        for z in gnd:
            for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not z.IsOnLayer(layer):
                    continue
                poly = z.GetFilledPolysList(layer)
                if poly is not None and poly.Contains(p):
                    return True
        return False

    kept = [v for v in vias if covered(v)]
    for v in vias:
        if v not in kept:
            b.Remove(v)
    if kept:
        b.BuildConnectivity()
    return kept, len(vias) - len(kept)


MIN_TRACK = 0.15  # mm, the DRC minimum (gen_pcb.py)


def drc_unconnected(board_file):
    """Unconnected items reported by KiCad's DRC on the finished board (pours included)."""
    return [i["items"][0]["description"] for i in drc(board_file).get("unconnected_items", [])]


def narrow_to_min(b):
    """Freerouting necks a track down (to 0.1 mm) where it squeezes past a pad; the DRC minimum is 0.15 mm, so those
    short pieces are widened to it (the DRC afterwards still checks every clearance). Returns them."""
    narrow = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetWidth() < pcbnew.FromMM(MIN_TRACK)]
    for t in narrow:
        t.SetWidth(pcbnew.FromMM(MIN_TRACK))
    return narrow


TEARDROP = dict(length=1.0, width=0.85, max_track=0.45)  # past the pad edge (mm); fraction of the pad; widest track


def add_teardrops(b):
    """Teardrops where a track meets a pad or a via: a small copper wedge of the track's net, from the pad's centre
    (inside it) to 1 mm past its edge, so the joint survives flexing and hot-swapping. KiCad generates these only
    in its editor, so they are drawn here as small high-priority zones; the zone filler keeps them clear of other
    nets like any other copper."""
    import math
    targets = []  # (x, y, half size along x, along y, layer set, net code)
    for fp in b.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() <= 0:
                continue
            bb = p.GetBoundingBox()
            targets.append((p.GetPosition(), bb.GetWidth() / 2, bb.GetHeight() / 2, p, p.GetNetCode()))
    for v in b.GetTracks():
        if v.GetClass() == "PCB_VIA":
            r = v.GetWidth(pcbnew.F_Cu) / 2
            targets.append((v.GetPosition(), r, r, v, v.GetNetCode()))
    by_net = {}
    for tgt in targets:
        by_net.setdefault(tgt[4], []).append(tgt)
    made = 0
    for t in [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]:
        w = t.GetWidth()
        if w > mm(TEARDROP["max_track"]):
            continue
        layer = t.GetLayer()
        for end, other in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            for pos, hx, hy, item, net in by_net.get(t.GetNetCode(), []):
                if not item.IsOnLayer(layer) or abs(end.x - pos.x) > hx or abs(end.y - pos.y) > hy:
                    continue
                dx, dy = other.x - pos.x, other.y - pos.y
                n = math.hypot(dx, dy)
                if n == 0:
                    break
                ux, uy = dx / n, dy / n
                edge = abs(ux) * hx + abs(uy) * hy  # pad centre to its edge along the track
                reach = edge + mm(TEARDROP["length"])
                if n < reach:  # the track ends before the teardrop would
                    break
                half = max(w / 2, TEARDROP["width"] * (abs(uy) * hx + abs(ux) * hy))  # pad half-width across it
                px, py = -uy, ux
                pts = [(pos.x + px * half, pos.y + py * half), (pos.x + ux * reach + px * w / 2, pos.y + uy * reach + py * w / 2),
                       (pos.x + ux * reach - px * w / 2, pos.y + uy * reach - py * w / 2), (pos.x - px * half, pos.y - py * half)]
                z = pcbnew.ZONE(b)
                z.SetLayer(layer)
                z.SetNetCode(net)
                z.SetAssignedPriority(100 + made)  # overlapping zones (two teardrops on one via) need distinct priorities
                z.SetLocalClearance(mm(0.2))
                z.SetMinThickness(mm(0.1))
                z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
                z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
                try:
                    z.SetTeardropAreaType(2)  # TD_VIAPAD: KiCad shows and manages it as a teardrop
                except Exception:  # noqa: BLE001
                    pass
                o = z.Outline()
                o.NewOutline()
                for x, y in pts:
                    o.Append(int(x), int(y))
                b.Add(z)
                made += 1
                break
    return made


def coplanar_ground(b, name="usb-hs-corridor", clearance=0.2):
    """Bottom-layer ground 0.2 mm beside the USB high-speed pair (instead of the pour's 0.3 mm): a higher-priority
    ground zone over the corridor (a rule area of pcb/electronics.py that keeps footprints out of it)."""
    gnd = b.FindNet("GND")
    for area in [z for z in b.Zones() if z.GetIsRuleArea() and z.GetZoneName() == name]:
        z = pcbnew.ZONE(b)
        z.SetLayer(pcbnew.B_Cu)
        z.SetNet(gnd)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        z.SetAssignedPriority(1)
        z.Outline().Append(area.Outline())
        b.Add(z)
        return True
    return False


def finish(routed_file, final):
    """Pour ground, stitch, add teardrops, fill and save the final board from a routed (pour-less) board."""
    b = pcbnew.LoadBoard(str(routed_file))
    teardrops = add_teardrops(b)
    print("teardrops: %d" % teardrops)
    stitched = stitch_ground(b)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        add_ground_pour(b, layer)
    if not coplanar_ground(b):
        print("WARNING: no USB high-speed corridor found")
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.BuildConnectivity()
    kept, removed = prune_dangling_vias(b, stitched)
    if removed:
        print("pruned %d ground stitching via(s) the pour does not reach" % removed)
    pcbnew.SaveBoard(final, b)
    patch_project(Path(final).with_suffix(".kicad_pro"))
    return b, len(kept)


def main(placed, ses, final):
    b = pcbnew.LoadBoard(placed)
    if not pcbnew.ImportSpecctraSES(b, ses):
        raise SystemExit("could not import " + ses)
    narrow = narrow_to_min(b)
    if narrow:
        print("widened %d autorouter neck-down segment(s) to %.2f mm (%.2f mm of track)"
              % (len(narrow), MIN_TRACK, sum(pcbnew.ToMM(t.GetLength()) for t in narrow)))
    routed = Path(final).parent / "lira-routed.kicad_pcb"
    pcbnew.SaveBoard(str(routed), b)
    patch_project(routed.with_suffix(".kicad_pro"))  # so the DRC in repair() uses our net classes and rules
    shutil.copy(Path(final).with_suffix(".kicad_dru"), routed.with_suffix(".kicad_dru"))
    log, failed = repair(routed, placed)
    for line in log:
        print("repair:", line)
    patch_project(routed.with_suffix(".kicad_pro"))  # SaveBoard in repair() wrote KiCad's default classes again
    b, stitched = finish(routed, final)
    missing = drc_unconnected(final)
    for m in missing:
        print("UNCONNECTED:", m)
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    print("final board: %d track segments, %.0f mm of copper, %d vias (%d ground stitching)" % (
        len(tracks), sum(pcbnew.ToMM(t.GetLength()) for t in tracks), len(vias), stitched))
    if failed or missing:  # (make deletes the half-finished board: .DELETE_ON_ERROR)
        raise SystemExit("the board is not completely connected")


if __name__ == "__main__":
    main(*sys.argv[1:4])
