"""Parametric 3D-printable case for Lira, after the Apple M0110 (1984): a tilted slab with a flat deck,
shallow perimeter chamfers and a close-fitting key well, floating on a recessed base.

    .venv/bin/python case/gen_case.py         -> build/case/*.step, *.stl (one file per printed piece)

Top mount (mount.py): the plate is screwed to the underside of the top frame and the PCB hangs from the switches,
so no printed part has to hold the PCB flat. Two bodies, both printable without supports:
  * top frame   - deck, chamfers, key wells (numpad and main block separated by a rib, like an M0110 + M0120
                  side by side); no text or logo. Its flat underside carries the plate: M2 heat-set inserts for the
                  plate's ears, M3 inserts for the case screws and bolts. Printed deck up.
  * bottom body - closes the case: room for the PCB and its parts (backstops 0.5 mm under the PCB at the back),
                  pockets for the plate's ears and screw heads, parting groove, solid base underneath with the battery
                  pocket, port window and headset jack window at the back, rubber feet. Printed as it sits on
                  the desk.
If the printer bed is smaller than the case, each body is cut in two along staggered seams (the top frame
bridges the seam of the bottom body and vice versa) with alignment pins; the plate, screwed across the top frame's
seam, ties its two halves together; M3 screws join the two bodies.

Frames: "slab" frame = origin at the front-left corner of the key area on the deck, x right, y towards the back,
z up (perpendicular to the deck). "world" = the desk, the slab tilted by TILT degrees.
Reads the PCB geometry from build/pcb/interface.json (written by pcb/gen_pcb.py).
"""
import json
import math
import sys
from pathlib import Path

from build123d import (Align, Box, Cylinder, Keep, Location, Plane, Pos, RectangleRounded, Vector,
                       export_step, export_stl, extrude, loft, split)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import layout as L  # noqa: E402
import mount  # noqa: E402

from paths import BUILD  # noqa: E402

IFACE = json.loads((BUILD / "pcb/interface.json").read_text())
OUT = BUILD / "case"

