"""Single source of truth for the physical layout of the keyboard.

Main block = "Agar mini" 40% (4 rows, 13u wide, empty 1.25u corners on the bottom row, 3u + 3u split spacebar)
+ a 4x4 numpad on the left, separated by a 0.5u gap. Every key is an MX switch.

Everything else (preview, KLE, RMK keyboard.toml, vial.json, PCB placement, plate, case) is generated from KEYS.
Units: keyboard units (1u = 19.05 mm), origin = top-left corner of the top-left key.

Run `python3 layout.py` to regenerate <build>/layout.svg and <build>/kle.json.
"""
import json

from paths import BUILD

U = 19.05  # mm
NUMPAD_W = 4
GAP = 0.5  # between numpad and main block
MAIN_W = 13
MX = NUMPAD_W + GAP  # x of the main block
WIDTH, HEIGHT = MX + MAIN_W, 4


class Key:
    def __init__(self, label, x, y, w=1.0, h=1.0, block="main"):
        self.label, self.x, self.y, self.w, self.h, self.block = label, x, y, w, h, block
        self.row = self.col = None  # matrix position, set by assign_matrix()

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    @property
    def stabilized(self):
        return self.w >= 2 or self.h >= 2

    def __repr__(self):
        return "Key(%r, x=%g, y=%g, w=%g, h=%g, rc=%s)" % (self.label, self.x, self.y, self.w, self.h,
                                                            (self.row, self.col))


KEYS = []


def place(y, x, block, items):
    """items: label (1u) | (label, w) | (label, w, h) | (None, w) for an empty space."""
    for it in items:
        if isinstance(it, str):
            it = (it, 1)
        label, w, h = it[0], it[1], it[2] if len(it) > 2 else 1
        if label is not None:
            KEYS.append(Key(label, x, y, w, h, block))
        x += w
    return x


# Numpad: a standard numpad without its top row (num lock, /, *, -) -> − and + move to the 4th column.
place(0, 0, "numpad", ["7", "8", "9", "−"])
place(1, 0, "numpad", ["4", "5", "6", "+"])
place(2, 0, "numpad", ["1", "2", "3", ("enter", 1, 2)])
place(3, 0, "numpad", [("0", 2), "."])

# Main block: Agar mini. Numbers, - = [ ] ' / and arrows live on layers (as printed on the Agar keycaps).
place(0, MX, "main", ["esc"] + list("QWERTYUIOP") + ["\\", "delete"])
place(1, MX, "main", [("tab", 1.25)] + list("ASDFGHJKL;") + [("return", 1.75)])
place(2, MX, "main", [("shift", 1.75)] + list("ZXCVBNM,.") + [("shift", 1.25), "fn"])
BLOCKER = 1.25  # empty corners of the bottom row
place(3, MX, "main", [(None, BLOCKER), "option", ("⌘", 1.25), ("space", 3), ("space", 3), ("⌘", 1.25), "option",
                      (None, BLOCKER)])
SWITCHES = KEYS  # every key is an MX switch


def assign_matrix():
    """Matrix rows = physical rows. Matrix columns = 17 column lines anchored on the fullest row (row 0);
    keys of the other rows go to the nearest free line, keeping left-to-right order (keeps PCB routing short)."""
    anchors = [k.cx for k in sorted((k for k in KEYS if k.y == 0), key=lambda k: k.x)]
    for r in range(HEIGHT):
        row = sorted((k for k in KEYS if k.y == r), key=lambda k: k.x)
        n, m = len(row), len(anchors)
        # monotone matching of n keys onto m anchors minimizing total |dx| (classic DP)
        inf = float("inf")
        cost = [[inf] * (m + 1) for _ in range(n + 1)]
        for j in range(m + 1):
            cost[0][j] = 0.0
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost[i][j] = min(cost[i][j - 1], cost[i - 1][j - 1] + abs(row[i - 1].cx - anchors[j - 1]))
        i, j = n, m
        while i > 0:
            if cost[i][j] == cost[i][j - 1]:
                j -= 1
            else:
                row[i - 1].row, row[i - 1].col = r, j - 1
                i, j = i - 1, j - 1
    return len(anchors)


COLS = assign_matrix()
ROWS = HEIGHT


def check():
    for r in range(HEIGHT):
        main = [k for k in KEYS if k.block == "main" and k.y == r]
        # every main row spans exactly 13u (row 3 has empty corners on both sides)
        span = sum(k.w for k in main) + (2 * BLOCKER if r == 3 else 0)
        assert abs(span - MAIN_W) < 1e-9, (r, span)
    rc = [(k.row, k.col) for k in KEYS]
    assert None not in (p for pair in rc for p in pair)
    assert len(rc) == len(set(rc)), "two keys on the same matrix position"
    # no overlapping keys
    for a in KEYS:
        for b in KEYS:
            if a is not b:
                assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y, (a, b)


