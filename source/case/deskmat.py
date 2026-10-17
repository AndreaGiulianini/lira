"""Artwork of the desk mat in the desk scene (case/render_desk.py): a technical drawing of the keyboard itself.

    svg(render_dir) -> SVG text, 900 x 400 mm (1 user unit = 1 mm), y down, the mat's back edge on top

Cream ink on warm charcoal with burnt-orange accents: a millimetre ruler, a dot grid, dimension lines around the spot
where the keyboard sits, the side views of the Cherry rows used by the keycaps (from the KeyV2 meshes), the MX
cut-out, and the key matrix with its GPIO pins (from layout.py and the PCB's interface.json).
Where things go matches render_desk.py: the keyboard centre is MAT_KB mm from the mat's top-left corner.
"""
import json
from pathlib import Path

import numpy as np

import layout as L

MAT = (900.0, 400.0)
MAT_KB = (450.0, 150.0)  # keyboard centre on the mat (render_desk.py puts the mat accordingly)
VISIBLE = (130.0, 0.0, 770.0, 330.0)  # what the top-down camera sees of the mat
BG, INK, ACCENT = "#23201e", "#e9e0c9", "#d9662b"
SANS, MONO = "Helvetica Neue, Helvetica, Arial, sans-serif", "Menlo, SF Mono, monospace"


