"""Copper path between two pads on the routed PCB: the shortest way along one net's tracks and vias, its length (mm)
and the number of vias on it. pcb/verify_netlist.py measures the pairs listed in circuit.LAYOUT_PAIRS with it and
writes them into build/netlist.json, where pcb/check_circuit.py (G01) judges them.

A net is a graph: track ends are nodes, tracks are edges of their length; a track end on another track's middle, inside
a via or inside a pad joins them. Lengths run from where the tracks meet the pads (usually the pads' centres), so they
include up to half a pad at each end.
"""
import heapq
import math

import pcbnew


def mm(v):
    return pcbnew.ToMM(v)


def _pt(v):
    return round(mm(v.x), 4), round(mm(v.y), 4)


def _seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


class NetGraph:
    def __init__(self, board, net):
        self.adj = {}
        tracks = [t for t in board.GetTracks() if t.GetNetname() == net]
        segs = [t for t in tracks if t.GetClass() == "PCB_TRACK"]
        vias = [t for t in tracks if t.GetClass() == "PCB_VIA"]
        for s in segs:
            a, b = _pt(s.GetStart()), _pt(s.GetEnd())
            self._edge(("pt", s.GetLayer()) + a, ("pt", s.GetLayer()) + b, math.dist(a, b))
        ends = [n for n in self.adj if n[0] == "pt"]
        for n in ends:  # a track end on the middle of another track of the same layer
            p = n[2:]
            for s in segs:
                a, b = _pt(s.GetStart()), _pt(s.GetEnd())
                if s.GetLayer() == n[1] and p not in (a, b) and _seg_dist(p, a, b) < mm(s.GetWidth()) / 2:
                    self._edge(n, ("pt", s.GetLayer()) + a, math.dist(p, a))
                    self._edge(n, ("pt", s.GetLayer()) + b, math.dist(p, b))
        for v in vias:
            c = _pt(v.GetPosition())
            node = ("via",) + c
            self.adj.setdefault(node, [])
            for n in ends:
                if math.dist(n[2:], c) <= mm(v.GetWidth(pcbnew.F_Cu)) / 2 + 1e-3:
                    self._edge(node, n, math.dist(n[2:], c))
            for s in segs:  # a via dropped on the middle of a track
                a, b = _pt(s.GetStart()), _pt(s.GetEnd())
                if _seg_dist(c, a, b) < mm(s.GetWidth()) / 2:
                    self._edge(node, ("pt", s.GetLayer()) + a, math.dist(c, a))
                    self._edge(node, ("pt", s.GetLayer()) + b, math.dist(c, b))
        for f in board.GetFootprints():
            for p in f.Pads():
                if p.GetNetname() != net:
                    continue
                node = ("pad", f.GetReference(), p.GetNumber())
                self.adj.setdefault(node, [])
                for n in list(self.adj):
                    if n[0] == "pt" and p.IsOnLayer(n[1]) and p.HitTest(pcbnew.VECTOR2I(pcbnew.FromMM(n[2]),
                                                                                         pcbnew.FromMM(n[3]))):
                        self._edge(node, n, 0.0)
                    elif n[0] == "via" and p.HitTest(pcbnew.VECTOR2I(pcbnew.FromMM(n[1]), pcbnew.FromMM(n[2]))):
                        self._edge(node, n, 0.0)

    def _edge(self, a, b, w):
        self.adj.setdefault(a, []).append((b, w))
        self.adj.setdefault(b, []).append((a, w))

    def path(self, src, dst):
        """(length mm, vias on the way) of the shortest copper path, or None if the two are not joined by tracks."""
        best, hops = {src: 0.0}, {src: 0}
        heap = [(0.0, src)]
        while heap:
            d, n = heapq.heappop(heap)
            if n == dst:
                return round(d, 2), hops[n]
            if d > best[n]:
                continue
            for m, w in self.adj.get(n, ()):
                if d + w < best.get(m, 1e9):
                    best[m] = d + w
                    hops[m] = hops[n] + (m[0] == "via")
                    heapq.heappush(heap, (d + w, m))
        return None


def measure(board, pairs):
    """pairs: (kind, net, (ref, pad), (ref, pad)) -> one dict per pair with the copper length and vias."""
    graphs, out = {}, []
    for kind, net, a, b in pairs:
        g = graphs.setdefault(net, NetGraph(board, net))
        r = g.path(("pad",) + tuple(map(str, a)), ("pad",) + tuple(map(str, b)))
        out.append({"kind": kind, "net": net, "from": "%s.%s" % a, "to": "%s.%s" % b,
                    "mm": r[0] if r else None, "vias": r[1] if r else None})
    return out
