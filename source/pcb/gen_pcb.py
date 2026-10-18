"""Generates the keyboard PCB (placement, nets, outline, mounting holes) from layout.py.

Run with KiCad's own Python (it ships the pcbnew module):
    make pcb            (see Makefile)
Output: build/pcb/lira.kicad_pcb (unrouted) + lira.dsn for Freerouting.

Conventions: KiCad coordinates in mm, y grows towards the user (front). The key area starts at (KX, KY);
the electronics strip is behind it (smaller y). Switches sit on top, every SMD part on the bottom
(single-sided assembly at JLCPCB).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pcbnew  # noqa: E402

import circuit  # noqa: E402
import layout as L  # noqa: E402
from paths import BUILD  # noqa: E402
from electronics import add_electronics, STRIP_DEPTH  # noqa: E402

U = L.U
KICAD_FP = next(p for p in Path(pcbnew.__file__).resolve().parents if p.name == "Contents") \
    / "SharedSupport" / "footprints"
LIB = ROOT / "lib"

MARGIN = 0.6  # PCB edge beyond the key area (left and right)
FRONT_MARGIN = 2.0  # front: the big stabilizer holes of the bottom row reach 10.2 mm below the key centre
KX, KY = 10.0, 10.0 + STRIP_DEPTH  # top-left corner of the key area
BOARD_L, BOARD_T = KX - MARGIN, KY - STRIP_DEPTH
BOARD_R, BOARD_B = KX + L.WIDTH * U + MARGIN, KY + L.HEIGHT * U + FRONT_MARGIN
CORNER_R = 1.0

DIODE_OFFSET = (0.0, 5.0)  # diode position relative to the switch center (bottom side)


def mm(v):
    return pcbnew.FromMM(v)


def pt(x, y):
    return pcbnew.VECTOR2I(mm(x), mm(y))


def lib_path(lib):
    p = LIB / (lib + ".pretty")
    return str(p if p.exists() else KICAD_FP / (lib + ".pretty"))


class Board:
    def __init__(self, path):
        self.b = pcbnew.NewBoard(str(path))
        self.nets = {}
        self.footprints = []

    def net(self, name):
        if name not in self.nets:
            n = pcbnew.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self.nets[name] = n
        return self.nets[name]

    def place(self, lib, name, ref, x, y, rot=0.0, bottom=False, value=None, nets=None, lcsc=None,
              in_bom=True):
        fp = pcbnew.FootprintLoad(lib_path(lib), name)
        if fp is None:
            raise SystemExit("footprint not found: %s:%s" % (lib, name))
        fp.SetReference(ref)
        fp.SetValue(value or name)
        self.b.Add(fp)
        fp.SetPosition(pt(x, y))
        if bottom:
            fp.Flip(pt(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        for pad in fp.Pads():
            if nets and pad.GetNumber() in nets:
                pad.SetNet(self.net(nets[pad.GetNumber()]))
        if lcsc:
            fp.SetField("LCSC", lcsc)
            fp.GetField("LCSC").SetVisible(False)
        if not in_bom:
            fp.SetExcludedFromBOM(True)
            fp.SetExcludedFromPosFiles(True)
        fp.Reference().SetVisible(False)
        self.footprints.append(fp)
        return fp

    def edge_line(self, x1, y1, x2, y2):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(x1, y1))
        s.SetEnd(pt(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        self.b.Add(s)

    def edge_arc(self, cx, cy, r, start_deg):
        """Quarter arc of radius r around (cx, cy) from start_deg, 90 degrees clockwise on screen."""
        import math
        a0, a1 = math.radians(start_deg), math.radians(start_deg + 45)
        a2 = math.radians(start_deg + 90)
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(pt(cx + r * math.cos(a0), cy + r * math.sin(a0)),
                         pt(cx + r * math.cos(a1), cy + r * math.sin(a1)),
                         pt(cx + r * math.cos(a2), cy + r * math.sin(a2)))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        self.b.Add(s)

    def rounded_rect(self, l, t, r, b, rad):
        self.edge_line(l + rad, t, r - rad, t)
        self.edge_line(r, t + rad, r, b - rad)
        self.edge_line(r - rad, b, l + rad, b)
        self.edge_line(l, b - rad, l, t + rad)
        self.edge_arc(r - rad, t + rad, rad, 270)
        self.edge_arc(r - rad, b - rad, rad, 0)
        self.edge_arc(l + rad, b - rad, rad, 90)
        self.edge_arc(l + rad, t + rad, rad, 180)


def key_center(k):
    return KX + k.cx * U, KY + k.cy * U


def add_keys(B):
    """Switches, diodes and stabilizers; their nets come from circuit.matrix()."""
    parts = {p.ref: p for p in circuit.matrix(L.KEYS)}
    for i, k in enumerate(sorted(L.KEYS, key=lambda k: (k.row, k.col)), start=1):
        x, y = key_center(k)
        size = max(k.w, k.h)
        part = parts["SW%d" % i]
        lib, name = part.footprint.split(":")
        fp = B.place(lib, name, part.ref, x, y, value=part.value, nets=part.nets, lcsc=part.lcsc)
        dx, dy = DIODE_OFFSET
        fp.SetField("Key", "%s %s" % (k.label, part.note))
        d = parts["D%d" % i]
        lib, name = d.footprint.split(":")
        B.place(lib, name, d.ref, x + dx, y + dy, rot=0, bottom=True, value=d.value, nets=d.nets, lcsc=d.lcsc)
        if k.stabilized:
            stab = "Stabilizer_Cherry_MX_%.2fu" % (3.0 if size >= 3 else 2.0)
            B.place("Mounting_Keyboard_Stabilizer", stab, "ST%d" % i, x, y, rot=90 if k.h > k.w else 0,
                    value="stab %gu" % size, in_bom=False)


def all_holes_and_pads(B):
    """(x, y, radius, side) of every pad/hole already on the board; side in {'F','B','*'}."""
    out = []
    for fp in B.footprints:
        for p in fp.Pads():
            pos = p.GetPosition()
            sz = p.GetSize()
            r = max(pcbnew.ToMM(sz.x), pcbnew.ToMM(sz.y)) / 2
            if p.GetAttribute() in (pcbnew.PAD_ATTRIB_NPTH, pcbnew.PAD_ATTRIB_PTH):
                side = "*"
            else:
                side = "B" if p.IsOnLayer(pcbnew.B_Cu) else "F"
            out.append((pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y), r, side))
    return out


def courtyards(B, layer):
    """Axis-aligned boxes of the courtyards on one side (F_CrtYd: switches, B_CrtYd: sockets and SMD parts)."""
    boxes = []
    for fp in B.footprints:
        if fp.GetReference().startswith("H"):
            continue
        bb = fp.GetCourtyard(layer).BBox()
        if bb.GetWidth() > 0:
            boxes.append((pcbnew.ToMM(bb.GetLeft()), pcbnew.ToMM(bb.GetTop()),
                          pcbnew.ToMM(bb.GetRight()), pcbnew.ToMM(bb.GetBottom())))
    return boxes


# Mounting holes (M2, tray mount). Positions in keyboard units relative to the key area, chosen in free spots:
# the numpad gap, the empty bottom corners, between the two spacebars and between keys on row boundaries. Each wished spot is moved to the nearest place with room
# (add_mounting); check_mounting() verifies the clearance for a ⌀5 mm standoff + ⌀4 mm screw head.
CORNERS = [(L.MX + L.BLOCKER / 2, 3.5), (L.MX + L.MAIN_W - L.BLOCKER / 2, 3.5)]
MOUNT_U = [
    (L.NUMPAD_W + L.GAP / 2, 1.0), (L.NUMPAD_W + L.GAP / 2, 3.0),  # numpad gap
] + CORNERS + [
    (L.MX + 6.5, 3.5),  # between the spacebars
    (2.0, 2.0),  # numpad, between 5/6 row boundary
    (L.MX + 3.25, 2.0), (L.MX + 9.75, 2.0),  # main block, row boundary 1|2
]
STANDOFF_R = 2.75  # bottom side: printed standoff around a M2 heat-set insert
HEAD_R = 2.0  # top side: M2 screw head, must clear the switch bodies


def box_dist(x, y, boxes):
    best = 99.0
    for (l, t, r, b) in boxes:
        nx, ny = min(max(x, l), r), min(max(y, t), b)
        best = min(best, ((nx - x) ** 2 + (ny - y) ** 2) ** 0.5)
    return best


def clearance(x, y, feats, bottom, top):
    """Margin left around a hole at (x, y): >= 0 means the standoff (bottom) and the screw head (top) fit."""
    pads = min([((fx - x) ** 2 + (fy - y) ** 2) ** 0.5 - r for (fx, fy, r, side) in feats] + [99.0])
    return min(pads - STANDOFF_R, box_dist(x, y, bottom) - STANDOFF_R, box_dist(x, y, top) - HEAD_R)


def add_mounting(B, search=5.5, step=0.25):
    """Each wished position is moved (within `search` mm) to the spot with the most free room."""
    feats, bottom, top = all_holes_and_pads(B), courtyards(B, pcbnew.B_CrtYd), courtyards(B, pcbnew.F_CrtYd)
    holes = []
    for i, (ux, uy) in enumerate(MOUNT_U, start=1):
        x0, y0 = KX + ux * U, KY + uy * U
        n = int(search / step)
        cands = [(x0 + dx * step, y0 + dy * step) for dx in range(-n, n + 1) for dy in range(-n, n + 1)]
        # prefer the wished spot: penalize distance from it a little
        x, y = max(cands, key=lambda c: min(clearance(c[0], c[1], feats, bottom, top), 1.0)
                   - 0.02 * ((c[0] - x0) ** 2 + (c[1] - y0) ** 2) ** 0.5)
        x, y = round(x, 2), round(y, 2)
        B.place("MountingHole", "MountingHole_2.2mm_M2", "H%d" % i, x, y, value="M2", in_bom=False)
        holes.append((x, y))
    return holes


def check_holes_inside(B, min_edge=0.8):
    """Every hole must stay min_edge inside the board outline (DRC does not check plain NPTH holes)."""
    bad = []
    for fp in B.footprints:
        for p in fp.Pads():
            if not p.HasHole():
                continue
            x, y = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
            r = pcbnew.ToMM(p.GetDrillSize().x) / 2
            if min(x - r - BOARD_L, BOARD_R - x - r, y - r - BOARD_T, BOARD_B - y - r) < min_edge:
                bad.append("%s hole at %.1f,%.1f too close to the board edge" % (fp.GetReference(), x, y))
    return bad


def check_mounting(B, holes):
    feats = all_holes_and_pads(B)
    bottom, top = courtyards(B, pcbnew.B_CrtYd), courtyards(B, pcbnew.F_CrtYd)
    bad = []
    for (x, y) in holes:
        c = clearance(x, y, [f for f in feats if (f[0] - x) ** 2 + (f[1] - y) ** 2 > 0.01], bottom, top)
        if c < 0:
            bad.append(((x, y), "short of room by %.2f mm" % -c))
    return bad


def add_outline(B):
    B.rounded_rect(BOARD_L, BOARD_T, BOARD_R, BOARD_B, CORNER_R)


def setup_rules(B):
    ds = B.b.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_MinClearance = mm(0.15)
    ds.m_ViasMinSize = mm(0.6)
    ds.m_MinThroughDrill = mm(0.3)
    nc = ds.m_NetSettings.GetDefaultNetclass()
    nc.SetTrackWidth(mm(0.3))  # 0.3 mm signals: a keyboard PCB flexes, and hot-swapping pulls on the socket pads
    # routing clearance (exported to Freerouting) a little above the 0.15 mm the DRC enforces (patch_project), so
    # the autorouter's rounding never lands a track just under the limit
    nc.SetClearance(mm(0.18))
    nc.SetViaDiameter(mm(0.6))
    nc.SetViaDrill(mm(0.3))
    # gerbers, drill and CPL files use the bottom-left board corner as origin (all coordinates positive)
    ds.SetAuxOrigin(pt(BOARD_L, BOARD_B))


def to_slab(x, y):
    """KiCad mm -> case 'slab frame': origin at the front-left corner of the key area, y towards the back."""
    return round(x - KX, 3), round(KY + L.HEIGHT * U - y, 3)


def write_interface(path, holes, ports):
    """Everything the case and firmware generators need to know about the PCB (positions in slab frame)."""
    import json
    l, f = to_slab(BOARD_L, BOARD_B)
    r, b = to_slab(BOARD_R, BOARD_T)
    data = {
        "key_area": [round(L.WIDTH * U, 3), round(L.HEIGHT * U, 3)],
        "pcb": {"left": l, "right": r, "front": f, "back": b, "thickness": 1.6},
        "mount_holes": [to_slab(x, y) for x, y in holes],
        "ports": {},
    }
    for name, v in ports.items():
        if name in ("matrix", "gpio"):
            data[name] = v
        elif name == "bolts":
            data["ports"]["bolts"] = [to_slab(x, y) for x, y in v]
        elif name == "window":
            data["ports"]["window"] = {"x0": round(v[0] - KX, 3), "x1": round(v[2] - KX, 3)}
        else:
            x, y = to_slab(*v)
            data["ports"][name] = {"x": x, "y": y}
    path.write_text(json.dumps(data, indent=1))


POWER_NETS = ("GND", "VBUS", "AUD_5V")  # USB 5 V, sound card 5 V
# Every net on the RP2040's 0.4 mm-pitch pads (0.2 mm wide, 0.2 mm apart): 0.2 mm tracks, the widest that leave such a
# pad with the routing clearance to its neighbours. The matrix lines start there too; the 3.3 V rail feeds only the
# RP2040, its flash and the LED (tens of mA). Patterns: KiCad wildcards.
FINE_NETS = ("3V3", "1V1", "XIN", "XOUT", "SWCLK", "SWDIO", "RESET", "RP_DP", "RP_DN", "QSPI_*", "ROW*", "COL*",
             "LED_RED")


def setup_netclasses(B):
    """Power nets get 0.4 mm tracks (the sound card and the hub draw ~0.15 A from VBUS); the RP2040's nets 0.2 mm."""
    ns = B.b.GetDesignSettings().m_NetSettings
    nc = pcbnew.NETCLASS("Power")
    nc.SetTrackWidth(mm(0.4))
    nc.SetClearance(mm(0.18))
    nc.SetViaDiameter(mm(0.7))
    nc.SetViaDrill(mm(0.35))
    ns.SetNetclass("Power", nc)
    fine = pcbnew.NETCLASS("Fine")
    fine.SetTrackWidth(mm(0.2))
    fine.SetClearance(mm(0.18))
    fine.SetViaDiameter(mm(0.6))
    fine.SetViaDrill(mm(0.3))
    ns.SetNetclass("Fine", fine)
    for n in POWER_NETS:
        ns.SetNetclassPatternAssignment(n, "Power")
    for n in FINE_NETS:
        ns.SetNetclassPatternAssignment(n, "Fine")
    B.b.SynchronizeNetsAndNetClasses(True)