# ------------------------------------------------------------------------------------------- parameters (mm)
TILT = 8.0  # typing angle (M0110: ~11-12 deg)
FRONT, SIDE = 26.0, 22.0  # bezels at deck level
WALL_BACK = 2.2  # wall behind the PCB, measured below the PCB (the back face is vertical, the slab is tilted)
CLEAR = 0.5  # PCB to case walls (front and back)
CLEAR_X = 1.0  # PCB to the side walls: a 335 mm tray printed in two halves can shrink by ~1 mm
WELL_CLEAR = 0.5  # keycap area to key well walls
PLATE_TOP = -6.5  # keycap skirts end up roughly level with the deck, as on the M0110
TOP_T = -PLATE_TOP  # top frame thickness, deck -> parting line: the plate's top face lies on the frame's underside
PLATE_T = 1.6  # FR4 plate (a 1.5 mm aluminium plate leaves 0.1 mm, taken up by the bolts)
PLATE_BOT = PLATE_TOP - PLATE_T
PCB_TOP = PLATE_TOP - 5.0  # MX spec: plate top to PCB top
PCB_T = IFACE["pcb"]["thickness"]
PCB_BOT = PCB_TOP - PCB_T
FLOOR_GAP = 3.0  # room for the hotswap sockets (1.85 mm) and the switch pins under the PCB
FLOOR_TOP = PCB_BOT - FLOOR_GAP
FLOOR_T = 2.0
SLAB_H = -(FLOOR_TOP - FLOOR_T)  # deck -> slab bottom
GROOVE_H, GROOVE_D = 1.2, 1.0  # parting groove all around
PLAN_R = 6.0  # corner radius seen from above
CH_ANGLE = 10.0  # perimeter chamfers, degrees steeper than the deck
CH = {"front": 16.0, "back": 10.0, "side": 5.0}  # chamfer widths
FRONT_LIFT = 1.5  # slab front edge above the desk
BASE_INSET = 8.0  # base recess under the slab, behind 45 degree chamfers (printable)
FRONT_CHAMFER = 44.0  # degrees from the vertical (world) of the base chamfer at the front
EAR_CLEAR = 0.6  # plate ears and their screw heads to the bottom body
INSERT_M3 = (4.0, 4.5)  # M3 heat-set inserts (case screws), short type (3 mm) + room for the screw tip
SCREW_M3 = (3.4, 6.4, 8.0)  # clearance hole, head counterbore, shank length below the parting line
PIN = (3.3, 7.6)  # alignment pins at the seams: 3 x 14 mm dowel/filament, hole depth per side (0.6 mm spare)
FEET = (12.5, 1.0)  # rubber feet recess diameter, depth
STRIP_CLEAR = 6.5  # room under the PCB in the electronics strip (JST-PH plug ~4.8 mm, USB-C 3.2 mm)
# battery pocket L x W x depth below the floor: a 603450 cell (~1200 mAh, nominal 50 x 34 x 6, real cells with
# the protection board up to 52 x 35 x 6.5) + room for the lead
POCKET = (56.0, 37.5, 7.5)
POCKET_AT = (6.0, 42.5)  # front-left corner of the battery pocket (slab frame), under the numpad
BOLT = (6.4, 3.4, 6.4)  # strip bolts: boss diameter (0.5 mm play in the 7.4 mm PCB hole), clearance hole, counterbore
BOLT_SHOULDER = 9.5  # below the PCB the bosses widen: backstops for the PCB's back strip...
BACKSTOP_GAP = 0.5  # ...this far under it (the PCB hangs from the switches; a USB cable can't bend it further)
USB_POST = 0.4  # post under the USB-C receptacle, this far below it: limits how far a cable can bend the PCB
USB_H = 3.26  # HRO TYPE-C-31-M-12 height (datasheet)
RESET_HOLE, RESET_SLEEVE = 1.8, 4.5  # paperclip hole, and a sleeve guiding it up to 1 mm below the button
RESET_H = 1.5  # TS-1187A height (datasheet)
WINDOW_Z = (-19.0, -TOP_T + 1)  # port window in the back wall (slab z): USB-C plug overmold, switch, LEDs; open
# up to the parting line (the top frame is its top edge), or the switch lever could not pass while the PCB goes in
WINDOW_USB = 8.5  # the window reaches at least this far either side of the USB-C axis (bulky overmolds)
JACK_AXIS = 2.5  # PJ-320D-4A headset jack: 5 mm body under the PCB, plug axis in its middle
JACK_W = 6.0  # its own window in the back wall, this far either side of the axis (overmolds up to 9 mm), up to the
# parting line (the jack's nose passes through the wall)
JACK_FLOOR = -20.2  # its floor (slab z): low enough for a 9 mm overmold, high enough not to leave a sliver of the
# base's chamfer
BED = 256.0  # printer bed (square); bodies wider than BED - 6 are split

KW, KD = IFACE["key_area"]
PCB = IFACE["pcb"]
PORTS = IFACE.get("ports", {})
t = math.radians(TILT)
# the back face is vertical, so the wall gets thinner below the deck: WALL_BACK is kept down to CAVITY_REF (the
# parts on the PCB bottom up to the module and the USB-C receptacle keep the full clearance to the back wall), and
# below it the cavity follows the back face (see cut_behind)
CAVITY_REF = PCB_BOT - 2.5
BACK = max(20.0, PCB["back"] - KD + CLEAR + WALL_BACK - CAVITY_REF * math.tan(t))
X_L, X_R, Y_F, Y_B = -SIDE, KW + SIDE, -FRONT, KD + BACK
U = L.U

TY = FRONT * math.cos(t)
TZ = FRONT_LIFT + (FRONT + SLAB_H * math.tan(t)) * math.sin(t) + SLAB_H * math.cos(t)
SLAB = Location((0, TY, TZ), (TILT, 0, 0))
DEPTH_W = (Y_B - Y_F) * math.cos(t)  # world depth of the case (front and back faces are vertical)


def w_pt(x, y, z):
    return Vector(x, y * math.cos(t) - z * math.sin(t) + TY, y * math.sin(t) + z * math.cos(t) + TZ)


def w_dir(x, y, z):
    return Vector(x, y * math.cos(t) - z * math.sin(t), y * math.sin(t) + z * math.cos(t))


def slab_box(x0, x1, y0, y1, z0, z1):
    return SLAB * Pos(x0, y0, z0) * Box(x1 - x0, y1 - y0, z1 - z0, align=(Align.MIN,) * 3)