# ---------------------------------------------------------------------------------------------------- outputs

def kle(via=False):
    """keyboard-layout-editor.com raw data (paste into the Raw data tab).
    via=True: VIA/Vial style, the only legend is "row,col" (what rmkit and Vial read)."""
    rows = []
    for r in range(HEIGHT):
        cursor, out = 0.0, []
        for k in sorted((k for k in KEYS if k.y == r), key=lambda k: k.x):
            props = {}
            if abs(k.x - cursor) > 1e-9:
                props["x"] = round(k.x - cursor, 4)
            if k.w != 1:
                props["w"] = k.w
            if k.h != 1:
                props["h"] = k.h
            if props:
                out.append(props)
            if via:
                out.append("%d,%d" % (k.row, k.col))
            else:
                out.append("%s\n\n\n\n\n\n\n\n\n%d,%d" % (k.label, k.row, k.col))  # matrix pos as front legend
            cursor = k.x + k.w
        rows.append(out)
    return rows


# M0110-inspired palette: warm beige case, cream alphas, darker warm grey modifiers.
CASE, ALPHA, MOD, INK, DIM = "#d9d0bd", "#f3eee4", "#cfc5b2", "#3b3631", "#8a8173"
ALPHAS = set("QWERTYUIOPASDFGHJKLZXCVBNM") | set("0123456789.,;'/[]−+\\")


def svg(show_matrix=False):
    s = 40.0  # px per u
    pad, bezel = 60.0, 0.45 * s
    W, H = WIDTH * s + 2 * pad, HEIGHT * s + 2 * pad + 40
    o = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
         'font-family="Helvetica Neue, Helvetica, Arial, sans-serif">' % (W, H, W, H),
         '<rect width="100%" height="100%" fill="#faf8f4"/>']
    # case silhouette (placeholder: real case comes later)
    o.append('<rect x="%g" y="%g" width="%g" height="%g" rx="14" fill="%s"/>' % (
        pad - bezel, pad - bezel, WIDTH * s + 2 * bezel, HEIGHT * s + 2 * bezel, CASE))
    for k in KEYS:
        x, y, w, h = pad + k.x * s, pad + k.y * s, k.w * s, k.h * s
        fill = ALPHA if k.label in ALPHAS else MOD
        if k.label == "space":
            fill = ALPHA
        o.append('<rect x="%g" y="%g" width="%g" height="%g" rx="5" fill="%s" stroke="#b5ab98" stroke-width="1"/>'
                 % (x + 1.5, y + 1.5, w - 3, h - 3, fill))
        o.append('<rect x="%g" y="%g" width="%g" height="%g" rx="4" fill="#ffffff" fill-opacity="0.35"/>'
                 % (x + 6, y + 4, w - 12, h - 13))
        big = len(k.label) <= 2
        o.append('<text x="%g" y="%g" font-size="%d" fill="%s"%s>%s</text>' % (
            x + (w / 2 if big else 9), y + (17 if big else 15), 13 if big else 9, INK,
            ' text-anchor="middle"' if big else "", k.label.replace("&", "&amp;").replace("<", "&lt;")))
        if k.w != 1 or k.h != 1:
            o.append('<text x="%g" y="%g" font-size="8" fill="%s" text-anchor="end">%gu</text>' % (
                x + w - 7, y + h - 8, DIM, k.w if k.h == 1 else k.h))
        if show_matrix:
            o.append('<text x="%g" y="%g" font-size="8" fill="#b0503c">%d,%d</text>' % (
                x + 7, y + h - 8, k.row, k.col))
    # dimensions
    y0 = pad + HEIGHT * s + bezel + 22
    o.append('<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s"/>' % (pad, y0, pad + WIDTH * s, y0, DIM))
    o.append('<text x="%g" y="%g" font-size="12" fill="%s" text-anchor="middle">key area %.1f × %.1f mm '
             '(%gu × %gu) · %d keys · matrix %d×%d</text>' % (
                 pad + WIDTH * s / 2, y0 + 16, INK, WIDTH * U, HEIGHT * U, WIDTH, HEIGHT, len(SWITCHES), ROWS, COLS))
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    check()
    out = BUILD
    out.mkdir(parents=True, exist_ok=True)
    (out / "layout.svg").write_text(svg(), encoding="utf-8")
    (out / "layout-matrix.svg").write_text(svg(show_matrix=True), encoding="utf-8")
    (out / "kle.json").write_text(json.dumps(kle(), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "kle-via.json").write_text(json.dumps(kle(via=True), indent=1), encoding="utf-8")
    stab = [k for k in KEYS if k.stabilized]
    print("%d keys, matrix %dx%d, %d stabilizers: %s" % (len(SWITCHES), ROWS, COLS, len(stab),
                                                          ", ".join("%s %gu" % (k.label, max(k.w, k.h)) for k in stab)))
    print("key area %.2f x %.2f mm" % (WIDTH * U, HEIGHT * U))
