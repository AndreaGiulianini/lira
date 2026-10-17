"""Completes the routing where Freerouting leaves it unfinished, so the board needs no hand work.

    (pcb/finish_pcb.py calls repair() on the routed board, before the ground pours)

Freerouting 2.4.1 is deterministic and now and then gives up on a connection in a crowded spot, or lays tracks of two
nets over each other (a fault of its optimiser). Running it again gives the same result, and it cannot carry on from a
routed board: tracks handed to it as fixed do not count as connections, so it starts over and fails. Instead:
  1. the segments KiCad's DRC reports as crossing, shorting or too close are deleted (never ground, never what
     pcb/electronics.py drew itself), then whatever they leave hanging: track ends touching nothing (but a piece
     still on a pad stays, as a way out of fine-pitch pins), vias joined on one layer only;
  2. every net still in more than one piece, except GND (the pours join it), is joined by a small router: A* on a
     0.1 mm grid over both layers with vias, at the net class's width, 0.2 mm from other nets (Freerouting keeps
     0.18 mm, the DRC minimum is 0.15 mm), 0.35 mm from the board edge, outside the keep-out areas, never on the
     bottom layer of the USB high-speed corridor and only across (not along) the pair on the top layer. The path is
     then straightened, into 0 / 45 / 90 degree pieces where they fit, each piece checked exactly against the
     copper around it; what is left hanging afterwards is removed.
The DRC that follows checks the result like the rest of the board; a net that cannot be joined stops the build.
"""
import heapq
import json
import math
import subprocess
from pathlib import Path

import pcbnew

from gen_pcb import POWER_NETS

GRID = 0.1  # mm
EDGE = 0.35  # mm to the board edge
HOLE = 0.25  # mm from copper to a hole, and between holes
MARGIN = 0.03  # mm more on the grid, so that a step between two free cells is clear as well
VIA_COST = 2.0  # mm of track one via is worth
PAIR_COST = 0.5  # mm added per 0.1 mm step on the top layer over the USB high-speed pair: crossing it is fine,
#                  running along it is not (it is the pair's ground reference)
PAIR = ("USB_DP", "USB_DN")
WINDOWS = (3, 8, 20)  # mm around the two pieces to join: the router looks this far, widening if it finds no path
# power net? -> attempts of (track width, clearance) at the net class's vias (diameter, drill, as gen_pcb.py): the
# class width first, then a neck-down at the DRC limits, which reaches into 0.5 mm-pitch pins (as Freerouting does)
SIZES = {True: ([(0.4, 0.2), (0.3, 0.15)], 0.7, 0.35), False: ([(0.3, 0.2), (0.2, 0.15)], 0.6, 0.3)}
CORRIDOR = "usb-hs-corridor"
TRACK_ERRORS = ("tracks_crossing", "shorting_items", "clearance")
LAYERS = (pcbnew.F_Cu, pcbnew.B_Cu)
KCLI = next(p for p in Path(pcbnew.__file__).resolve().parents if p.name == "Contents") / "MacOS" / "kicad-cli"


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    return pcbnew.VECTOR2I(int(round(x)), int(round(y)))


def drc(board_file):
    """KiCad's DRC report (errors only) of a saved board, as a dict."""
    out = Path(board_file).with_suffix(".drc.json")
    subprocess.run([str(KCLI), "pcb", "drc", "--format", "json", "--severity-error", "--all-track-errors", "-o",
                    str(out), str(board_file)], check=True, capture_output=True)
    d = json.loads(out.read_text())
    out.unlink()
    return d


