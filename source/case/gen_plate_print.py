"""3D-printable plate: the same outline, ears, back tabs, screw holes and switch / stabilizer openings as the FR4 or
laser-cut plate (mount.py), so it fits the case the same way, but stiffened for plastic.

    .venv/bin/python case/gen_plate_print.py     -> build/case/plate-print-{left,right}.stl and .step   (make case)

  * 1.5 mm thick where the switches clip in (MX spec 1.5 +- 0.1 mm): under every key a pocket leaves the plate at
    1.5 mm and gives the switch clips room (15.55 mm square for a 1u key, the whole key for the stabilized ones);
  * between the keys the material goes down to 4 mm: a grid of ribs 3.5 mm wide along the key boundaries, which
    ends 1 mm above the PCB. A 4 mm ribbed PLA plate bends about as much as the 1.6 mm FR4 one;
  * the ears and back tabs stay 1.6 mm thick like the FR4 plate (same screws, the bolt bosses clamp the tabs the same);
  * two pieces for a 256 mm bed, split along key boundaries (a stepped line between the keys, through the middle of a
    rib): each piece has its own ears, and the switches and the PCB tie the two together once assembled.
Print orientation: the top face on the bed (flat and smooth where the switches clip in), ribs up, no supports.
Frame: the case slab frame (mount.py), z up, plate top at gen_case.PLATE_TOP; the pieces are turned over for printing.
"""
import sys
from pathlib import Path

from build123d import (Align, Box, Cylinder, Polyline, Pos, RectangleRounded, Rot, export_step, export_stl, extrude,
                       make_face)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_case as G  # noqa: E402
import layout as L  # noqa: E402
import mount  # noqa: E402
from paths import BUILD  # noqa: E402

CLIP_T = 1.5  # plate thickness where the switches clip in
EAR_T = 1.6  # ears and back tabs: as thick as the FR4 plate
RIB_T = 4.0  # total thickness at the ribs
POCKET = 1.75  # pocket under a key: the key's size less this much on each side (1u: 15.55 mm, room for the clips)
POCKET_STAB = 1.0  # ...less only this much across a stabilized key (the stabilizer wire swings there)
SEAM_AT = 11.0  # split near this x (key units from the left edge): the boundary between the two 3u spacebars
OUT = BUILD / "case"
U, KW, KD = L.U, mount.KW, mount.KD


def seam_x():
    """For each row (0 = back), the key boundary in the main block closest to SEAM_AT."""
    xs = []
    for r in range(L.HEIGHT):
        keys = [k for k in L.KEYS if k.block == "main" and k.y <= r < k.y + k.h]
        bounds = sorted({k.x for k in keys} | {k.x + k.w for k in keys})
        xs.append(min(bounds, key=lambda b: abs(b - SEAM_AT)) * U)
    return xs


def left_region():
    """Plan polygon of the left piece (slab frame): everything left of the stepped seam."""
    xs = seam_x()  # row r spans y = KD - (r + 1) U .. KD - r U
    far = 60.0
    pts = [(-far, -far), (xs[-1], -far)]
    for r in range(L.HEIGHT - 1, 0, -1):  # from the front row up: step at each row boundary
        y = KD - r * U
        pts += [(xs[r], y), (xs[r - 1], y)]
    pts += [(xs[0], KD + far), (-far, KD + far)]
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) + abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    return clean


def prism(pts, z0, z1):
    clean = []
    for x, y in pts:  # the filleted outline repeats a point where two arcs meet
        if not clean or abs(x - clean[-1][0]) + abs(y - clean[-1][1]) > 1e-4:
            clean.append((x, y))
    if abs(clean[0][0] - clean[-1][0]) + abs(clean[0][1] - clean[-1][1]) <= 1e-4:
        clean.pop()
    face = make_face(Polyline(*clean, close=True))
    return Pos(0, 0, z0) * extrude(face, z1 - z0)


def plate():
    top = G.PLATE_TOP
    bolts = [tuple(b) for b in G.PORTS.get("bolts", [])]
    p = prism(mount.outline(bolts), top - EAR_T, top)
    p += Pos(KW / 2, (KD - mount.PLATE_FRONT) / 2, top - RIB_T) * Box(
        KW, KD + mount.PLATE_FRONT, RIB_T - EAR_T + 0.01, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for k in L.KEYS:
        cx, cy = k.cx * U, KD - k.cy * U
        mx = POCKET_STAB if k.stabilized and k.h > k.w else POCKET
        my = POCKET_STAB if k.stabilized and k.w > k.h else POCKET
        p -= Pos(cx, cy, top - RIB_T - 1) * Box(k.w * U - 2 * mx, k.h * U - 2 * my, RIB_T + 1 - CLIP_T,
                                                align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x, y, w, h in mount.openings():
        p -= Pos(x, y, top - RIB_T - 1) * extrude(RectangleRounded(w, h, mount.CUT_R), RIB_T + 2)
    holes = [(hx, hy, mount.SCREW_HOLE) for *_, (hx, hy) in mount.ears()]
    holes += [(hx, hy, mount.BOLT_HOLE) for *_, (hx, hy) in mount.tabs(bolts)]
    for x, y, d in holes:
        p -= Pos(x, y, top - RIB_T - 1) * Cylinder(d / 2, RIB_T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return p


def main():
    assert G.PLATE_TOP - RIB_T >= G.PCB_TOP + 0.8, "the ribs would touch the PCB"
    OUT.mkdir(parents=True, exist_ok=True)
    whole = plate()
    cut = prism(left_region(), G.PLATE_TOP - RIB_T - 5, G.PLATE_TOP + 5)
    for name, piece in (("left", whole & cut), ("right", whole - cut)):
        piece = Rot(180, 0, 0) * piece  # top face down on the bed
        bb = piece.bounding_box()
        piece = Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * piece
        bb = piece.bounding_box()
        assert max(bb.size.X, bb.size.Y) <= G.BED - 6, "plate piece %s too big for the bed" % name
        export_stl(piece, str(OUT / ("plate-print-%s.stl" % name)), tolerance=0.02, angular_tolerance=0.2)
        export_step(piece, str(OUT / ("plate-print-%s.step" % name)))
        print("plate-print-%-5s %6.1f x %5.1f x %4.1f mm  %5.1f cm3" % (name, bb.size.X, bb.size.Y, bb.size.Z,
                                                                       piece.volume / 1000))
    print("printed plate: seam at x = %s mm (rows back to front)" % ", ".join("%.1f" % x for x in seam_x()))


if __name__ == "__main__":
    main()