def slab_cyl(x, y, z0, z1, d):
    return SLAB * Pos(x, y, z0) * Cylinder(d / 2, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def keep_below(part, p, n):
    """Keep what is under the plane through slab point p with slab normal n."""
    return split(part, bisect_by=Plane(origin=w_pt(*p), z_dir=w_dir(*n)), keep=Keep.BOTTOM)


def keep_above(part, p, n):
    return split(part, bisect_by=Plane(origin=w_pt(*p), z_dir=w_dir(*n)), keep=Keep.TOP)


def outline_prism(inset=0.0, z0=-5.0, z1=200.0):
    """World-vertical prism of the case outline (vertical front, back and side faces)."""
    sk = RectangleRounded(X_R - X_L - 2 * inset, DEPTH_W - 2 * inset, PLAN_R - inset)
    return Pos((X_L + X_R) / 2, DEPTH_W / 2, z0) * extrude(sk, z1 - z0)


# ------------------------------------------------------------------------------------------------ features

def key_well_boxes():
    """Key wells: per row, contiguous keys merged into one box (keycap area + WELL_CLEAR)."""
    boxes = []
    for block in ("numpad", "main"):
        for r in range(L.HEIGHT):
            spans = sorted((k.x, k.x + k.w) for k in L.SWITCHES if k.block == block and k.y <= r < k.y + k.h)
            merged = []
            for a, b in spans:
                if merged and a <= merged[-1][1] + 1e-6:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            for a, b in merged:
                boxes.append(slab_box(a * U - WELL_CLEAR, b * U + WELL_CLEAR, KD - (r + 1) * U - WELL_CLEAR,
                                      KD - r * U + WELL_CLEAR, -TOP_T - 1, 5))
    return boxes


def cut_behind(part):
    """Trim a cavity at a vertical plane (parallel to the outer back face) through the PCB's back edge clearance at
    CAVITY_REF: above CAVITY_REF the cavity keeps its full depth, below it the wall stays WALL_BACK thick."""
    y = PCB["back"] + CLEAR
    return split(part, bisect_by=Plane(origin=w_pt(0, y, CAVITY_REF), z_dir=(0, 1, 0)), keep=Keep.BOTTOM)


def case_screws():
    """M3 screws from below, joining bottom body and top frame (slab x, y). Four along the front, one either side
    of each frame seam (the top frame and the bottom body are split at staggered x), and two per side; the back is
    held by the three bolt bosses."""
    pts = [(x, -7.0) for x in (30.0, 130.0, 210.0, KW - 30.0)]
    for x in (PCB["left"] - CLEAR_X - 7.0, PCB["right"] + CLEAR_X + 7.0):  # clear of the base undercut
        pts += [(x, 12.0), (x, KD + 6.0)]
    return pts


def seam_positions():
    """Seam x (slab frame) for the top frame and the bottom body, staggered; None if the body fits the bed."""
    width = X_R - X_L
    if width <= BED - 6:
        return None, None
    return X_L + width * 0.48, X_L + width * 0.60


def top_frame():
    p = outline_prism()
    p = keep_below(p, (0, 0, 0), (0, 0, 1))
    p = keep_above(p, (0, 0, -TOP_T), (0, 0, 1))
    a = math.radians(CH_ANGLE)
    p = keep_below(p, (0, Y_F + CH["front"], 0), (0, -math.sin(a), math.cos(a)))
    p = keep_below(p, (0, Y_B - CH["back"], 0), (0, math.sin(a), math.cos(a)))
    p = keep_below(p, (X_L + CH["side"], 0, 0), (-math.sin(a), 0, math.cos(a)))
    p = keep_below(p, (X_R - CH["side"], 0, 0), (math.sin(a), 0, math.cos(a)))
    for b in key_well_boxes():
        p -= b
    d, depth = INSERT_M3
    for x, y in case_screws() + [tuple(b) for b in PORTS.get("bolts", [])]:
        p -= slab_cyl(x, y, -TOP_T - 1, -TOP_T + depth, d)
    d, depth = mount.INSERT  # top mount: M2 inserts for the plate's ears
    for *_, (x, y) in mount.ears():
        p -= slab_cyl(x, y, -TOP_T - 1, -TOP_T + depth, d)
    return p


def base():
    """Solid under the slab, recessed by BASE_INSET behind a chamfer (slab frame). At the front the chamfer starts
    at the bottom edge of the vertical front face (no ledge) and runs in less, so that it stays at FRONT_CHAMFER
    from the vertical in the world: the slab tilt would make a 45 degree slab-frame chamfer 53 degrees there."""
    def plane(z, cy):
        return Plane(origin=w_pt((X_L + X_R) / 2, cy, z), z_dir=w_dir(0, 0, 1), x_dir=(1, 0, 0))
    z0 = -SLAB_H + 0.01
    y_front = Y_F + z0 * math.tan(t) - 0.5  # 0.5 mm in front of the vertical front face at the slab bottom (the
    # outline prism trims it: the face runs down another ~0.6 mm, then the chamfer; no coincident edges)
    ta = math.tan(math.radians(FRONT_CHAMFER))
    front_in = BASE_INSET * (ta * math.cos(t) - math.sin(t)) / (math.cos(t) + ta * math.sin(t))
    oy0, oy1 = y_front, Y_B
    iy0, iy1 = y_front + front_in, Y_B - BASE_INSET
    outer = RectangleRounded(X_R - X_L, oy1 - oy0, PLAN_R)
    inner = RectangleRounded(X_R - X_L - 2 * BASE_INSET, iy1 - iy0, 0.5)  # sharp: gentler corners
    chamfer = loft([plane(z0, (oy0 + oy1) / 2) * outer, plane(z0 - BASE_INSET, (iy0 + iy1) / 2) * inner])
    column = extrude(plane(z0 - BASE_INSET + 0.01, (iy0 + iy1) / 2) * inner, -80)
    return chamfer + column


def bottom_body():
    p = outline_prism()
    p = keep_below(p, (0, 0, -TOP_T), (0, 0, 1))
    p = keep_above(p, (0, 0, -SLAB_H), (0, 0, 1))
    p += base()
    p = p & outline_prism()  # vertical front/back faces also for the base
    p = split(p, bisect_by=Plane.XY, keep=Keep.TOP)  # desk
    # parting groove
    band = keep_above(keep_below(outline_prism(), (0, 0, -TOP_T), (0, 0, 1)), (0, 0, -TOP_T - GROOVE_H), (0, 0, 1))
    p -= band - outline_prism(GROOVE_D)
    # room for the PCB with its parts (it hangs from the switches: nothing to rest on)
    p -= cut_behind(slab_box(PCB["left"] - CLEAR_X, PCB["right"] + CLEAR_X, PCB["front"] - CLEAR, PCB["back"] + CLEAR,
                             FLOOR_TOP, 5))
    # pockets for the plate's ears and the heads of their M2 screws
    head_d, head_h = mount.SCREW["head"]
    for x0, x1, y0, y1, _ in mount.ears():
        p -= slab_box(x0 - EAR_CLEAR, x1 + EAR_CLEAR, y0 - EAR_CLEAR, y1 + EAR_CLEAR, PLATE_BOT - head_h - EAR_CLEAR, 5)
    # electronics strip: extra room under the parts on the back of the PCB
    strip_floor = PCB_BOT - STRIP_CLEAR
    p -= cut_behind(slab_box(PCB["left"] - CLEAR_X, PCB["right"] + CLEAR_X, KD + 0.5, PCB["back"] + CLEAR,
                             strip_floor, FLOOR_TOP + 1))
    if "usb" in PORTS:  # post under the USB-C receptacle (in front of the window)
        u = PORTS["usb"]
        p += slab_box(u["x"] - 3.0, u["x"] + 3.0, u["y"] - 6.2, u["y"] - 2.2, strip_floor - 0.5, PCB_BOT - USB_H - USB_POST)
    # battery pocket; its back end reaches under the electronics strip, where the JST connector is
    bl, bw, bh = POCKET
    bx, by = POCKET_AT
    assert by + bw > KD + 0.5, "the battery pocket must reach the strip for the lead"
    p -= slab_box(bx, bx + bl, by, by + bw, FLOOR_TOP - bh, FLOOR_TOP + 1)
    if "window" in PORTS:  # port window in the back wall: power switch, two LEDs, USB-C
        w = PORTS["window"]
        x0, x1 = w["x0"], w["x1"]
        if "usb" in PORTS:
            x0, x1 = min(x0, PORTS["usb"]["x"] - WINDOW_USB), max(x1, PORTS["usb"]["x"] + WINDOW_USB)
        p -= slab_box(x0, x1, PCB["back"] - 2, Y_B + 20, *WINDOW_Z)
    if "jack" in PORTS:  # headset jack window
        jx = PORTS["jack"]["x"]
        p -= slab_box(jx - JACK_W, jx + JACK_W, PCB["back"] - 2, Y_B + 20, JACK_FLOOR, WINDOW_Z[1])
    if "reset" in PORTS:  # paperclip hole from the underside, with a guide sleeve up to near the button
        r = PORTS["reset"]
        p += slab_cyl(r["x"], r["y"], strip_floor - 0.5, PCB_BOT - RESET_H - 1.0, RESET_SLEEVE)
        p -= slab_cyl(r["x"], r["y"], -SLAB_H - 80, PCB_BOT, RESET_HOLE)
    # strip bolts: a boss through the PCB hole up to the plate's back tab, which it clamps against the top frame
    # (M3 x 20 from below, through boss, PCB hole and tab); a shoulder under the PCB is its backstop
    boss, hole, cb = BOLT
    for x, y in PORTS.get("bolts", []):
        p += slab_cyl(x, y, strip_floor - 0.5, PCB_BOT - BACKSTOP_GAP, BOLT_SHOULDER)
        p += slab_cyl(x, y, strip_floor - 0.5, PLATE_BOT, boss)
        p -= slab_cyl(x, y, strip_floor - 3.0, -TOP_T + 1, hole)
        p -= slab_cyl(x, y, -SLAB_H - 80, strip_floor - 3.0, cb)
    # case screws: clearance hole up to the top frame, counterbore from below
    hole, cb, shank = SCREW_M3
    for x, y in case_screws():
        p -= slab_cyl(x, y, -TOP_T - shank - 0.01, -TOP_T + 1, hole)
        p -= slab_cyl(x, y, -SLAB_H - 80, -TOP_T - shank, cb)
    # rubber feet
    bb = p.bounding_box()
    fd, fdep = FEET
    for fx in (bb.min.X + BASE_INSET + 18, bb.max.X - BASE_INSET - 18):
        for fy in (BASE_INSET + 14, DEPTH_W - BASE_INSET - 14):
            p -= Pos(fx, fy, -1) * Cylinder(fd / 2, fdep + 1, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return p


def cut_at_seam(part, x, pins):
    """Split a body at slab/world x and drill pin holes into both faces."""
    left = split(part, bisect_by=Plane.YZ.offset(x), keep=Keep.BOTTOM)
    right = split(part, bisect_by=Plane.YZ.offset(x), keep=Keep.TOP)
    d, depth = PIN
    for (y, z) in pins:
        c = w_pt(x, y, z)
        pin = Pos(c.X - depth, c.Y, c.Z) * Cylinder(d / 2, 2 * depth, rotation=(0, 90, 0),
                                                    align=(Align.CENTER, Align.CENTER, Align.MIN))
        left -= pin
        right -= pin
    return [left, right]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    top, bottom = top_frame(), bottom_body()
    seam_top, seam_bot = seam_positions()
    pieces = {}
    if seam_top is None:
        pieces = {"top": top, "bottom": bottom}
    else:
        tl, tr = cut_at_seam(top, seam_top, [(Y_F + 20, -3.0), (Y_B - 11, -3.0)])  # clear of the chamfers
        bl, br = cut_at_seam(bottom, seam_bot, [(Y_F + 12, -12.5), (KD - 8, -SLAB_H - 6)])
        pieces = {"top-left": tl, "top-right": tr, "bottom-left": bl, "bottom-right": br}
    for old in list(OUT.glob("case-*.step")) + list(OUT.glob("case-*.stl")):  # e.g. halves left from a smaller BED
        old.unlink()
    for name, part in pieces.items():
        bb = part.bounding_box()
        export_step(part, str(OUT / ("case-%s.step" % name)))
        export_stl(part, str(OUT / ("case-%s.stl" % name)), tolerance=0.02, angular_tolerance=0.2)
        print("%-13s %6.1f x %5.1f x %5.1f mm  %6.1f cm3" % (name, bb.size.X, bb.size.Y, bb.size.Z, part.volume / 1000))
    print("case %.1f x %.1f mm, rear height %.1f mm, tilt %g deg" % (X_R - X_L, DEPTH_W, w_pt(0, Y_B, 0).Z, TILT))


if __name__ == "__main__":
    main()
