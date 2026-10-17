"""3D model of the headset jack (Hroparts PJ-320D-4A), which KiCad's library has no model for: without it the PCB and
case renders show an empty jack window.

    .venv/bin/python case/jack_model.py     -> lib/lira.3dshapes/Jack_3.5mm_PJ-320D-4A.step   (make renders)

Built in the frame of KiCad's footprint Connector_Audio:Jack_3.5mm_KoreanHropartsElec_PJ-320D-4A_Horizontal (x along
the jack, the plug goes in at x = -8.35; model y = -footprint y; z up from the board), with the sizes of the HRO
drawing (PJ-320D-4A_C95562.pdf): body 12.1 x 6.1 x 5.0 mm, nose 5.0 mm across and 2.0 mm long, hole 3.6 mm, two
0.75 mm pegs 0.7 mm long 7.0 mm apart; black nylon body, gold-plated contacts.
"""
from pathlib import Path

from build123d import Align, Axis, Box, Color, Compound, Cylinder, Pos, Rot, export_step

OUT = Path(__file__).resolve().parents[1] / "lib/lira.3dshapes/Jack_3.5mm_PJ-320D-4A.step"
BODY = (-6.35, 5.75, 3.05, 5.0)  # x from, x to, half width, height (footprint fab outline, drawing)
NOSE = (-8.35, 2.5)  # front face x, radius
HOLE_R, HOLE_DEPTH = 1.8, 11.0
PEGS = (-4.75, 2.25)  # x of the locating pegs (footprint)
CONTACTS = ((-0.15, 1), (-3.15, 1), (3.85, 1), (4.95, -1))  # pads R1, R2, T on footprint y = -3.25, S on +3.25


def model():
    x0, x1, hw, h = BODY
    body = Pos((x0 + x1) / 2, 0, 0) * Box(x1 - x0, 2 * hw, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    front, r = NOSE
    axis = Pos(0, 0, h / 2) * Rot(0, 90, 0)  # cylinders along x, at mid height
    body += Pos(front, 0, 0) * axis * Cylinder(r, x0 - front, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body -= Pos(front - 0.1, 0, 0) * axis * Cylinder(HOLE_R, HOLE_DEPTH, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x in PEGS:
        body += Pos(x, 0, 0) * Cylinder(0.375, 0.7, align=(Align.CENTER, Align.CENTER, Align.MAX))
    body.color, body.label = Color(0.08, 0.08, 0.08), "body"
    contacts = []
    for x, side in CONTACTS:  # a bent tab down the side of the body onto its pad
        tab = Pos(x, side * (hw + 0.1), 0) * Box(0.8, 0.2, 1.6, align=(Align.CENTER, Align.CENTER, Align.MIN))
        foot = Pos(x, side * (hw + 0.6), 0) * Box(0.8, 1.2, 0.15, align=(Align.CENTER, Align.CENTER, Align.MIN))
        part = tab + foot
        part.color, part.label = Color(0.85, 0.68, 0.3), "contact"
        contacts.append(part)
    return Compound(children=[body, *contacts], label="PJ-320D-4A")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    m = model()
    export_step(m, str(OUT))
    bb = m.bounding_box()
    print("wrote %s: %.1f x %.1f x %.1f mm" % (OUT.relative_to(OUT.parents[2]), bb.size.X, bb.size.Y, bb.size.Z))


if __name__ == "__main__":
    main()
