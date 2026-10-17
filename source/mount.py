"""Top mount: where the plate is fixed to the top frame. Shared by pcb/gen_plate.py (ears, tabs and holes),
case/gen_case.py (inserts in the top frame, pockets in the bottom body) and case/check_fit.py.

The switches clip into the plate and the PCB hangs from the switches (hot-swap sockets); nothing printed holds the
PCB. The plate's top face lies on the flat underside of the top frame:
  * ears at the front and at the sides, outside the PCB outline: M2 screws from below into heat-set inserts in the
    top frame (they can be reached with the PCB already on the switches);
  * tabs at the back, over the PCB's three big holes: the M3 case bolts come up from the bottom body through the
    PCB holes and the tabs into the top frame, so the plate's back edge is clamped between the top frame and the
    bolt bosses.
Slab frame (mm): origin at the front-left corner of the key area, x right, y towards the back.
"""
import layout as L

KW, KD = L.WIDTH * L.U, L.HEIGHT * L.U
PLATE_FRONT = 1.5  # the plate edge is 1.5 mm in front of the key area
EAR_W = 8.0  # width of an ear
FRONT_REACH, SIDE_REACH = 6.5, 7.5  # how far the ears reach out of the plate edge
SCREW_HOLE, BOLT_HOLE = 2.4, 3.4  # plate holes: M2 clearance, M3 clearance
TAB_W, TAB_END = 12.0, 6.0  # back tabs: width, plate past the bolt axis
# front ears: between the M3 case screws (y = -7) and clear of the top frame's seam pins; side ears: between the
# side case screws (gen_case.case_screws)
FRONT_EARS = (6.0, 80.0, 140.0, 220.0, 275.0, KW - 6.0)
SIDE_EARS = (30.0, 70.0)
SCREW = dict(length=5.0, head=(3.8, 2.0))  # M2 x 5 socket head (DIN 912): head diameter x height
INSERT = (3.2, 4.0)  # M2 heat-set insert (3 mm long, 3.2 mm hole) in the top frame: hole diameter, depth


# Plate openings (the FR4 / laser-cut plate in pcb/gen_plate.py and the printed one in case/gen_plate_print.py):
#   * switch: 14 x 14 mm (MX spec)
#   * PCB-mount (screw-in) stabilizer housing: 7 x 16 mm per side. This is the Cherry spec opening (6.65 x 12.3 mm +
#     wire notches, see swillkb kb_builder) made symmetric and a bit larger, so it works whichever way the housing
#     faces and has no slot narrower than 1 mm.
# All inner corners R0.5, so a 1 mm router bit can mill them.
SWITCH = 14.0
STAB = (7.0, 16.0)  # stabilizer opening, horizontal key: width (along x) x height
STAB_DX = {2.0: 11.938, 3.0: 19.05}  # stabilizer offset from the switch centre, by key length
CUT_R = 0.5


def openings():
    """[(cx, cy, w, h)] of every plate opening in the slab frame: switches, then stabilizer housings."""
    out = []
    for k in L.KEYS:
        cx, cy = k.cx * L.U, KD - k.cy * L.U
        out.append((cx, cy, SWITCH, SWITCH))
        if k.stabilized:
            d = STAB_DX[3.0 if max(k.w, k.h) >= 3 else 2.0]
            for s in (-1, 1):
                if k.h > k.w:  # vertical key: stabilizer rotated 90 degrees
                    out.append((cx, cy + s * d, STAB[1], STAB[0]))
                else:
                    out.append((cx + s * d, cy, STAB[0], STAB[1]))
    return out