def stl_points(path):
    b = Path(path).read_bytes()
    n = int.from_bytes(b[80:84], "little")
    a = np.frombuffer(b[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return a["v"].reshape(-1, 3)


def hull(pts):
    """Convex hull (monotone chain) of 2D points, counter-clockwise."""
    pts = sorted(set(map(tuple, np.round(pts, 3))))

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]


def text(x, y, s, size=3.2, anchor="start", font=MONO, fill=INK, weight=400, spacing=0.0, opacity=1.0):
    return ('<text x="%.2f" y="%.2f" font-family="%s" font-size="%.2f" font-weight="%d" fill="%s" '
            'text-anchor="%s" letter-spacing="%.2f" opacity="%.2f">%s</text>'
            % (x, y, font, size, weight, fill, anchor, spacing, opacity, s))


def dim_h(x0, x1, y, label, color=INK):
    """Horizontal dimension line with arrows and extension ticks."""
    a = 2.2
    return ('<g stroke="%s" stroke-width="0.35" fill="none">'
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/><line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
            '<path d="M%.2f %.2f l%.2f %.2f l0 %.2f z M%.2f %.2f l%.2f %.2f l0 %.2f z" fill="%s"/></g>'
            % (color, x0, y, x1, y, x0, y - 4, x0, y + 4, x1, y - 4, x1, y + 4,
               x0, y, a * 2, -a / 2, a, x1, y, -a * 2, -a / 2, a, color)
            + text((x0 + x1) / 2, y - 1.6, label, 3.6, "middle", fill=color))


def dim_v(x, y0, y1, label, color=INK):
    a = 2.2
    mid = (y0 + y1) / 2
    return ('<g stroke="%s" stroke-width="0.35" fill="none">'
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
            '<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/><line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f"/>'
            '<path d="M%.2f %.2f l%.2f %.2f l%.2f 0 z M%.2f %.2f l%.2f %.2f l%.2f 0 z" fill="%s"/></g>'
            % (color, x, y0, x, y1, x - 4, y0, x + 4, y0, x - 4, y1, x + 4, y1,
               x, y0, -a / 2, a * 2, a, x, y1, -a / 2, -a * 2, a, color)
            + '<g transform="translate(%.2f %.2f) rotate(-90)">%s</g>' % (x - 1.6, mid, text(0, 0, label, 3.6, "middle",
                                                                                         fill=color)))


def svg(render_dir, case_size, iface):
    W, H = MAT
    kx, ky = MAT_KB
    cw, cd = case_size
    x0, y0, x1, y1 = kx - cw / 2, ky - cd / 2, kx + cw / 2, ky + cd / 2  # keyboard footprint on the mat
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="2700" height="1200" viewBox="0 0 %g %g">' % (W, H),
         '<defs><filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="1.6" numOctaves="2" seed="7"/>'
         '<feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="table" '
         'tableValues="0 0.07"/></feComponentTransfer></filter></defs>',
         '<rect width="%g" height="%g" fill="%s"/>' % (W, H, BG),
         '<rect width="%g" height="%g" filter="url(#grain)"/>' % (W, H)]
    # dot grid every 10 mm, crosses every 50 mm
    dots = ['<g fill="%s" opacity="0.22">' % INK]
    for gx in range(10, int(W), 10):
        for gy in range(10, int(H), 10):
            if gx % 50 or gy % 50:
                dots.append('<circle cx="%d" cy="%d" r="0.35"/>' % (gx, gy))
    dots.append('</g><g stroke="%s" stroke-width="0.3" opacity="0.45">' % INK)
    for gx in range(50, int(W), 50):
        for gy in range(50, int(H), 50):
            dots.append('<path d="M%d %d h5 M%d %d v5" fill="none"/>' % (gx - 2.5, gy, gx, gy - 2.5))
    dots.append("</g>")
    o += dots
    # millimetre rulers along the back edge and the left edge of what the camera sees
    r = ['<g stroke="%s" stroke-width="0.3" opacity="0.8">' % INK]
    for mx in range(0, int(W) + 1, 5):
        r.append('<line x1="%d" y1="0" x2="%d" y2="%.1f"/>' % (mx, mx, 5 if mx % 50 == 0 else 3.2 if mx % 10 == 0 else 2))
    for my in range(0, int(H) + 1, 5):
        r.append('<line x1="%g" y1="%d" x2="%g" y2="%d"/>' % (VISIBLE[0] + 8, my, VISIBLE[0] + 8 + (5 if my % 50 == 0
                                                                                                   else 3.2 if my % 10 == 0 else 2), my))
    r.append("</g>")
    for mx in range(0, int(W) + 1, 50):
        r.append(text(mx + 1.2, 9.5, "%d" % mx, 2.8, opacity=0.8))
    o += r
    # dimension lines around the keyboard, as if it were the object of the drawing
    o.append(dim_h(x0, x1, y0 - 9, "%.1f" % cw, ACCENT))
    o.append(dim_v(x0 - 9, y0, y1, "%.1f" % cd, ACCENT))
    o.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.3" '
             'stroke-dasharray="3 2" opacity="0.6"/>' % (x0 - 3, y0 - 3, cw + 6, cd + 6, INK))
    # title block, top left of the frame
    tx, ty = VISIBLE[0] + 18, 32
    o.append(text(tx, ty, 'LIR<tspan fill="%s">A</tspan>' % ACCENT, 13.0, font=SANS, weight=700, spacing=-0.3))
    for i, line in enumerate(("40%% + NUMPAD · %d KEYS · %d×%d MATRIX" % (len(L.SWITCHES), L.ROWS, L.COLS),
                              "NRF52840 · BLUETOOTH + USB-C · RMK / VIAL",
                              "CASE %.1f × %.1f MM · TILT 8°" % (cw, cd))):
        o.append(text(tx + 0.4, ty + 9 + i * 5.2, line, 3.1, opacity=0.85))
    # Cherry row profiles, side views at 2.5:1 (from the keycap meshes)
    px, py, s = VISIBLE[0] + 18, y0 + 18, 2.5
    o.append(text(px, py - 6, "CHERRY PROFILE · SIDE · 2.5:1", 3.0, opacity=0.85))
    for i, row in enumerate((2, 3, 4)):
        stl = Path(render_dir) / ("keycap-r%d-1x1.stl" % row)
        if not stl.exists():
            continue
        v = stl_points(stl)
        h = hull(v[:, [1, 2]])
        bx, by = px + 2 + i * 0, py + 8 + i * 30
        pts = " ".join("%.2f,%.2f" % (bx + (yy - v[:, 1].min()) * s, by + 22 - zz * s) for yy, zz in h)
        o.append('<polygon points="%s" fill="none" stroke="%s" stroke-width="0.4"/>' % (pts, INK))
        o.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="0.3" opacity="0.6"/>'
                 % (bx - 3, by + 22, bx + 18.5 * s + 3, by + 22, INK))
        o.append(text(bx + 18.6 * s + 6, by + 14, "R%d" % row, 5.0, font=SANS, weight=700,
                      fill=ACCENT if row == 3 else INK))
        o.append(text(bx + 18.6 * s + 6, by + 20, "%.2f MM" % v[:, 2].max(), 2.8, opacity=0.8))
    # MX cut-out at 4:1, right of the keyboard
    cx, cy, s = x1 + 18 + 28, y0 + 40, 4.0
    o.append(text(cx - 28, y0 + 4, "MX CUT-OUT · 4:1", 3.0, opacity=0.85))
    o.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" fill="none" stroke="%s" stroke-width="0.45"/>'
             % (cx - 7 * s, cy - 7 * s + 12, 14 * s, 14 * s, INK))
    o.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" stroke-width="0.4"/>' % (cx, cy + 12, 2 * s, INK))
    for ppx, ppy in ((-3.81, -2.54), (2.54, -5.08)):
        o.append('<circle cx="%.2f" cy="%.2f" r="%.2f" fill="none" stroke="%s" stroke-width="0.4"/>'
                 % (cx + ppx * s, cy + 12 + ppy * s, 0.75 * s, ACCENT))
    o.append(dim_h(cx - 7 * s, cx + 7 * s, cy - 7 * s + 4, "14.00"))
    # the key matrix with its pins, under the keyboard
    rows, cols = iface["matrix"]["rows"], iface["matrix"]["cols"]
    mx0, mx1, my0 = VISIBLE[0] + 40, VISIBLE[2] - 20, y1 + 30
    pitch_x, pitch_y = (mx1 - mx0) / (len(cols) - 1), 15.0
    keys = {(k.row, k.col) for k in L.KEYS}
    o.append(text(mx0 - 22, my0 - 12, "KEY MATRIX · %d ROWS × %d COLUMNS · DIODES COLUMN → ROW" % (len(rows), len(cols)),
                  3.0, opacity=0.85))
    for c, name in enumerate(cols):
        x = mx0 + c * pitch_x
        o.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="0.3" opacity="0.55"/>'
                 % (x, my0 - 5, x, my0 + (len(rows) - 1) * pitch_y + 4, INK))
        o.append(text(x, my0 - 6.5, "C%d" % c, 2.6, "middle", opacity=0.8))
        o.append(text(x, my0 + (len(rows) - 1) * pitch_y + 9, name.replace("_", "."), 2.3, "middle", opacity=0.6))
    for r_, name in enumerate(rows):
        y = my0 + r_ * pitch_y
        hot = r_ == 1  # the row being scanned, in orange
        col = ACCENT if hot else INK
        o.append('<line x1="%.2f" y1="%.2f" x2="%.2f" y2="%.2f" stroke="%s" stroke-width="%.2f" opacity="%.2f"/>'
                 % (mx0 - 8, y, mx1 + 6, y, col, 0.5 if hot else 0.3, 1.0 if hot else 0.55))
        o.append(text(mx0 - 12, y + 1.1, "R%d" % r_, 2.8, "end", fill=col))
        o.append(text(mx0 - 26, y + 1.0, name.replace("_", "."), 2.3, "end", fill=col, opacity=0.7))
        for c in range(len(cols)):
            if (r_, c) not in keys:
                continue
            x = mx0 + c * pitch_x
            # switch (a gap in the column) and its diode (triangle + bar) down to the row line
            o.append('<g stroke="%s" stroke-width="0.35" fill="none">'
                     '<circle cx="%.2f" cy="%.2f" r="1.6"/>'
                     '<path d="M%.2f %.2f l-1.6 -2.6 h3.2 z M%.2f %.2f h3.2" fill="%s"/></g>'
                     % (col, x + 6, y - 6.5, x + 6, y - 0.4, x + 4.4, y - 0.4, col))
    # registration corners of the frame
    for cxx, cyy, dx, dy in ((VISIBLE[0] + 4, 4, 1, 1), (VISIBLE[2] - 4, 4, -1, 1)):
        o.append('<path d="M%.2f %.2f h%.2f M%.2f %.2f v%.2f" stroke="%s" stroke-width="0.5" fill="none"/>'
                 % (cxx, cyy, 8 * dx, cxx, cyy, 8 * dy, ACCENT))
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    import sys
    sys.stdout.write(svg(sys.argv[1], (377.4, 127.8), json.loads(Path(sys.argv[2]).read_text())))