# Design rules on top of the netclasses (JLCPCB standard 2-layer process allows 0.127 mm track/space).
DRC_RULES = """(version 1)
(rule "signal tracks may neck down"
  (condition "A.Type == 'Track'")
  (constraint track_width (min 0.15mm)))
(rule "fine-pitch pads (QFN)"
  (condition "A.Type == 'Pad' && B.Type == 'Pad'")
  (constraint clearance (min 0.15mm)))
(rule "edge-mounted parts (USB-C)"
  (condition "A.Parent.Reference == 'J1'")
  (constraint edge_clearance (min 0mm)))
"""


def patch_project(pro):
    """pcbnew.SaveBoard keeps KiCad's default net classes in the .kicad_pro; write ours so DRC sees them."""
    import json
    d = json.loads(pro.read_text())
    rules = d["board"]["design_settings"]["rules"]
    rules.update(min_track_width=0.15, min_clearance=0.15, min_hole_clearance=0.2, min_copper_edge_clearance=0.3)
    ns = d["net_settings"]
    # DRC limit 0.15 mm (fine-pitch QFN pads are 0.175 apart); signals are routed at 0.3 mm
    default = dict(ns["classes"][0], track_width=0.3, clearance=0.15, via_diameter=0.6, via_drill=0.3)
    power = dict(default, name="Power", track_width=0.4, clearance=0.15, via_diameter=0.7, via_drill=0.35, priority=0)
    fine = dict(default, name="Fine", track_width=0.2, clearance=0.15, via_diameter=0.6, via_drill=0.3, priority=1)
    ns["classes"] = [default, power, fine]
    ns["netclass_patterns"] = [{"netclass": "Power", "pattern": n} for n in POWER_NETS] + \
        [{"netclass": "Fine", "pattern": n} for n in FINE_NETS]
    pro.write_text(json.dumps(d, indent=2))


