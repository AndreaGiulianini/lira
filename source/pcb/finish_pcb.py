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
from repair import CORRIDOR, drc, remove, repair, seg_dist, segs_dist  # noqa: E402


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


def stitch_ground(b, pitch=5.0, via_d=0.6, drill=0.3, clearance=0.35, split=None, key_pitch=12.0):
    """GND vias on a grid wherever both layers are free, so the two ground pours become one.

    With `split`, `pitch` is used in front of it (the electronics strip: USB, audio, antenna) and `key_pitch`
    behind it (the key field), where the signals are slow and a coarse stitch is enough. That keeps the via
    count, the drilling cost and the visual clutter down without weakening the ground where it matters."""
    gnd = b.FindNet("GND")
    bbox = b.GetBoardEdgesBoundingBox()
    shapes = []  # (layer, shape) of every copper object and hole
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
    top, bottom, left, right = bbox.GetTop() + edge, bbox.GetBottom() - edge, bbox.GetLeft() + edge, bbox.GetRight() - edge
    regions = [(pitch, top, split), (key_pitch, split, bottom)] if split else [(pitch, top, bottom)]
    vias = []
    for step_mm, y0, y1 in regions:
        step = pcbnew.FromMM(step_mm)
        y = int(y0)
        while y < y1:
            x = int(left)
            while x < right:
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