def seg_dist(px, py, ax, ay, bx, by):
    """Distance from point p to segment ab."""
    dx, dy = bx - ax, by - ay
    l2 = dx * dx + dy * dy
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def segs_dist(a, b, c, d):
    """Distance between segments ab and cd (0 where they cross)."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if side(c, d, a) * side(c, d, b) < 0 and side(a, b, c) * side(a, b, d) < 0:
        return 0.0
    return min(seg_dist(*a, *c, *d), seg_dist(*b, *c, *d), seg_dist(*c, *a, *b), seg_dist(*d, *a, *b))


class Obstacle:
    """Something a new track's centre line must stay rt away from (on the given layers) and a new via's centre rv
    (None: no limit). kind "seg": (ax, ay, bx, by, half width); "circle": (x, y, radius); "shape": a KiCad shape."""

    def __init__(self, kind, data, layers, rt, rv, box):
        self.kind, self.data, self.layers, self.rt, self.rv, self.box = kind, data, layers, rt, rv, box

    def near_point(self, x, y, r):
        if self.kind == "seg":
            ax, ay, bx, by, h = self.data
            return seg_dist(x, y, ax, ay, bx, by) - h < r
        if self.kind == "circle":
            cx, cy, rad = self.data
            return math.hypot(x - cx, y - cy) - rad < r
        return self.data.Collide(vec(x, y), int(r))

    def near_seg(self, a, b, r):
        if self.kind == "seg":
            ax, ay, bx, by, h = self.data
            return segs_dist(a, b, (ax, ay), (bx, by)) - h < r
        if self.kind == "circle":
            cx, cy, rad = self.data
            return seg_dist(cx, cy, *a, *b) - rad < r
        return self.data.Collide(pcbnew.SEG(vec(*a), vec(*b)), int(r))


def box_of(item):
    bb = item.GetBoundingBox()
    return bb.GetLeft(), bb.GetTop(), bb.GetRight(), bb.GetBottom()


def obstacles(b, net, w, via_d, drill, clear):
    """Everything a new track (width w) or via of this net must keep clear of (clear: to other nets)."""
    rt, rv = w / 2 + clear, via_d / 2 + clear
    out = []
    for t in b.GetTracks():
        if t.GetNetCode() == net:
            continue
        if t.GetClass() == "PCB_VIA":
            p, r = t.GetPosition(), t.GetWidth(pcbnew.F_Cu) / 2
            out.append(Obstacle("circle", (p.x, p.y, r), LAYERS, rt, rv, (p.x - r, p.y - r, p.x + r, p.y + r)))
        else:
            s, e, h = t.GetStart(), t.GetEnd(), t.GetWidth() / 2
            out.append(Obstacle("seg", (s.x, s.y, e.x, e.y, h), (t.GetLayer(),), rt, rv,
                                (min(s.x, e.x) - h, min(s.y, e.y) - h, max(s.x, e.x) + h, max(s.y, e.y) + h)))
    for p in b.GetPads():
        own = p.GetNetCode() == net
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH:
            for layer in LAYERS:
                if p.IsOnLayer(layer):
                    if not own:
                        out.append(Obstacle("shape", p.GetEffectiveShape(layer), (layer,), rt, rv, box_of(p)))
                    elif not p.HasHole():  # no via in a pad of its own net either
                        out.append(Obstacle("shape", p.GetEffectiveShape(layer), (layer,), None, via_d / 2 + mm(0.05),
                                            box_of(p)))
        if p.HasHole():
            hole = p.GetEffectiveHoleShape()
            if own:  # a track may cross its own pad; a via must keep off the hole
                out.append(Obstacle("shape", hole, LAYERS, None, drill / 2 + mm(HOLE), box_of(p)))
            else:
                out.append(Obstacle("shape", hole, LAYERS, w / 2 + mm(HOLE), via_d / 2 + mm(HOLE), box_of(p)))
    for d in b.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            out.append(Obstacle("shape", d.GetEffectiveShape(), LAYERS, w / 2 + mm(EDGE), via_d / 2 + mm(EDGE),
                                box_of(d)))
    zones = list(b.Zones()) + [z for fp in b.GetFootprints() for z in fp.Zones()]
    for z in zones:
        if not z.GetIsRuleArea():
            continue
        if z.GetZoneName() == CORRIDOR:  # the high-speed pair's ground reference: keep the bottom layer whole
            out.append(Obstacle("shape", z.Outline(), (pcbnew.B_Cu,), rt, rv, box_of(z)))  # (rt, rv: other nets)
            continue
        no_tracks, no_vias = z.GetDoNotAllowTracks(), z.GetDoNotAllowVias()
        if no_tracks or no_vias:
            layers = tuple(layer for layer in LAYERS if z.IsOnLayer(layer))
            out.append(Obstacle("shape", z.Outline(), layers, w / 2 + 1 if no_tracks else None,
                                via_d / 2 + 1 if no_vias else None, box_of(z)))
    return out


def pieces(b, net):
    """The separate pieces (lists of pads, tracks and vias) a net is in."""
    c = b.GetConnectivity()
    items = [t for t in b.GetTracks() if t.GetNetCode() == net] + [p for p in b.GetPads() if p.GetNetCode() == net]
    seen, out = set(), []
    for it in items:
        if it.m_Uuid.AsString() in seen:
            continue
        group = [it] + [g.Cast() for g in c.GetConnectedItems(it) if g.GetNetCode() == net]  # (as PAD, PCB_VIA...)
        group = list({g.m_Uuid.AsString(): g for g in group}.values())
        seen.update(g.m_Uuid.AsString() for g in group)
        out.append(group)
    return out


def anchors(piece):
    pts = []
    for it in piece:
        if it.GetClass() == "PCB_TRACK":
            pts += [(it.GetStart().x, it.GetStart().y), (it.GetEnd().x, it.GetEnd().y)]
        else:
            pts.append((it.GetPosition().x, it.GetPosition().y))
    return pts


def contains(it, layer, x, y):
    """Whether point (x, y) on this layer is inside the copper of a pad, via or track."""
    if not it.IsOnLayer(layer):
        return False
    if it.GetClass() == "PAD":
        return it.GetEffectiveShape(layer).Collide(vec(x, y), 0)
    if it.GetClass() == "PCB_VIA":
        p = it.GetPosition()
        return math.hypot(x - p.x, y - p.y) <= it.GetWidth(pcbnew.F_Cu) / 2 - mm(0.05)
    s, e = it.GetStart(), it.GetEnd()
    return seg_dist(x, y, s.x, s.y, e.x, e.y) <= it.GetWidth() / 2 - mm(0.02)


class Grid:
    """Cells GRID apart over a window: where a new track centre (per layer) or via may go, and which cells lie in the
    copper of the piece to join (1) or of the others (2)."""

    def __init__(self, window, obs, source, targets, pair=()):
        self.g = g = mm(GRID)
        self.x0, self.y0, x1, y1 = window
        self.nx, self.ny = int((x1 - self.x0) // g) + 1, int((y1 - self.y0) // g) + 1
        n = self.n = self.nx * self.ny
        self.free = [bytearray(b"\x01") * n for _ in LAYERS]
        self.via = bytearray(b"\x01") * n
        m = mm(MARGIN)
        for o in obs:
            r = max(o.rt or 0, o.rv or 0) + m
            lis = [i for i, layer in enumerate(LAYERS) if layer in o.layers]
            for ix, iy, x, y in self.cells(o.box, r):
                i = iy * self.nx + ix
                if not o.near_point(x, y, r):
                    continue
                if o.rv is not None and self.via[i] and o.near_point(x, y, o.rv + m):
                    self.via[i] = 0
                if o.rt is not None:
                    for li in lis:
                        if self.free[li][i] and o.near_point(x, y, o.rt + m):
                            self.free[li][i] = 0
        self.over_pair = bytearray(n)  # top-layer cells over the USB pair
        for ax, ay, bx, by, h in pair:
            r = h + mm(0.3)
            for ix, iy, x, y in self.cells((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)), r):
                if seg_dist(x, y, ax, ay, bx, by) < r:
                    self.over_pair[iy * self.nx + ix] = 1
        self.mark = bytearray(2 * n)
        for value, piece in ((1, source), (2, [it for p in targets for it in p])):
            for it in piece:
                for li, layer in enumerate(LAYERS):
                    if not it.IsOnLayer(layer):
                        continue
                    for ix, iy, x, y in self.cells(box_of(it), 0):
                        i = iy * self.nx + ix
                        if self.free[li][i] and not self.mark[li * n + i] and contains(it, layer, x, y):
                            self.mark[li * n + i] = value

    def cells(self, box, r):
        g = self.g
        ix0, iy0 = max(0, int((box[0] - r - self.x0) // g)), max(0, int((box[1] - r - self.y0) // g))
        ix1, iy1 = min(self.nx - 1, int((box[2] + r - self.x0) // g) + 1), min(self.ny - 1,
                                                                                int((box[3] + r - self.y0) // g) + 1)
        for iy in range(iy0, iy1 + 1):
            y = self.y0 + iy * g
            for ix in range(ix0, ix1 + 1):
                yield ix, iy, self.x0 + ix * g, y

    def xy(self, s):
        i = s % self.n
        return self.x0 + (i % self.nx) * self.g, self.y0 + (i // self.nx) * self.g

    def search(self):
        """A* from the cells of the piece to join to any cell of the others: the cells and layers of the path."""
        n, nx, ny = self.n, self.nx, self.ny
        goal = [s for s in range(2 * n) if self.mark[s] == 2]
        start = [s for s in range(2 * n) if self.mark[s] == 1]
        if not goal or not start:
            return None
        gx = [(s % n) % nx for s in goal]
        gy = [(s % n) // nx for s in goal]
        tx0, tx1, ty0, ty1 = min(gx), max(gx), min(gy), max(gy)

        def h(i):
            ix, iy = i % nx, i // nx
            return math.hypot(max(tx0 - ix, 0, ix - tx1), max(ty0 - iy, 0, iy - ty1))

        via_cost = VIA_COST / GRID
        pair_cost = PAIR_COST / GRID
        top = LAYERS.index(pcbnew.F_Cu)
        moves = [(dx, dy, math.hypot(dx, dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy]
        dist = [math.inf] * (2 * n)
        prev = [-1] * (2 * n)
        heap = []
        for s in start:
            dist[s] = 0.0
            heap.append((h(s % n), 0.0, s))
        heapq.heapify(heap)
        while heap:
            _, d, s = heapq.heappop(heap)
            if d > dist[s]:
                continue
            if self.mark[s] == 2:
                path = [s]
                while prev[path[-1]] >= 0:
                    path.append(prev[path[-1]])
                return path[::-1]
            li, i = divmod(s, n)
            ix, iy = i % nx, i // nx
            free = self.free[li]
            for dx, dy, cost in moves:
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < nx and 0 <= jy < ny):
                    continue
                j = jy * nx + jx
                if not free[j] or (dx and dy and not (free[iy * nx + jx] and free[jy * nx + ix])):
                    continue
                t, nd = li * n + j, d + cost + (pair_cost if li == top and self.over_pair[j] else 0.0)
                if nd < dist[t]:
                    dist[t], prev[t] = nd, s
                    heapq.heappush(heap, (nd + h(j), nd, t))
            if self.via[i] and self.free[1 - li][i]:
                t, nd = (1 - li) * n + i, d + via_cost
                if nd < dist[t]:
                    dist[t], prev[t] = nd, s
                    heapq.heappush(heap, (nd + h(i), nd, t))
        return None


def clear_seg(obs, layer, a, b):
    lo_x, hi_x, lo_y, hi_y = min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1])
    for o in obs:
        if o.rt is None or layer not in o.layers:
            continue
        x0, y0, x1, y1 = o.box
        if x1 + o.rt < lo_x or x0 - o.rt > hi_x or y1 + o.rt < lo_y or y0 - o.rt > hi_y:
            continue
        if o.near_seg(a, b, o.rt):
            return False
    return True


def straighten(obs, layer, pts):
    """Fewest straight pieces through the path's cells, each checked against the obstacles."""
    corners = [pts[0]]
    for k in range(1, len(pts) - 1):
        d1 = (pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
        d2 = (pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
        if d1 != d2:
            corners.append(pts[k])
    if len(pts) > 1:
        corners.append(pts[-1])
    out, i = [corners[0]], 0
    while i < len(corners) - 1:
        j = next((j for j in range(len(corners) - 1, i + 1, -1) if clear_seg(obs, layer, corners[i], corners[j])),
                 i + 1)
        out.append(corners[j])
        i = j
    return out


def octilinear(obs, layer, pts):
    """Like Freerouting, only 0 / 45 / 90 degree pieces: a slanting piece becomes a 45 degree one and a straight one
    (whichever order keeps clear), or stays as it is if neither does."""
    out = [pts[0]]
    for b in pts[1:]:
        a = out[-1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        m = min(abs(dx), abs(dy))
        if m < 1 or abs(abs(dx) - abs(dy)) < 1:
            out.append(b)
            continue
        diag = (math.copysign(m, dx), math.copysign(m, dy))
        for k in ((a[0] + diag[0], a[1] + diag[1]), (b[0] - diag[0], b[1] - diag[1])):
            if clear_seg(obs, layer, a, k) and clear_seg(obs, layer, k, b):
                out.append(k)
                break
        out.append(b)
    return out


def snap(obs, piece, layer, end, nxt):
    """Move a path end that lies inside a pad, via or track of the piece to its centre (or onto the track's centre
    line) when the piece of track to the next corner stays clear. Returns the point and the track to split, if any."""
    for it in sorted(piece, key=lambda it: it.GetClass() != "PAD"):
        if not contains(it, layer, *end):
            continue
        if it.GetClass() == "PCB_TRACK":
            s, e = it.GetStart(), it.GetEnd()
            dx, dy = e.x - s.x, e.y - s.y
            l2 = dx * dx + dy * dy or 1
            t = max(0.0, min(1.0, ((end[0] - s.x) * dx + (end[1] - s.y) * dy) / l2))
            p = (s.x + t * dx, s.y + t * dy)
        else:
            p = (it.GetPosition().x, it.GetPosition().y)
        if clear_seg(obs, layer, p, nxt):
            return p, it if it.GetClass() == "PCB_TRACK" else None
        return end, None
    return end, None


def split(b, track, p):
    """Cut a track in two at point p (on it), so a new track can end there on a track end."""
    s, e = track.GetStart(), track.GetEnd()
    if min(math.hypot(p[0] - s.x, p[1] - s.y), math.hypot(p[0] - e.x, p[1] - e.y)) < mm(0.001):
        return
    other = pcbnew.PCB_TRACK(b)
    other.SetStart(vec(*p))
    other.SetEnd(e)
    other.SetWidth(track.GetWidth())
    other.SetLayer(track.GetLayer())
    other.SetNetCode(track.GetNetCode())
    other.SetLocked(track.IsLocked())
    b.Add(other)
    track.SetEnd(vec(*p))


def join(b, net, name):
    """Join the piece of the net nearest to another piece to it. Returns (mm of track, vias) or None."""
    attempts, via_d, drill = SIZES[name in POWER_NETS]
    via_d, drill = mm(via_d), mm(drill)
    parts = pieces(b, net)
    best = None
    for i, p in enumerate(parts):
        for j, q in enumerate(parts):
            if i < j:
                d, a, c = min((math.hypot(a[0] - c[0], a[1] - c[1]), a, c) for a in anchors(p) for c in anchors(q))
                if best is None or d < best[0]:
                    best = (d, i, j, a, c)
    _, i, j, a, c = best
    if len(parts[i]) > len(parts[j]):
        i, j = j, i
    source, targets = parts[i], [p for k, p in enumerate(parts) if k != i]
    pair = [] if name in PAIR else [(t.GetStart().x, t.GetStart().y, t.GetEnd().x, t.GetEnd().y, t.GetWidth() / 2)
                                    for t in b.GetTracks() if t.GetNetname() in PAIR and t.GetClass() == "PCB_TRACK"]
    board = b.GetBoardEdgesBoundingBox()
    path = None
    for w, clear in attempts:
        w = mm(w)
        obs = obstacles(b, net, w, via_d, drill, mm(clear))
        for margin in WINDOWS:
            m = mm(margin)
            window = (max(min(a[0], c[0]) - m, board.GetLeft()), max(min(a[1], c[1]) - m, board.GetTop()),
                      min(max(a[0], c[0]) + m, board.GetRight()), min(max(a[1], c[1]) + m, board.GetBottom()))
            grid = Grid(window, obs, source, targets, pair)
            path = grid.search()
            if path:
                break
        if path:
            break
    if not path:
        return None
    runs = [[path[0]]]  # pieces of the path on one layer
    for s in path[1:]:
        if s // grid.n != runs[-1][-1] // grid.n:
            runs.append([])
        runs[-1].append(s)
    length, vias = 0.0, []
    first_piece, last_pieces = source, [it for p in targets for it in p]
    for k, run in enumerate(runs):
        layer = LAYERS[run[0] // grid.n]
        pts = straighten(obs, layer, [grid.xy(s) for s in run])
        if k == 0 and len(pts) > 1:  # (a one-point run is where the path changes layer: the via stays there)
            pts[0], cut = snap(obs, first_piece, layer, pts[0], pts[1])
            if cut is not None:
                split(b, cut, pts[0])
        if k == len(runs) - 1 and len(pts) > 1:
            pts[-1], cut = snap(obs, last_pieces, layer, pts[-1], pts[-2])
            if cut is not None:
                split(b, cut, pts[-1])
        pts = octilinear(obs, layer, pts)
        for p, q in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(vec(*p))
            t.SetEnd(vec(*q))
            t.SetWidth(int(w))
            t.SetLayer(layer)
            t.SetNetCode(net)
            b.Add(t)
            length += pcbnew.ToMM(t.GetLength())
        if k < len(runs) - 1:
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(vec(*pts[-1]))
            v.SetWidth(int(via_d))
            v.SetDrill(int(drill))
            v.SetNetCode(net)
            b.Add(v)
            vias.append(pts[-1])
    b.BuildConnectivity()
    return length, len(vias)


def remove(b, items):
    """Take items off the board. pcbnew then hands them over to Python, which would free them while KiCad's
    connectivity data still points at them (later calls return garbage), so they are kept alive instead."""
    for t in items:
        b.Remove(t)
        t.thisown = False


def key(t):
    """What identifies a track or via across boards (their UUIDs change on every session import): kind, net and
    layer, and its points."""
    if t.GetClass() == "PCB_VIA":
        return ("via", t.GetNetname(), None), [(t.GetPosition().x, t.GetPosition().y)]
    return ("track", t.GetNetname(), t.GetLayer()), [(t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)]


class Keep:
    """The generator's own tracks and vias. The session import moves unlocked ones by up to half a micrometre, so
    they are recognised within 1 um (either way round, for a track)."""

    def __init__(self, items):
        self.by_kind = {}
        for t in items:
            kind, pts = key(t)
            self.by_kind.setdefault(kind, []).append(pts)

    def __contains__(self, t):
        kind, pts = key(t)
        for other in self.by_kind.get(kind, ()):
            for order in (other, other[::-1]):
                if all(abs(a[0] - b[0]) <= 1000 and abs(a[1] - b[1]) <= 1000 for a, b in zip(pts, order)):
                    return True
        return False


def via_layers(c, v):
    """The copper layers on which a via is joined to something."""
    layers = {t.GetLayer() for t in c.GetConnectedTracks(v)}
    for p in c.GetConnectedPads(v):
        layers |= {layer for layer in LAYERS if p.IsOnLayer(layer)}
    return layers


def prune(b, keep, pad_stubs=True):
    """Delete track ends that touch nothing and vias joined on one layer only, until there are none, except ground,
    locked items and those in keep (the generator's own tracks and vias). pad_stubs: also keep a hanging piece that
    still sits on a pad (the router can start from its free end, outside a fine-pitch pin row). Returns how many,
    and the nets they were on."""
    removed, nets = 0, set()
    while True:
        b.BuildConnectivity()
        c = b.GetConnectivity()
        gone = []
        for t in b.GetTracks():
            if t.IsLocked() or t.GetNetname() == "GND" or t in keep:
                continue
            if t.GetClass() == "PCB_VIA":
                if len(via_layers(c, t)) < 2:
                    gone.append(t)
            elif c.TestTrackEndpointDangling(t, False) and not (pad_stubs and len(c.GetConnectedPads(t))):
                gone.append(t)
        if not gone:
            return removed, nets
        nets |= {t.GetNetCode() for t in gone}
        remove(b, gone)
        removed += len(gone)


def repair(routed, placed):
    """Repair the routed board file in place (placed: the board before routing, with the generator's own tracks).
    Returns what was done, line by line (nothing if all was fine), and the nets it could not join."""
    d = drc(routed)
    bad = {i["uuid"] for v in d.get("violations", []) if v["type"] in TRACK_ERRORS for i in v["items"]}
    opened = {i["description"].split("[")[1].split("]")[0] for v in d.get("unconnected_items", []) for i in v["items"]
              if "[" in i["description"]} - {"GND"}
    if not bad and not opened:
        return [], []
    keep = Keep(pcbnew.LoadBoard(str(placed)).GetTracks())
    b = pcbnew.LoadBoard(str(routed))
    gone = [t for t in b.GetTracks() if t.m_Uuid.AsString() in bad and not t.IsLocked() and t not in keep
            and t.GetNetname() != "GND"]
    nets = {b.FindNet(n).GetNetCode() for n in opened} | {t.GetNetCode() for t in gone}
    remove(b, gone)
    stubs, pruned = prune(b, keep)
    nets |= pruned
    log = ["deleted %d crossing or too close segment(s) and %d hanging piece(s)" % (len(gone), stubs)] if gone or stubs else []
    failed = []
    for net in sorted(nets):
        name = b.GetNetInfo().GetNetItem(net).GetNetname()
        if name == "GND":
            continue
        joined = []
        while len(pieces(b, net)) > 1:
            done = join(b, net, name)
            if done is None:
                failed.append(name)
                break
            joined.append(done)
        if joined:
            log.append("joined %s: %d link(s), %.1f mm, %d via(s)" % (
                name, len(joined), sum(j[0] for j in joined), sum(j[1] for j in joined)))
    left, _ = prune(b, keep, pad_stubs=False)  # stubs the joins did not use
    if left:
        log.append("removed %d piece(s) left hanging after the joins" % left)
    pcbnew.SaveBoard(str(routed), b)
    if failed:
        log.append("COULD NOT JOIN: " + ", ".join(failed))
    return log, failed