def build(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    pcb = out_dir / "lira.kicad_pcb"
    (out_dir / "lira.kicad_dru").write_text(DRC_RULES)
    for ext in (".kicad_pro", ".kicad_prl"):  # NewBoard would load the previous run's project (and its rules): the
        pcb.with_suffix(ext).unlink(missing_ok=True)  # same sources must give the same board whatever is in build/
    B = Board(pcb)
    setup_rules(B)
    add_outline(B)
    add_keys(B)
    ports = add_electronics(B, BOARD_L, BOARD_T, BOARD_R, KY) or {}
    holes = add_mounting(B)
    setup_netclasses(B)
    bad = check_mounting(B, holes)
    for h, why in bad:
        print("MOUNT HOLE CONFLICT at %.1f,%.1f: %s" % (h[0], h[1], why))
    edge = check_holes_inside(B)
    for why in edge:
        print("EDGE:", why)
    if bad or edge:
        raise SystemExit(1)
    B.b.BuildConnectivity()
    pcbnew.SaveBoard(str(pcb), B.b)
    patch_project(pcb.with_suffix(".kicad_pro"))
    pcbnew.ExportSpecctraDSN(B.b, str(out_dir / "lira.dsn"))
    write_interface(out_dir / "interface.json", holes, ports)
    print("wrote %s: %d footprints, %d nets, board %.1f x %.1f mm" % (
        pcb.name, len(B.footprints), len(B.nets), BOARD_R - BOARD_L, BOARD_B - BOARD_T))


if __name__ == "__main__":
    build(BUILD / "pcb")
