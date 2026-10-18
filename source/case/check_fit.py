"""Test fit of the case: everything that goes inside, modelled from the final PCB and from the datasheets, against
the printed pieces as exported. Writes build/case/check-fit.txt; exit status 1 on any FAIL.

    .venv/bin/python case/check_fit.py     (after pcb/export_parts.py and case/gen_case.py; `make case` runs all three)

The pieces are read back from the exported STEP (collisions) and STL (rays) files and probed, so the test does not
rely on what gen_case.py meant to build: gen_case.py is imported only for the slab <-> world transform and the stack
heights (deck, plate, PCB), which are the design inputs. Part positions come from the PCB (build/pcb/parts.json).

  C  collisions: each inside part (enlarged by a clearance) vs each printed piece, boolean intersection
  A  assembly: the volume swept by the PCB (with all its parts) and by the plate while they are lowered into the
     bottom body, and by the top frame while it is lowered over the keycaps, must be free
  P  ports: USB-C and headset plug overmolds, the status LED seen from behind, paperclip path to the BOOT
     button
  S  screws: head seat, tip vs end of the hole, thread engaged in the insert, plastic around the inserts; top mount:
     the plate lies on the top frame, the bolt bosses clamp its back tabs, the backstops under the PCB
  W  walls: local thickness of every piece (rays from the surface along the inward normal)
  O  printing: overhangs and bridges in the print orientation, bed size
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from build123d import Align, Cylinder, Polyline, Pos, RectangleRounded, extrude, import_step, make_face, offset
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import gen_case as G  # noqa: E402
import layout as L  # noqa: E402
import mount  # noqa: E402
from paths import BUILD  # noqa: E402

PARTS = json.loads((BUILD / "pcb/parts.json").read_text())

# ------------------------------------------------------------------ datasheet dimensions (mm) and test margins
# height of each bottom-side part below the PCB, by footprint name
HEIGHT_BELOW = [
    ("SW_Hotswap_Kailh", 1.95),  # CPG151101S11-type socket (C41430893; Kailh C2803348 discontinued): 1.85 +- 0.1
    ("QFN-56", 0.9),  # RP2040 QFN-56 7 x 7: 0.9 max (datasheet)
    ("SOIC-8_5.3x5.3", 2.16),  # W25Q128JVSIQ SOIC-8 208 mil: 2.16 max (Winbond package outline)
    ("USB_C_Receptacle_HRO", 3.26),  # HRO TYPE-C-31-M-12 (C165948): 3.26
    ("SW-SMD_4P-L5.1-W5.1", 1.5),  # TS-1187A (C318884): 5.1 x 5.1 x 1.5
    ("SOT-23", 1.45), ("SOD-123", 1.35), ("_0603_", 1.0),
    # sound card
    ("PJ-320D-4A", 5.0),  # Hroparts PJ-320D-4A (C95562): body 5.0 high (nose 5.0 diameter)
    ("LQFP-48", 1.6),  # CM108B LQFP-48 7 x 7: 1.6 max
    ("WCH_QFN-16", 0.85),  # CH334P QFN-16 3 x 3: 0.85 max
    ("Crystal_SMD_3225", 1.0),  # 12 MHz 3225 crystal: 0.8-1.0
    ("WQFN-16", 0.8),  # TPA6132A2 RTE: 0.8 max
    ("SOT-363", 1.1),  # TPS22919 SC-70-6 (DCK): 1.1 max
]
PIN_BELOW = 1.9  # MX switch pins and posts: 3.3 below the housing = 1.7 below a 1.6 mm PCB (+0.2)
STAB_HEAD = (5.5, 2.0)  # screw-in stabilizer: screw head + washer under the PCB, diameter x height
PLATE_T = 1.6  # FR4 plate (1.5 mm aluminium is thinner: the FR4 plate is the worst case)
KEYCAP_REST, TRAVEL = 6.5, 4.0  # keycap skirt above the plate top at rest (low profile: worst case), MX travel
KEYCAP_GAP = 0.95  # keycap = key unit - 0.95
USB_PLUG = (13.0, 7.5, 30.0)  # USB-C overmold width x height x length (common 12.4 x 6.5, bulky cables 13 x 7.5)
JACK_PLUG = (9.0, 30.0)  # 3.5 mm plug overmold, round: diameter (straight plugs 5-8 mm, bulky ones 9) x length
JACK_AXIS = 2.5  # PJ-320D-4A plug axis below the PCB (5 mm body)
USB_AXIS = 3.26 / 2  # receptacle axis below the PCB
M2 = dict(head=mount.SCREW["head"], length=mount.SCREW["length"])  # plate screws (top mount)
M2_INSERT = 3.0  # M2 heat-set insert length
M3_INSERT = 3.0  # short M3 heat-set insert length
SCREWS = dict(case=12.0, bolt=20.0)  # M3 lengths
CLEAR = 0.3  # clearance required between an inside part and the case
MIN_WALL = 1.2  # thinnest wall: 2 perimeters of a 0.4 mm nozzle + margin (below MIN_WALL_FAIL it does not print)
MIN_WALL_FAIL = 0.8
MIN_INSERT_WALL = 1.5  # plastic around a heat-set insert hole
OVERHANG = 45.0  # degrees from vertical
BRIDGE = 20.0  # longest unsupported span
BED = G.BED

results = []


def report(status, code, msg):
    results.append((status, code, msg))


# ------------------------------------------------------------------------------------------------- geometry
def slab_to_world(p):
    return np.array(tuple(G.w_pt(*p)))


def slab_dir(d):
    return np.array(tuple(G.w_dir(*d)))


def world_to_slab(P):
    t = math.radians(G.TILT)
    P = np.atleast_2d(P)
    Y, Z = P[:, 1] - G.TY, P[:, 2] - G.TZ
    return np.stack([P[:, 0], Y * math.cos(t) + Z * math.sin(t), -Y * math.sin(t) + Z * math.cos(t)], 1)


class Mesh:
    """Triangle mesh of a printed piece (binary STL) with vectorised ray casting."""

    def __init__(self, path):
        raw = np.fromfile(path, dtype=np.uint8)
        n = int.from_bytes(raw[80:84].tobytes(), "little")
        rec = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        tri = np.frombuffer(raw[84:84 + 50 * n].tobytes(), dtype=rec)["v"].astype(float)
        self.tri = tri
        self.v0, self.e1, self.e2 = tri[:, 0], tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        nrm = np.cross(self.e1, self.e2)
        self.area = np.linalg.norm(nrm, axis=1) / 2
        keep = self.area > 1e-9
        self.normal = np.zeros_like(nrm)
        self.normal[keep] = nrm[keep] / (2 * self.area[keep, None])

    def hits(self, o, d):
        """Sorted distinct distances along the ray o + t d (d unit) to the triangles."""
        o, d = np.asarray(o, float), np.asarray(d, float)
        p = np.cross(d, self.e2)
        det = (self.e1 * p).sum(1)
        ok = np.abs(det) > 1e-12
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = o - self.v0
        u = (s * p).sum(1) * inv
        q = np.cross(s, self.e1)
        v = (q @ d) * inv
        t = (q * self.e2).sum(1) * inv
        m = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-6)
        return np.unique(np.round(t[m], 4))

    def first_hits(self, O, D, tmax, chunk=256):
        """Nearest hit distance for many rays (inf if none closer than tmax) and the triangle hit (-1 if none)."""
        out = np.full(len(O), np.inf)
        tri = np.full(len(O), -1)
        e1, e2, v0 = self.e1[None], self.e2[None], self.v0[None]
        for a in range(0, len(O), chunk):
            o, d = O[a:a + chunk, None], D[a:a + chunk, None]
            p = np.cross(d, e2)
            det = (e1 * p).sum(2)
            ok = np.abs(det) > 1e-12
            inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
            s = o - v0
            u = (s * p).sum(2) * inv
            q = np.cross(s, e1)
            v = (q * d).sum(2) * inv
            t = (q * e2).sum(2) * inv
            m = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 1e-3) & (t < tmax)
            t = np.where(m, t, np.inf)
            out[a:a + chunk] = t.min(1)
            tri[a:a + chunk] = np.where(np.isfinite(t.min(1)), t.argmin(1), -1)
        return out, tri


class Pieces:
    def __init__(self):
        self.names = sorted(p.stem.replace("case-", "") for p in (BUILD / "case").glob("case-*.step"))
        self.step = {n: import_step(str(BUILD / "case" / ("case-%s.step" % n))) for n in self.names}
        self.mesh = {n: Mesh(BUILD / "case" / ("case-%s.stl" % n)) for n in self.names}
        self.bb = {n: s.bounding_box() for n, s in self.step.items()}

    def of(self, kind):
        return [n for n in self.names if n.startswith(kind)]

    def segments(self, o, d, kinds=("top", "bottom")):
        """Solid intervals [(t0, t1, piece)] along a ray that starts outside every piece."""
        out = []
        for n in self.names:
            if not n.startswith(kinds):
                continue
            t = self.mesh[n].hits(o, d)
            if len(t) % 2:
                t = t[:-1]  # grazing hit: drop the last one
            out += [(t[i], t[i + 1], n) for i in range(0, len(t), 2)]
        return sorted(out)

    def collide(self, solid, kinds=("top", "bottom")):
        """Volume of the solid inside each piece (only pieces whose bounding box it reaches)."""
        hits = {}
        sb = solid.bounding_box()
        for n in self.names:
            if not n.startswith(kinds):
                continue
            b = self.bb[n]
            if sb.max.X < b.min.X or sb.min.X > b.max.X or sb.max.Y < b.min.Y or sb.min.Y > b.max.Y \
                    or sb.max.Z < b.min.Z or sb.min.Z > b.max.Z:
                continue
            v = volume(self.step[n] & solid)
            if v > 1e-3:
                hits[n] = v
        return hits


def volume(shape):
    return shape.volume if shape is not None else 0.0


def ray(pieces, p, d, kinds=("top", "bottom")):
    """Segments along a slab-frame ray from slab point p, direction d."""
    d = np.asarray(d, float) / np.linalg.norm(d)
    return pieces.segments(slab_to_world(p), slab_dir(d), kinds)


# ----------------------------------------------------------------------------------------------- the inside
def box(x0, x1, y0, y1, z0, z1, m=0.0):
    """Slab-frame box; with a margin m its plan corners are rounded by m (the true offset of the box)."""
    if m <= 0:
        return G.slab_box(x0, x1, y0, y1, z0, z1)
    sk = RectangleRounded(x1 - x0 + 2 * m, y1 - y0 + 2 * m, m)
    return G.SLAB * Pos((x0 + x1) / 2, (y0 + y1) / 2, z0 - m) * extrude(sk, z1 - z0 + 2 * m)


def prism(pts, z0, z1, m=0.0):
    """Slab-frame prism over a plan polygon (e.g. the plate outline), grown by m all round."""
    pts = [tuple(p) for p in pts]  # JSON gives lists, which build123d would take as lists of points
    face = make_face(Polyline(*pts, close=True))
    area = 0.5 * abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])))
    assert abs(face.area - area) < 0.01 * area, "bad outline polygon: face %.1f mm2, polygon %.1f mm2" % (face.area, area)
    if m > 0:
        face = offset(face, m)
    return G.SLAB * Pos(0, 0, z0 - m) * extrude(face, z1 - z0 + 2 * m)


def cyl(x, y, z0, z1, d, m=0.0):
    return G.slab_cyl(x, y, z0 - m, z1 + m, d + 2 * m)


def ycyl(x, z, y0, y1, d):
    """Slab-frame cylinder along y (a round plug pointing out of the back), axis at (x, z)."""
    return G.SLAB * Pos(x, y0, z) * Cylinder(d / 2, y1 - y0, rotation=(-90, 0, 0),
                                             align=(Align.CENTER, Align.CENTER, Align.MIN))


def height_below(fp):
    for key, h in HEIGHT_BELOW:
        if key in fp:
            return h
    return 0.0


def inside_parts(up=0.0, down=0.0):
    """(name, solid, margin used, group) of everything that goes in the case except screws. Groups: pcb (the PCB
    and everything on it), plate, keycap. With up / down the pcb, plate and keycap solids are
    extended along the slab normal: the volume they sweep while being lowered into place (up) or while the top
    frame is lowered over them (down)."""
    def mbox(x0, x1, y0, y1, z0, z1, m=0.0):
        return box(x0, x1, y0, y1, z0 - down, z1 + up, m)

    def mcyl(x, y, z0, z1, d, m=0.0):
        return cyl(x, y, z0 - down, z1 + up, d, m)

    out = []
    bot, top = G.PCB_BOT, G.PCB_TOP
    b = PARTS["board"][0]["outer"]
    pcb = mbox(b[0], b[2], b[1], b[3], bot, top)
    holes = []
    for fp in PARTS["footprints"]:
        for p in fp["pads"]:
            if p["drill"] > 1.0 and fp["fp"].startswith("MountingHole"):
                holes.append(mcyl(p["xy"][0], p["xy"][1], bot - 1, top + 1, p["drill"]))
    for h in holes:
        pcb -= h
    out.append(("PCB", pcb, 0.0, "pcb"))
    for fp in PARTS["footprints"]:
        name, ref = fp["fp"], fp["ref"]
        if fp["side"] == "B":
            h = height_below(name)
            body = fp["fab"] or fp["courtyard"]
            if h and body:
                x0, y0, x1, y1 = body
                out.append((ref, mbox(x0, x1, y0, y1, bot - h, bot, CLEAR), CLEAR, "pcb"))
        elif "SW_Hotswap_Kailh" in name:
            # the socket is two lobes (solder tab + contact post each) joined between the posts
            pads = sorted((p for p in fp["pads"] if p["num"] in ("1", "2")), key=lambda p: p["xy"][0])
            posts = sorted((p for p in fp["pads"] if abs(p["drill"] - 3.05) < 0.1), key=lambda p: p["xy"][0])
            for group in ([pads[0], posts[0]], [pads[1], posts[1]], posts):
                xs = [q["bbox"][0] for q in group] + [q["bbox"][2] for q in group]
                ys = [q["bbox"][1] for q in group] + [q["bbox"][3] for q in group]
                out.append(("socket " + ref, mbox(min(xs), max(xs), min(ys), max(ys), bot - 1.95, bot, CLEAR), CLEAR, "pcb"))
            for p in fp["pads"]:
                if p["drill"] > 0:
                    out.append(("pin " + ref, mcyl(p["xy"][0], p["xy"][1], bot - PIN_BELOW, bot, p["drill"], CLEAR),
                                CLEAR, "pcb"))
        elif "Stabilizer" in name:
            for p in fp["pads"]:
                if p["drill"] > 0:
                    out.append(("stab screw " + ref, mcyl(p["xy"][0], p["xy"][1], bot - STAB_HEAD[1], bot,
                                                         STAB_HEAD[0], CLEAR), CLEAR, "pcb"))
    plate = PARTS.get("plate")
    if plate:
        solid = prism(plate[0]["outline"], G.PLATE_TOP - PLATE_T - down, G.PLATE_TOP + up)
        out.append(("plate", solid, 0.0, "plate"))
        d, h = M2["head"]  # heads of the M2 screws under the plate's ears
        for *_, (x, y) in mount.ears():
            out.append(("M2 head at %.1f,%.1f" % (x, y), mcyl(x, y, G.PLATE_TOP - PLATE_T - h, G.PLATE_TOP - PLATE_T, d,
                                                              CLEAR), CLEAR, "plate"))
    KD = L.HEIGHT * L.U
    for k in L.SWITCHES:
        x0, x1 = k.x * L.U + KEYCAP_GAP / 2, (k.x + k.w) * L.U - KEYCAP_GAP / 2
        y0, y1 = KD - (k.y + k.h) * L.U + KEYCAP_GAP / 2, KD - k.y * L.U - KEYCAP_GAP / 2
        for state, z in (("rest", KEYCAP_REST), ("pressed", KEYCAP_REST - TRAVEL)):
            out.append(("keycap %s (%s)" % (k.label, state),
                        mbox(x0, x1, y0, y1, G.PLATE_TOP + z, G.PLATE_TOP + z + 12.0, CLEAR), CLEAR, "keycap"))
    return out


def plate_with_openings():
    plate = PARTS.get("plate")
    if not plate:
        return None
    solid = prism(plate[0]["outline"], G.PLATE_TOP - PLATE_T, G.PLATE_TOP)
    for h in plate[0]["holes"]:
        solid -= box(h[0], h[2], h[1], h[3], G.PLATE_TOP - PLATE_T - 1, G.PLATE_TOP + 1)
    return solid


# ----------------------------------------------------------------------------------------------------- checks
def check_collisions(pieces):
    for name, solid, m, group in inside_parts():
        for piece, v in pieces.collide(solid).items():
            report("FAIL", "C", "%s (clearance %.2f) collides with %s: %.2f mm3" % (name, m, piece, v))
    if plate_with_openings() is None:
        report("FAIL", "C", "plate: no closed outline in build/plate/plate.kicad_pcb (empty plate)")
    # top mount: every M2 screw is reached from below with the PCB already on the switches (outside the PCB)
    b = PARTS["board"][0]["outer"]
    for *_, (x, y) in mount.ears():
        gap = max(b[0] - x, x - b[2], b[1] - y, y - b[3])
        if gap < 1.5:
            report("FAIL", "C", "M2 at %.1f,%.1f: only %.2f mm outside the PCB, no way to reach it from below" % (x, y, gap))


def check_assembly(pieces):
    """Top mount: the plate, the switches and the PCB with everything on it are one unit, screwed to the top frame;
    the bottom body comes on from below (here: the unit goes into it along the slab normal), and the top frame comes
    down over the keycaps onto the plate."""
    lift, bad = 40.0, 0
    for name, solid, m, group in inside_parts(up=lift):
        if group in ("pcb", "plate"):
            for piece, v in pieces.collide(solid, ("bottom",)).items():
                report("FAIL", "A", "%s cannot be lowered into place: its path hits %s (%.2f mm3)" % (name, piece, v))
                bad += 1
    for name, solid, m, group in inside_parts(down=lift):
        if group in ("pcb", "plate", "keycap"):
            for piece, v in pieces.collide(solid, ("top",)).items():
                report("FAIL", "A", "the top frame cannot be lowered over %s: hits it (%s, %.2f mm3)" % (name, piece, v))
                bad += 1
    if not bad:
        report("PASS", "A", "plate + PCB unit, bottom body and top frame all come together straight (%.1f mm clearance)"
               % CLEAR)


def back_face_y(pieces, x, z):
    """Slab y of the outer back face at slab (x, z), from a ray coming from behind."""
    seg = ray(pieces, (x, G.Y_B + 60, z), (0, -1, 0), ("bottom",))
    return G.Y_B + 60 - seg[0][0] if seg else None


def check_ports(pieces):
    fps = {fp["ref"]: fp for fp in PARTS["footprints"]}
    bot = G.PCB_BOT
    # USB-C: the overmold of a mated plug must not touch the case
    j1 = fps["J1"]
    x = (j1["fab"][0] + j1["fab"][2]) / 2
    mouth = j1["fab"][3]
    z = bot - USB_AXIS
    w, h, l = USB_PLUG
    v = pieces.collide(box(x - w / 2, x + w / 2, mouth, mouth + l, z - h / 2, z + h / 2))
    face = back_face_y(pieces, G.PORTS["window"]["x1"] + 3, z)  # just outside the port window
    if v:
        report("FAIL", "P", "USB-C overmold %gx%g mm hits %s" % (w, h, v))
    else:
        report("PASS", "P", "USB-C overmold %gx%g mm clears the window; receptacle mouth %.2f mm inside the back face"
               % (w, h, face - mouth))
    # headset jack: the overmold of a 3.5 mm plug pushed fully in
    if "J3" in fps:
        j3 = fps["J3"]
        x = (j3["fab"][0] + j3["fab"][2]) / 2
        mouth = j3["fab"][3]
        z = bot - JACK_AXIS
        d, l = JACK_PLUG
        v = pieces.collide(ycyl(x, z, mouth, mouth + l, d))
        face = back_face_y(pieces, x + G.JACK_W + 3, z)  # just outside the jack window
        if v:
            report("FAIL", "P", "headset plug overmold %g mm hits %s" % (d, v))
        else:
            report("PASS", "P", "headset plug overmold %g mm clears the window; jack mouth %.2f mm %s the back face"
                   % (d, abs(face - mouth), "inside" if face > mouth else "past"))
    # status LED: seen from behind, horizontally or from above at 30 / 45 degrees
    for ref in ("D103",):
        d = fps[ref]
        x, y = d["xy"]
        seen = [ang for ang in (0, 30, 45)
                if not ray(pieces, (x, y, bot - 1.0), (0, math.cos(math.radians(ang)), -math.sin(math.radians(ang))),
                           ("bottom",))]
        report("PASS" if seen else "FAIL", "P", "LED %s visible from behind at %s deg below the slab" % (ref, seen))
    # BOOT: a paperclip from the underside straight up to the button (held while the cable goes in)
    r = fps["SW101"]
    x, y = r["xy"]
    z0 = bot - 1.5 - 0.05
    seg = ray(pieces, (x, y, z0), (0, 0, -1), ("bottom",))
    if seg:
        report("FAIL", "P", "BOOT: the paperclip path is blocked %.1f mm below the button" % seg[0][0])
    else:
        top = slab_to_world((x, y, z0))
        down = slab_dir((0, 0, -1))
        report("PASS", "P", "BOOT: clear path, %.1f mm from the desk to the button" % (top[2] / -down[2]))


def check_screws(pieces):
    def seat_and_end(x, y, kind):
        below = (x, y, -G.SLAB_H - 80)
        seg = ray(pieces, (x + 2.35, y + 0.01, below[2]), (0, 0, 1), ("bottom",))
        seat = below[2] + seg[0][0] if seg else None
        segs = ray(pieces, (x + 0.31, y + 0.01, below[2]), (0, 0, 1))
        end = below[2] + segs[0][0] if segs else None
        top = ray(pieces, (x + 2.6, y + 0.01, G.PCB_BOT), (0, 0, 1), ("top",))
        mouth = G.PCB_BOT + top[0][0] if top else None
        return seat, end, mouth

    def insert_wall(x, y, z, r_hole, kinds):
        walls = []
        for a in np.radians(np.arange(0, 360, 15) + 3):
            d = (math.cos(a), math.sin(a), 0)
            o = (x + 500 * d[0], y + 500 * d[1], z)  # start outside the case
            seg = ray(pieces, o, (-d[0], -d[1], 0), kinds)
            near = [s for s in seg if 500 - s[1] >= r_hole - 0.05]  # the solid between the hole and the outside
            walls.append(near[-1][1] - near[-1][0] if near else 0.0)
        return min(walls)

    for kind, pts in (("case", G.case_screws()), ("bolt", [tuple(b) for b in G.PORTS.get("bolts", [])])):
        length = SCREWS[kind]
        for x, y in pts:
            seat, end, mouth = seat_and_end(x, y, kind)
            if seat is None or end is None or mouth is None:
                report("FAIL", "S", "M3 x %g at %.1f,%.1f: no counterbore / hole / insert found" % (length, x, y))
                continue
            tip = seat + length
            engaged = min(tip, mouth + M3_INSERT) - mouth
            wall = insert_wall(x, y, mouth + 1.5, G.INSERT_M3[0] / 2, ("top",))
            # how deep the head sits in its counterbore, from the desk (along the screw axis)
            p0, d = slab_to_world((x, y, seat)), slab_dir((0, 0, 1))
            depth = p0[2] / d[2]
            msg = ("M3 x %g at %.1f,%.1f: head seat %.2f (%.1f mm deep from the desk), tip %.2f, hole ends %.2f "
                   "(margin %.2f), %.2f mm in the insert, insert wall %.2f"
                   % (length, x, y, seat, depth, tip, end, end - tip, engaged, wall))
            if end - tip < 0.3 or engaged < 2.4 or wall < 1.0:
                report("FAIL", "S", msg)
            elif wall < MIN_INSERT_WALL - 0.02:
                report("WARN", "S", msg)
            else:
                report("PASS", "S", msg)
    # top mount: M2 screws through the plate's ears into the top frame
    head_d, head_h = M2["head"]
    for *_, (x, y) in mount.ears():
        under = ray(pieces, (x + 2.6, y + 0.01, G.PLATE_TOP - PLATE_T), (0, 0, 1), ("top",))
        mouth = G.PLATE_TOP - PLATE_T + under[0][0] if under else None  # the frame's underside next to the hole
        seg = ray(pieces, (x + 0.31, y + 0.01, G.PLATE_TOP - 0.2), (0, 0, 1), ("top",))
        end = G.PLATE_TOP - 0.2 + seg[0][0] if seg else None  # end of the insert hole
        skin = seg[0][1] - seg[0][0] if seg else 0.0  # plastic between the hole and the deck
        if mouth is None or end is None:
            report("FAIL", "S", "M2 at %.1f,%.1f: no insert hole in the top frame" % (x, y))
            continue
        tip = G.PLATE_TOP - PLATE_T + M2["length"]
        engaged = min(tip, mouth + M2_INSERT) - mouth
        wall = insert_wall(x, y, mouth + 1.5, mount.INSERT[0] / 2, ("top",))
        msg = ("M2 x %g at %.1f,%.1f: plate top %.2f on the frame at %.2f, tip %.2f, hole ends %.2f (margin %.2f), "
               "%.2f mm in the insert, insert wall %.2f, deck over the insert %.2f"
               % (M2["length"], x, y, G.PLATE_TOP, mouth, tip, end, end - tip, engaged, wall, skin))
        if abs(mouth - G.PLATE_TOP) > 0.05 or end - tip < 0.3 or engaged < 2.4 or wall < 1.0 or skin < 1.2:
            report("FAIL", "S", msg)
        elif wall < MIN_INSERT_WALL - 0.02 or skin < 2.0:
            report("WARN", "S", msg)
        else:
            report("PASS", "S", msg)
    # the bolt bosses clamp the plate's back tabs against the frame; their shoulders are backstops under the PCB
    for x, y in G.PORTS.get("bolts", []):
        seg = ray(pieces, (x + 2.6, y + 0.01, G.PLATE_TOP - PLATE_T + 0.5), (0, 0, -1), ("bottom",))
        boss = G.PLATE_TOP - PLATE_T + 0.5 - seg[0][0] if seg else None
        seg = ray(pieces, (x + 4.2, y + 0.01, G.PCB_BOT + 0.1), (0, 0, -1), ("bottom",))
        stop = G.PCB_BOT + 0.1 - seg[0][0] if seg else None
        frame = ray(pieces, (x + 2.6, y + 0.01, G.PLATE_TOP - PLATE_T), (0, 0, 1), ("top",))
        top = G.PLATE_TOP - PLATE_T + frame[0][0] if frame else None
        if boss is None or stop is None or top is None:
            report("FAIL", "S", "bolt at %.1f,%.1f: boss / backstop / frame not found" % (x, y))
            continue
        msg = ("bolt at %.1f,%.1f: plate tab %.2f..%.2f clamped between boss top %.2f and frame %.2f; backstop %.2f mm "
               "under the PCB" % (x, y, G.PLATE_TOP - PLATE_T, G.PLATE_TOP, boss, top, G.PCB_BOT - stop))
        ok = abs(boss - (G.PLATE_TOP - PLATE_T)) < 0.05 and abs(top - G.PLATE_TOP) < 0.05
        report("PASS" if ok and 0.3 <= G.PCB_BOT - stop <= 1.0 else "FAIL", "S", msg)


def sample_surface(mesh, density):
    """Random points on the mesh, one per `density` mm2, with their triangle index."""
    rng = np.random.default_rng(1)
    n = int(mesh.area.sum() / density)
    idx = rng.choice(len(mesh.area), size=n, p=mesh.area / mesh.area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    flip = r1 + r2 > 1
    r1[flip], r2[flip] = 1 - r1[flip], 1 - r2[flip]
    pts = mesh.v0[idx] + r1[:, None] * mesh.e1[idx] + r2[:, None] * mesh.e2[idx]
    return pts, idx


def clusters(points, radius):
    if not len(points):
        return []
    pairs = cKDTree(points).query_pairs(radius, output_type="ndarray")
    n = len(points)
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n)) if len(pairs) else \
        coo_matrix((n, n))
    _, lab = connected_components(g, directed=False)
    return [np.flatnonzero(lab == k) for k in range(lab.max() + 1)]


def check_walls(pieces):
    for name in pieces.names:
        m = pieces.mesh[name]
        pts, idx = sample_surface(m, 0.5)
        nrm = m.normal[idx]
        t, hit = m.first_hits(pts - 1e-3 * nrm, -nrm, 3.0)
        # a wall has two opposing faces; a ray that leaves through a face at a right angle to the start face is
        # only crossing the edge where two faces meet
        opposing = (hit >= 0) & ((m.normal[np.maximum(hit, 0)] * nrm).sum(1) < -0.5)
        thin = (t < MIN_WALL) & opposing
        found = 0
        for c in clusters(pts[thin], 1.5):
            p = world_to_slab(pts[thin][c])
            lo, hi = p.min(0), p.max(0)
            if len(c) < 3:
                continue
            found += 1
            report("FAIL" if t[thin][c].min() < MIN_WALL_FAIL else "WARN", "W", "%s: wall %.2f-%.2f mm over %.0f mm2 at slab x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f"
                   % (name, t[thin][c].min(), np.median(t[thin][c]), len(c) * 0.5, lo[0], hi[0], lo[1], hi[1],
                      lo[2], hi[2]))
        if not found:
            report("PASS", "W", "%s: no wall thinner than %.1f mm (%d samples)" % (name, MIN_WALL, len(pts)))


def bridge_span(m, tris, up, axes):
    """Just under a flat down-facing region, look for walls on both sides along each horizontal axis: the region
    is a bridge if every sample has walls on both sides along some axis (span = the shortest such distance, the
    way a slicer bridges), None if it is open on one side (a ledge)."""
    pick = tris[np.argsort(-m.area[tris])][:8]
    spans = []
    for i in pick:
        p = m.tri[i].mean(0) - 0.3 * up
        best = None
        for a in axes:
            t, _ = m.first_hits(np.array([p, p]), np.array([a, -a]), 120.0)
            if np.isfinite(t).all():
                best = t.sum() if best is None else min(best, t.sum())
        if best is None:
            return None
        spans.append(best)
    return max(spans)


def check_printing(pieces):
    lim = -math.sin(math.radians(90 - OVERHANG))  # outward normal more downward than this = overhang
    for name in pieces.names:
        m = pieces.mesh[name]
        up = np.array([0, 0, 1.0]) if name.startswith("bottom") else slab_dir((0, 0, 1))
        h = m.tri @ up  # height of every vertex in the print orientation
        bed = h.min()
        ext = m.tri.reshape(-1, 3)
        if name.startswith("top"):
            ext = world_to_slab(ext)
        size = ext.max(0) - ext.min(0)
        report("PASS" if max(size[0], size[1]) <= BED else "FAIL", "O",
               "%s: %.1f x %.1f x %.1f mm on a %g mm bed" % (name, size[0], size[1], size[2], BED))
        c = m.normal @ up
        axes = [np.array([1.0, 0, 0]), np.array([0, 1.0, 0])] if name.startswith("bottom") else \
            [slab_dir((1, 0, 0)), slab_dir((0, 1, 0))]
        over = (c < lim) & (h.mean(1) > bed + 0.4) & (m.area > 1e-6)
        ids = np.flatnonzero(over)
        if not len(ids):
            continue
        cent = m.tri[ids].mean(1)
        for grp in clusters(cent, 2.5):
            tri = ids[grp]
            area = m.area[tri].sum()
            if area < 3.0:
                continue
            ang = np.degrees(np.arccos(np.clip(-c[tri], -1, 1)))  # 0 = ceiling
            p = m.tri[tri].reshape(-1, 3)
            ps = world_to_slab(p)
            lo, hi = ps.min(0), ps.max(0)
            flat = c[tri] < -0.985
            if flat.any():
                q = m.tri[tri[flat]].reshape(-1, 3)
                width = min(np.ptp(q @ a) for a in axes)
                span = bridge_span(m, tri[flat], up, axes)
                if span is None:  # open on one side along both axes: a ledge printed in the air
                    kind = "ledge %.1f mm wide, supported on one side only" % width
                    status = "WARN" if width > 1.0 else "PASS"
                else:
                    kind = "bridge %.1f mm" % span
                    status = "WARN" if span > BRIDGE else "PASS"
            else:
                kind = "overhang %.0f deg from vertical" % (90 - ang.min())
                status = "WARN"
            report(status, "O", "%s: %s, %.0f mm2 at slab x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f"
                   % (name, kind, area, lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))


def main():
    pieces = Pieces()
    check_collisions(pieces)
    if not any(code == "C" and status != "PASS" for status, code, _ in results):
        report("PASS", "C", "no inside part within %.1f mm of a printed piece" % CLEAR)
    check_assembly(pieces)
    check_ports(pieces)
    check_screws(pieces)
    check_walls(pieces)
    check_printing(pieces)
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    lines = ["%-4s %s  %s" % r for r in sorted(results, key=lambda r: (order[r[0]], r[1]))]
    n = {s: sum(1 for r in results if r[0] == s) for s in order}
    lines.append("%d FAIL, %d WARN, %d PASS" % (n["FAIL"], n["WARN"], n["PASS"]))
    text = "\n".join(lines) + "\n"
    (BUILD / "case/check-fit.txt").write_text(text)
    print(text, end="")
    sys.exit(1 if n["FAIL"] else 0)


if __name__ == "__main__":
    main()