def prune_single_layer_vias(b):
    """Remove non-GND vias that connect only one layer. The autorouter leaves a few when repair deletes the track
    that used to leave the via on the other layer. Safe test: the via has track ends on exactly one layer, and no
    track or pad touches it on the other layer (plain geometry: segment distances and pad bounding boxes, which only
    errs towards keeping a via; KiCad's shape objects, created by the thousand here, upset its Python bindings). The
    DRC at the end confirms nothing was disconnected."""
    ends = {}
    segs = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
    for t in b.GetTracks():
        if t.GetClass() != "PCB_TRACK":
            continue
        s, e = t.GetStart(), t.GetEnd()
        for p in (s, e):
            ends.setdefault((p.x, p.y), set()).add(t.GetLayer())
        if t.GetLayer() in segs:
            segs[t.GetLayer()].append((s.x, s.y, e.x, e.y, t.GetWidth() / 2))
    pads = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
    for p in b.GetPads():
        if p.GetNetCode() <= 0:
            continue
        bb = p.GetBoundingBox()
        for layer in pads:
            if p.IsOnLayer(layer):
                pads[layer].append((bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()))
    removed = 0
    for v in [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA" and t.GetNetname() != "GND"]:
        c = v.GetPosition()
        layers = ends.get((c.x, c.y), set())
        if len(layers) != 1:
            continue
        other = pcbnew.B_Cu if pcbnew.F_Cu in layers else pcbnew.F_Cu
        r = v.GetWidth(pcbnew.F_Cu) / 2
        touched = any(seg_dist(c.x, c.y, x0, y0, x1, y1) <= r + h for x0, y0, x1, y1, h in segs[other]) or \
            any(x0 - r <= c.x <= x1 + r and y0 - r <= c.y <= y1 + r for x0, y0, x1, y1 in pads[other])
        if not touched:
            remove(b, [v])  # (kept alive: see repair.remove)
            removed += 1
    return removed


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
            remove(b, [v])  # (kept alive: see repair.remove)
    if kept:
        b.BuildConnectivity()
    return kept, len(vias) - len(kept)


MIN_TRACK = 0.15  # mm, the DRC minimum (gen_pcb.py)
STRIP_SPLIT = 34.0  # mm: electronics strip behind this line, key field in front of it (ground stitching density)


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


# The matrix lines and the LED line start at the RP2040's 0.4 mm-pitch pads, so they are routed at 0.2 mm (the Fine
# net class, gen_pcb.py); out in the board they are widened back to the 0.3 mm of every other signal wherever they
# keep 0.2 mm from other copper (a keyboard PCB flexes, and hot-swapping pulls on the socket pads).
WIDEN = dict(prefixes=("ROW", "COL", "LED_RED"), width=0.3, clearance=0.2, hole=0.25, edge=0.35)


def widen_lines(b):
    """Widen the matrix lines' segments to WIDEN["width"] where the wider segment keeps WIDEN["clearance"] from
    every other net, WIDEN["hole"] from holes, WIDEN["edge"] from the board edge and stays out of the rule areas.
    Plain geometry on bounding boxes (pads, board edge, rule areas: conservative), segments and circles; the DRC
    checks the result. Returns (widened, candidates)."""
    to = mm(WIDEN["width"])
    cand = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK" and t.GetNetname().startswith(WIDEN["prefixes"])
            and t.GetWidth() < to]
    cell = mm(4.0)
    index = {}

    def put(entry, box):
        x0, y0, x1, y1 = box
        for cx in range(int(x0 // cell), int(x1 // cell) + 1):
            for cy in range(int(y0 // cell), int(y1 // cell) + 1):
                index.setdefault((cx, cy), []).append(entry)

    def rect(item):
        bb = item.GetBoundingBox()
        return bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()

    tracks = {}  # uuid -> [layer, net, ax, ay, bx, by, half width] (updated as tracks widen)
    for t in b.GetTracks():
        if t.GetClass() == "PCB_VIA":
            p, r = t.GetPosition(), t.GetWidth(pcbnew.F_Cu) / 2
            put(("circle", None, t.GetNetCode(), p.x, p.y, r, mm(WIDEN["clearance"])), (p.x - r, p.y - r, p.x + r, p.y + r))
        elif t.GetClass() == "PCB_TRACK":
            s, e = t.GetStart(), t.GetEnd()
            rec = [t.GetLayer(), t.GetNetCode(), s.x, s.y, e.x, e.y, t.GetWidth() / 2]
            tracks[t.m_Uuid.AsString()] = rec
            put(("seg", rec), rect(t))
    for p in b.GetPads():
        net = p.GetNetCode() if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH else -1
        layers = tuple(layer for layer in (pcbnew.F_Cu, pcbnew.B_Cu) if p.IsOnLayer(layer))
        if layers and p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
            put(("rect", layers, net, rect(p), mm(WIDEN["clearance"])), rect(p))
        if p.HasHole():
            c, r = p.GetPosition(), max(p.GetDrillSize().x, p.GetDrillSize().y) / 2
            put(("circle", None, -2, c.x, c.y, r, mm(WIDEN["hole"])), (c.x - r, c.y - r, c.x + r, c.y + r))
    edges = b.GetBoardEdgesBoundingBox()
    bx0, by0, bx1, by1 = edges.GetLeft(), edges.GetTop(), edges.GetRight(), edges.GetBottom()
    areas = []
    for z in b.Zones():
        if z.GetIsRuleArea() and (z.GetDoNotAllowTracks() or z.GetZoneName() == CORRIDOR):
            layers = (pcbnew.B_Cu,) if z.GetZoneName() == CORRIDOR else \
                tuple(layer for layer in (pcbnew.F_Cu, pcbnew.B_Cu) if z.IsOnLayer(layer))
            areas.append((layers, rect(z)))

    def seg_rect(a, c, r):
        x0, y0, x1, y1 = r
        if x0 <= a[0] <= x1 and y0 <= a[1] <= y1 or x0 <= c[0] <= x1 and y0 <= c[1] <= y1:
            return 0.0
        corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
        return min(segs_dist(a, c, corners[i], corners[(i + 1) % 4]) for i in range(4))

    done = 0
    for t in cand:
        rec = tracks[t.m_Uuid.AsString()]
        layer, net, ax, ay, ex, ey, _ = rec
        h = to / 2
        a, c = (ax, ay), (ex, ey)
        ok = min(ax, ex) - h >= bx0 + mm(WIDEN["edge"]) and max(ax, ex) + h <= bx1 - mm(WIDEN["edge"]) and \
            min(ay, ey) - h >= by0 + mm(WIDEN["edge"]) and max(ay, ey) + h <= by1 - mm(WIDEN["edge"])
        near = {}
        if ok:
            for cx in range(int((min(ax, ex) - to) // cell), int((max(ax, ex) + to) // cell) + 1):
                for cy in range(int((min(ay, ey) - to) // cell), int((max(ay, ey) + to) // cell) + 1):
                    for entry in index.get((cx, cy), ()):
                        near[id(entry)] = entry
        for entry in near.values():
            if entry[0] == "seg":
                l2, n2, x0, y0, x1, y1, h2 = entry[1]
                if entry[1] is rec or n2 == net or l2 != layer:
                    continue
                ok = segs_dist(a, c, (x0, y0), (x1, y1)) - h - h2 >= mm(WIDEN["clearance"])
            elif entry[0] == "circle":
                _, _, n2, x, y, r, cl = entry
                if n2 == net:
                    continue
                ok = seg_dist(x, y, ax, ay, ex, ey) - h - r >= cl
            else:
                _, layers, n2, r, cl = entry
                if n2 == net or layer not in layers:
                    continue
                ok = seg_rect(a, c, r) - h >= cl
            if not ok:
                break
        if ok:
            ok = not any(layer in layers and seg_rect(a, c, r) - h < 0 for layers, r in areas)
        if ok:
            t.SetWidth(to)
            rec[6] = h
            done += 1
    return done, len(cand)


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
    widened, lines = widen_lines(b)
    print("matrix lines: %d of %d segments widened to %.1f mm" % (widened, lines, WIDEN["width"]))
    single = prune_single_layer_vias(b)
    if single:
        print("pruned %d single-layer via(s)" % single)
    teardrops = add_teardrops(b)
    print("teardrops: %d" % teardrops)
    stitched = stitch_ground(b, split=STRIP_SPLIT)
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