def ears():
    """[(x0, x1, y0, y1, (hx, hy))]: each ear's rectangle and its M2 hole."""
    out = []
    y0 = -PLATE_FRONT
    for x in FRONT_EARS:
        out.append((x - EAR_W / 2, x + EAR_W / 2, y0 - FRONT_REACH, y0, (x, y0 - FRONT_REACH + 3.0)))
    for y in SIDE_EARS:
        out.append((-SIDE_REACH, 0.0, y - EAR_W / 2, y + EAR_W / 2, (-SIDE_REACH + 3.0, y)))
        out.append((KW, KW + SIDE_REACH, y - EAR_W / 2, y + EAR_W / 2, (KW + SIDE_REACH - 3.0, y)))
    return out


def tabs(bolts):
    """[(x0, x1, y0, y1, (hx, hy))]: back tabs over the PCB's bolt holes (bolts: [(x, y)] from interface.json)."""
    return [(x - TAB_W / 2, x + TAB_W / 2, KD, y + TAB_END, (x, y)) for x, y in bolts]


def outline(bolts, r_out=1.5, r_in=1.0, steps=8):
    """Plate outline (slab x, y), counter-clockwise: the key area (plus PLATE_FRONT) with the ears and tabs, every
    corner rounded (outer r_out, inner r_in: a 1 mm router bit)."""
    front = sorted((e[0], e[1], e[2]) for e in ears() if e[3] == -PLATE_FRONT)  # (x0, x1, y_low)
    left = sorted((e[2], e[3], e[0]) for e in ears() if e[1] == 0.0)  # (y0, y1, x_low)
    right = sorted((e[2], e[3], e[1]) for e in ears() if e[0] == KW)
    back = sorted((t[0], t[1], t[3]) for t in tabs(bolts))
    yf = -PLATE_FRONT
    pts = [(0.0, yf)]
    for x0, x1, y in front:  # along the front edge, left to right, ears hang down
        pts += [(x0, yf), (x0, y), (x1, y), (x1, yf)]
    pts.append((KW, yf))
    for y0, y1, x in right:  # up the right edge, ears stick out
        pts += [(KW, y0), (x, y0), (x, y1), (KW, y1)]
    pts.append((KW, KD))
    for x0, x1, y in reversed(back):  # along the back, right to left, tabs stick out
        pts += [(x1, KD), (x1, y), (x0, y), (x0, KD)]
    pts.append((0.0, KD))
    for y0, y1, x in reversed(left):  # down the left edge
        pts += [(0.0, y1), (x, y1), (x, y0), (0.0, y0)]
    # drop repeated points (an ear flush with a corner)
    clean = []
    for p in pts:
        if not clean or abs(p[0] - clean[-1][0]) + abs(p[1] - clean[-1][1]) > 1e-6:
            clean.append(p)
    if abs(clean[0][0] - clean[-1][0]) + abs(clean[0][1] - clean[-1][1]) < 1e-6:
        clean.pop()
    return fillet(clean, r_out, r_in, steps)


def fillet(pts, r_out, r_in, steps):
    """Round every corner of an axis-aligned polygon (counter-clockwise): convex corners r_out, concave r_in."""
    import math
    n, out = len(pts), []
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        a = (p1[0] - p0[0], p1[1] - p0[1])
        b = (p2[0] - p1[0], p2[1] - p1[1])
        la, lb = math.hypot(*a), math.hypot(*b)
        a, b = (a[0] / la, a[1] / la), (b[0] / lb, b[1] / lb)
        cross = a[0] * b[1] - a[1] * b[0]
        if abs(cross) < 1e-9:  # straight through
            out.append(p1)
            continue
        r = min(r_out if cross > 0 else r_in, la / 2, lb / 2)
        s = (p1[0] - a[0] * r, p1[1] - a[1] * r)  # arc start, on the incoming edge
        c = (s[0] + (-a[1] if cross > 0 else a[1]) * r, s[1] + (a[0] if cross > 0 else -a[0]) * r)  # centre
        a0 = math.atan2(s[1] - c[1], s[0] - c[0])
        sweep = (math.pi / 2) * (1 if cross > 0 else -1)
        for k in range(steps + 1):
            t = a0 + sweep * k / steps
            out.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return out
