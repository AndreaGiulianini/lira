"""Generates the switch plate (FR4 1.6 mm from JLCPCB, or DXF for laser/CNC) from layout.py.

Run with KiCad's Python (make plate). Output: build/plate/plate.kicad_pcb (Edge.Cuts only, same coordinates
as the PCB so the two line up) -> gerbers/DXF are exported by the Makefile.

Outline: the key area (plus 1.5 mm at the front) with the ears and back tabs of the top mount (mount.py): M2 holes in
the ears, M3 holes in the tabs. Openings for the switches and the stabilizers: mount.openings().
"""
import sys
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import pcbnew  # noqa: E402

import json  # noqa: E402

import layout as L  # noqa: E402
import mount  # noqa: E402
from gen_pcb import KX, KY, U, mm, pt  # noqa: E402

PLATE_MARGIN = 0.0  # plate edge = key area edge (keycaps are 0.5 mm inside it)
PLATE_FRONT = mount.PLATE_FRONT  # except at the front (mount.py), still 0.5 mm inside the PCB edge
MIN_WEB = 1.0  # thinnest plate material allowed between two openings


class Plate:
    def __init__(self, path):
        self.b = pcbnew.NewBoard(str(path))
        self.rects = []  # (cx, cy, w, h) of every opening, for the web check

    def _seg(self, x1, y1, x2, y2):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(x1, y1))
        s.SetEnd(pt(x2, y2))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        self.b.Add(s)

    def _arc(self, cx, cy, r, a0):
        """Quarter arc from a0 (a multiple of 90 degrees): its ends are computed exactly, so they land on the very
        same nanometre as the straight edges they join (cos/sin round-off can leave a 1 nm gap, and KiCad then sees
        no closed outline)."""
        unit = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}
        (c0, s0), (c1, s1) = unit[a0 % 360], unit[(a0 + 90) % 360]
        m = math.radians(a0 + 45)
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(pt(cx + r * c0, cy + r * s0), pt(cx + r * math.cos(m), cy + r * math.sin(m)),
                         pt(cx + r * c1, cy + r * s1))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        self.b.Add(s)

    def polygon(self, pts):
        """Closed outline through slab-frame points (mount.outline). The outline repeats a point where two arcs meet:
        a zero-length segment there would leave KiCad two ways to chain the outline, and it closes only now and then."""
        k = [slab_to_kicad(x, y) for x, y in pts]
        for a, b in zip(k, k[1:] + k[:1]):
            if (mm(a[0]), mm(a[1])) != (mm(b[0]), mm(b[1])):
                self._seg(a[0], a[1], b[0], b[1])

    def hole(self, x, y, d):
        s = pcbnew.PCB_SHAPE(self.b)
        s.SetShape(pcbnew.SHAPE_T_CIRCLE)
        kx, ky = slab_to_kicad(x, y)
        s.SetCenter(pt(kx, ky))
        s.SetEnd(pt(kx + d / 2, ky))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(mm(0.1))
        self.b.Add(s)

    def rrect(self, cx, cy, w, h, r, opening=True):
        cx, cy = round(cx, 6), round(cy, 6)
        l, t, rr, b = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
        self._seg(l + r, t, rr - r, t)
        self._seg(rr, t + r, rr, b - r)
        self._seg(rr - r, b, l + r, b)
        self._seg(l, b - r, l, t + r)
        self._arc(rr - r, t + r, r, 270)
        self._arc(rr - r, b - r, r, 0)
        self._arc(l + r, b - r, r, 90)
        self._arc(l + r, t + r, r, 180)
        if opening:
            self.rects.append((cx, cy, w, h))


def build(out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "plate.kicad_pcb"
    P = Plate(path)
    w, h = L.WIDTH * U + 2 * PLATE_MARGIN, L.HEIGHT * U + 2 * PLATE_MARGIN + PLATE_FRONT
    px, py = KX + L.WIDTH * U / 2, KY + L.HEIGHT * U / 2 + PLATE_FRONT / 2  # KiCad y grows towards the front
    bolts = json.loads((out_dir.parent / "pcb/interface.json").read_text())["ports"].get("bolts", [])
    P.polygon(mount.outline(bolts))
    for x0, x1, y0, y1, (hx, hy) in mount.ears():
        P.hole(hx, hy, mount.SCREW_HOLE)
        check_hole(hx, hy, mount.SCREW_HOLE, x0, x1, y0, y1)
    for x0, x1, y0, y1, (hx, hy) in mount.tabs(bolts):
        P.hole(hx, hy, mount.BOLT_HOLE)
        check_hole(hx, hy, mount.BOLT_HOLE, x0, x1, y0, y1)
    for x, y, ow, oh in mount.openings():
        cx, cy = slab_to_kicad(x, y)
        P.rrect(cx, cy, ow, oh, mount.CUT_R)
    check_webs(P, px, py, w, h)
    pcbnew.SaveBoard(str(path), P.b)
    # the outline must close into one board with every opening and hole inside it (what JLCPCB will mill); checked
    # on the saved file, read back
    polys = pcbnew.SHAPE_POLY_SET()
    n_holes = len(P.rects) + len(mount.ears()) + len(bolts)
    saved = pcbnew.LoadBoard(str(path))
    if not saved.GetBoardPolygonOutlines(polys, False) or polys.OutlineCount() != 1 or polys.HoleCount(0) != n_holes:
        path.unlink()
        raise SystemExit("PLATE: the Edge.Cuts outline does not close into one plate with %d openings and holes"
                         % n_holes)
    pts = mount.outline(bolts)
    print("wrote %s: %d openings, %d mounting holes, plate %.1f x %.1f mm with ears and tabs"
          % (path.name, len(P.rects), len(mount.ears()) + len(bolts), max(p[0] for p in pts) - min(p[0] for p in pts),
             max(p[1] for p in pts) - min(p[1] for p in pts)))


def slab_to_kicad(x, y):
    """Case slab frame (mount.py) -> KiCad mm (y grows towards the front)."""
    return KX + x, KY + L.HEIGHT * U - y


def check_hole(x, y, d, x0, x1, y0, y1):
    """A mounting hole keeps >= MIN_WEB to the edges of its ear or tab (the side joined to the plate excepted)."""
    webs = [x - d / 2 - x0, x1 - (x + d / 2), y - d / 2 - y0, y1 - (y + d / 2)]
    webs = [w for w in webs if w < 50]
    if min(webs) < MIN_WEB + 0.5:
        raise SystemExit("PLATE: hole at %.1f,%.1f is %.2f mm from the edge of its ear" % (x, y, min(webs)))


def check_webs(P, cx, cy, w, h):
    """Every opening keeps >= MIN_WEB of material to its neighbours and to the plate edge."""
    left, top = cx - w / 2, cy - h / 2
    problems = []
    for i, (ax, ay, aw, ah) in enumerate(P.rects):
        edge = min(ax - aw / 2 - left, left + w - (ax + aw / 2), ay - ah / 2 - top, top + h - (ay + ah / 2))
        if edge < MIN_WEB:
            problems.append("opening at %.1f,%.1f is %.2f mm from the plate edge" % (ax, ay, edge))
        for (bx, by, bw, bh) in P.rects[i + 1:]:
            gx = abs(ax - bx) - (aw + bw) / 2
            gy = abs(ay - by) - (ah + bh) / 2
            gap = max(gx, gy)
            if gap < MIN_WEB:
                problems.append("openings at %.1f,%.1f and %.1f,%.1f: web %.2f mm" % (ax, ay, bx, by, gap))
    for p in problems:
        print("PLATE:", p)
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    from paths import BUILD
    build(BUILD / "plate")
