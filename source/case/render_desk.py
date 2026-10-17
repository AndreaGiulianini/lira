"""Desk scene: the assembled keyboard seen from above, on a desk mat, with a few things around it.

    blender -b --factory-startup -P case/render_desk.py -- build [samples [scale%]]   (make renders)

The keyboard is built by case/render.py (same models and materials). Around it: an oak desk (Poly Haven texture,
case/fetch_assets.py), the desk mat printed with case/deskmat.py's drawing, a coiled USB-C cable with an aviator
connector plugged into the keyboard, a mug of coffee, a potted succulent (Poly Haven), a notebook and a pen, two
floppy disks and a few loose keycaps and switches. Writes build/img/desk.png and render/desk.blend.
Units: metres in the scene, millimetres in this file (MM converts); the keyboard centre is the origin, +y = back.
"""
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render as R  # noqa: E402

MM = R.MM
ASSETS = Path(__file__).resolve().parents[1] / "assets" / "polyhaven"
MAT_SIZE, MAT_T, MAT_TOP_EDGE = (900.0, 400.0), 3.0, 150.0  # desk mat; its back edge at y = 150 (deskmat.MAT_KB)
FRAME_W = 640.0  # what the camera sees across, at the mat
RES = (2560, 1440)
# where the loose things go: x, y (mm, keyboard centre = 0), [z,] turn about z, about x (degrees)
FLOPPIES = [(285, -108, MAT_T, 9), (190, -172, MAT_T, -17)]
SPARE_CAPS = [({"label": "esc", "mesh": "keycap-r2-1x1", "accent": True}, (118, -102, 18, 0)),
              ({"label": "⌘", "mesh": "keycap-r4-1.25x1", "modifier": True}, (92, -140, -24, 0)),
              ({"label": "A", "mesh": "keycap-r3-1x1"}, (128, -142, 40, 180))]
SPARE_SWITCHES = [(62, -112, 25, 0), (155, -122, -70, 90)]


def mat_(name, color, rough, **kw):
    return R.principled(name, color, rough, **kw)


def obj_from_bmesh(name, bm, material, coll):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if material:
        me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    coll.objects.link(o)
    return o


def rounded_rect(w, h, r, seg=10):
    """Outline points (mm) of a w x h rectangle with corner radius r, centred on the origin."""
    pts = []
    for cx, cy, a0 in ((w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90), (-w / 2 + r, -h / 2 + r, 180),
                       (w / 2 - r, -h / 2 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def slab_block(name, w, h, t, r, material, coll, bevel=0.0):
    """Rounded-rectangle block w x h x t (mm), bottom at z = 0, centred on the origin."""
    bm = bmesh.new()
    verts = [bm.verts.new((x * MM, y * MM, 0)) for x, y in rounded_rect(w, h, r)]
    face = bm.faces.new(verts)
    ext = bmesh.ops.extrude_face_region(bm, geom=[face])
    bmesh.ops.translate(bm, vec=(0, 0, t * MM), verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    o = obj_from_bmesh(name, bm, material, coll)
    if bevel:
        b = o.modifiers.new("round", "BEVEL")
        b.width, b.segments, b.limit_method = bevel * MM, 3, "ANGLE"
    return o


def textured(name, maps, scale, rough_mult=1.0):
    """Material from Poly Haven maps (Diffuse, Rough, nor_gl) with object-space box mapping, `scale` metres per tile."""
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / scale, 1 / scale, 1 / scale)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])

    def img(fname, colour):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(str(maps / fname))
        if not colour:
            t.image.colorspace_settings.name = "Non-Color"
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        return t
    nt.links.new(img("Diffuse_2k.jpg", True).outputs["Color"], p.inputs["Base Color"])
    rough = img("Rough_2k.jpg", False)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation, mul.inputs[1].default_value = "MULTIPLY", rough_mult
    nt.links.new(rough.outputs["Color"], mul.inputs[0])
    nt.links.new(mul.outputs[0], p.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(img("nor_gl_2k.jpg", False).outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], p.inputs["Normal"])
    return m


def mat_material(png):
    """The printed desk mat: the drawing as colour, a fine weave as bump, cloth sheen."""
    m = bpy.data.materials.new("desk mat")
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Roughness"].default_value = 0.9
    p.inputs["Sheen Weight"].default_value = 0.15
    p.inputs["Sheen Roughness"].default_value = 0.5
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")  # object coordinates (m) -> 0..1 over the mat, v up = back edge
    mp.inputs["Location"].default_value = (0.5, 0.5, 0)
    mp.inputs["Scale"].default_value = (1 / (MAT_SIZE[0] * MM), 1 / (MAT_SIZE[1] * MM), 1)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    # Mapping: point * scale + location (scale applied first: Point type)
    img = nt.nodes.new("ShaderNodeTexImage")
    img.image = bpy.data.images.load(str(png))
    img.interpolation = "Cubic"
    nt.links.new(mp.outputs["Vector"], img.inputs["Vector"])
    nt.links.new(img.outputs["Color"], p.inputs["Base Color"])
    # weave: two perpendicular sine bands, 0.6 mm pitch
    waves = []
    for axis in ("X", "Y"):
        w = nt.nodes.new("ShaderNodeTexWave")
        w.wave_type, w.bands_direction = "BANDS", axis
        w.inputs["Scale"].default_value = 1 / (0.6 * MM) / 6.28
        w.inputs["Distortion"].default_value = 1.5
        nt.links.new(tc.outputs["Object"], w.inputs["Vector"])
        waves.append(w)
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY"
    nt.links.new(waves[0].outputs["Fac"], add.inputs[0])
    nt.links.new(waves[1].outputs["Fac"], add.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.08 * MM
    nt.links.new(add.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    return m


def tube(name, splines, radius, material, coll):
    """Curve object with a round section; splines = [(type, [points mm])] ('POLY' or 'BEZIER' auto handles)."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth, cu.bevel_resolution = radius * MM, 4
    cu.resolution_u = 12
    cu.use_fill_caps = True
    for kind, pts in splines:
        if kind == "BEZIER":
            s = cu.splines.new("BEZIER")
            s.bezier_points.add(len(pts) - 1)
            for bp, p in zip(s.bezier_points, pts):
                bp.co = Vector(p) * MM
                bp.handle_left_type = bp.handle_right_type = "AUTO"
        else:
            s = cu.splines.new("POLY")
            s.points.add(len(pts) - 1)
            for sp, p in zip(s.points, pts):
                sp.co = (p[0] * MM, p[1] * MM, p[2] * MM, 1.0)
    cu.materials.append(material)
    o = bpy.data.objects.new(name, cu)
    coll.objects.link(o)
    return o


def cylinder(name, r, length, material, coll, verts=48, bevel=0.0):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=verts, radius1=r * MM, radius2=r * MM, depth=length * MM)
    o = obj_from_bmesh(name, bm, material, coll)
    for f in o.data.polygons:
        f.use_smooth = True
    o.data.set_sharp_from_angle(angle=math.radians(40))
    if bevel:
        b = o.modifiers.new("round", "BEVEL")
        b.width, b.segments, b.limit_method = bevel * MM, 3, "ANGLE"
    return o


def at(x, y, z, rz=0.0, rx=0.0):
    """Placement matrix: position in mm, then turned rz degrees about z after rx about x."""
    return (Matrix.Translation((x * MM, y * MM, z * MM)) @ Matrix.Rotation(math.radians(rz), 4, "Z")
            @ Matrix.Rotation(math.radians(rx), 4, "X"))


def group(name, coll, objs, matrix):
    e = bpy.data.objects.new(name, None)
    coll.objects.link(e)
    for o in objs:
        o.parent = e
    e.matrix_world = matrix
    return e


# ----------------------------------------------------------------------------------------------------- props
def mug(coll, M):
    """Cylindrical ceramic mug, 84 mm across, 92 mm tall, with coffee and a handle (towards +x)."""
    bm = bmesh.new()
    prof = [(0, 0), (40, 0), (42, 2), (42, 90), (41.2, 92), (40.2, 92), (39.5, 90), (39.5, 9), (38, 7.5), (0, 7.5)]
    vs = [bm.verts.new((r * MM, 0, z * MM)) for r, z in prof]
    for a, b in zip(vs, vs[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], cent=(0, 0, 0), axis=(0, 0, 1), steps=72,
                   angle=math.radians(360), use_merge=True)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    cup = obj_from_bmesh("mug", bm, M["ceramic"], coll)
    for f in cup.data.polygons:
        f.use_smooth = True
    cup.data.set_sharp_from_angle(angle=math.radians(50))
    coffee = cylinder("coffee", 39.6, 1.0, M["coffee"], coll, 72)
    coffee.location = (0, 0, 80 * MM)
    # handle: part of a torus (major 21 mm, minor 5.5 mm) standing in the xz plane
    bm = bmesh.new()
    seg, ring = 48, 16
    grid = []
    for i in range(seg + 1):
        u = math.radians(-100 + 200 * i / seg)
        row = []
        for j in range(ring):
            v = 2 * math.pi * j / ring
            rr = 21 + 5.5 * math.cos(v)
            row.append(bm.verts.new(((42 + 3 + rr * math.cos(u) - 21 + 4) * MM, 5.5 * math.sin(v) * MM,
                                     (48 + rr * math.sin(u)) * MM)))
        grid.append(row)
    for i in range(seg):
        for j in range(ring):
            bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][(j + 1) % ring], grid[i][(j + 1) % ring]))
    handle = obj_from_bmesh("mug handle", bm, M["ceramic"], coll)
    for f in handle.data.polygons:
        f.use_smooth = True
    return [cup, coffee, handle]


def notebook(coll, M):
    """A5 notebook (148 x 210 x 11 mm), kraft cover, elastic band, page block visible at the edges."""
    pages = slab_block("notebook pages", 146, 207, 10.0, 3.0, M["paper"], coll)
    pages.location = (1.5 * MM, 0, 0.6 * MM)
    cover_b = slab_block("notebook back cover", 148, 210, 0.6, 3.5, M["kraft"], coll)
    cover_t = slab_block("notebook front cover", 148, 210, 0.6, 3.5, M["kraft"], coll)
    cover_t.location = (0, 0, 10.6 * MM)
    band = slab_block("elastic band", 9, 211, 0.9, 0.5, M["band"], coll)
    band.location = (52 * MM, 0, 11.0 * MM)
    return [pages, cover_b, cover_t, band]


def pen(coll, M):
    """Fountain pen, 140 mm, black resin with brass trim, lying along +x."""
    body = cylinder("pen body", 6.5, 120, M["resin"], coll, 48, bevel=1.2)
    body.rotation_euler = (0, math.radians(90), 0)
    body.location = (0, 0, 6.5 * MM)
    ring = cylinder("pen ring", 6.7, 3, M["brass"], coll, 48)
    ring.rotation_euler = (0, math.radians(90), 0)
    ring.location = (-12 * MM, 0, 6.5 * MM)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=48, radius1=5.5 * MM, radius2=0.6 * MM, depth=18 * MM)
    nib = obj_from_bmesh("pen nib", bm, M["brass"], coll)
    for f in nib.data.polygons:
        f.use_smooth = True
    nib.rotation_euler = (0, math.radians(90), 0)
    nib.location = (69 * MM, 0, 6.5 * MM)
    clip = slab_block("pen clip", 52, 2.6, 1.2, 1.0, M["brass"], coll)
    clip.location = (-30 * MM, 0, 12.6 * MM)
    return [body, ring, nib, clip]


def floppy(coll, M, shell, label_lines):
    """3.5-inch floppy disk: 90 x 94 x 3.3 mm shell, sliding metal shutter, paper label with text."""
    objs = [slab_block("floppy shell", 90, 94, 3.3, 1.2, shell, coll, bevel=0.4)]
    shutter = slab_block("floppy shutter", 50, 31, 0.35, 0.6, M["shutter"], coll)
    shutter.location = (-6 * MM, (94 / 2 - 31 / 2 + 0.01) * MM, 3.3 * MM)
    slot = slab_block("floppy shutter window", 12, 17, 0.1, 0.5, M["slot"], coll)
    slot.location = (-6 * MM, (94 / 2 - 14) * MM, 3.66 * MM)
    label = slab_block("floppy label", 70, 56, 0.15, 1.0, M["paper"], coll)
    label.location = (0, -15 * MM, 3.3 * MM)
    objs += [shutter, slot, label]
    for i, (line, size) in enumerate(label_lines):
        cu = bpy.data.curves.new("label text", "FONT")
        cu.body = line
        cu.size = size * MM
        t = bpy.data.objects.new("label text", cu)
        coll.objects.link(t)
        cu.materials.append(M["ink"])
        t.location = (-31 * MM, (-1 - i * 8.5) * MM, 3.47 * MM)
        objs.append(t)
    return objs


def coiled_cable(coll, M, port, axis_dir):
    """USB-C plug in the keyboard's port, the cable down to the mat, a coil behind the keyboard, an aviator
    connector, and the cable leaving towards the back right."""
    objs = []
    d = Vector(axis_dir).normalized()
    up = Vector((0, 0, 1))
    side = d.cross(up).normalized()
    # plug overmold 12 x 6.5 x 26 mm, from 1 mm inside the window outwards
    p0 = Vector(port) - d * 1.0
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(12 * MM, 26 * MM, 6.5 * MM), verts=bm.verts)
    plug = obj_from_bmesh("usb-c plug", bm, M["anodised"], coll)
    b = plug.modifiers.new("round", "BEVEL")
    b.width, b.segments = 2.2 * MM, 4
    rot = Matrix((side, d, side.cross(d))).transposed().to_4x4()
    plug.matrix_world = Matrix.Translation((p0 + d * 13.0) * MM) @ rot
    objs.append(plug)
    end = p0 + d * 26.0
    z_coil = MAT_T + 6.0 + 1.7
    y_coil = end.y + 18.0
    x0, x1 = end.x + 26.0, end.x + 150.0
    lead = [tuple(end), tuple(end + d * 14 - up * 3), (end.x + 12, y_coil - 2, z_coil + 2)]
    turns, pitch = int((x1 - x0) / 3.6), 3.6
    coil = []
    for i in range(turns * 24 + 1):
        a = 2 * math.pi * i / 24
        coil.append((x0 + i * pitch / 24, y_coil + 6.0 * math.cos(a), z_coil + 6.0 * math.sin(a)))
    xa = coil[-1][0]
    tail = [(xa + 33, y_coil, z_coil), (xa + 48, y_coil + 4, MAT_T + 1.8), (xa + 80, y_coil + 40, MAT_T + 1.8),
            (xa + 95, 240.0, 1.8)]
    objs.append(tube("coiled cable", [("BEZIER", lead + [coil[0]]), ("POLY", coil),
                                      ("BEZIER", [coil[-1], (xa + 3, y_coil, z_coil)])], 1.7, M["paracord"], coll))
    objs.append(tube("cable to the computer", [("BEZIER", tail)], 1.7, M["paracord"], coll))
    # aviator connector: two knurled halves, 14 mm across
    for i, (x, ln, m) in enumerate(((xa + 10, 14, M["anodised"]), (xa + 24, 14, M["aviator"]))):
        c = cylinder("aviator %d" % i, 7.0, ln, m, coll, 48, bevel=0.8)
        c.rotation_euler = (0, math.radians(90), 0)
        c.location = (x * MM, y_coil * MM, z_coil * MM)
        objs.append(c)
    ring = cylinder("aviator ring", 7.6, 4, M["aviator"], coll, 48, bevel=0.4)
    ring.rotation_euler = (0, math.radians(90), 0)
    ring.location = ((xa + 17) * MM, y_coil * MM, z_coil * MM)
    objs.append(ring)
    return objs


def loose_switch(coll, matrix, name):
    parts = []
    for part in R.S["switch"]:
        o = bpy.data.objects.new(name + " " + part, R.MESHES["switch-" + part])
        coll.objects.link(o)
        parts.append(o)
    return group(name, coll, parts, matrix)


# ---------------------------------------------------------------------------------------------------- scene
def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    R.make_materials()
    groups = R.build()
    sc = bpy.context.scene
    everything = [o for g in groups.values() for o in g.all_objects]
    roots = [o for o in everything if o.parent is None]
    bpy.context.view_layer.update()
    pts = R.bbox_points(everything)
    c = sum(pts, Vector()) / len(pts)
    low = min(p.z for p in pts)
    shift = Matrix.Translation((-c.x, -c.y, MAT_T * MM - low))
    for o in roots:
        o.matrix_world = shift @ o.matrix_world
    bpy.context.view_layer.update()

    props = R.collection("desk")
    M = {
        "ceramic": mat_("glazed ceramic", "#eeeae3", 0.18, coat=0.6),
        "coffee": mat_("coffee", "#1e120b", 0.08, coat=0.3),
        "paper": mat_("paper", "#f1ece0", 0.85),
        "kraft": mat_("kraft cover", "#a9825a", 0.75, bump=0.4),
        "band": mat_("elastic band", R.ACCENT, 0.7),
        "resin": mat_("black resin", "#141414", 0.25, coat=0.5),
        "brass": mat_("brass", "#c9a45c", 0.28, metal=1.0),
        "shutter": mat_("floppy shutter", "#c7cacd", 0.32, metal=1.0),
        "slot": mat_("floppy slot", "#0d0d0d", 0.5),
        "ink": mat_("ink", "#2a2a33", 0.6),
        "floppy dark": mat_("floppy dark", "#2c2c2e", 0.45, bevel=0.3),
        "floppy beige": mat_("floppy beige", "#d8d0bc", 0.45, bevel=0.3),
        "paracord": mat_("paracord", R.ACCENT, 0.65, bump=0.6),
        "anodised": mat_("anodised aluminium", "#2d2d30", 0.35, metal=1.0, bevel=0.3),
        "aviator": mat_("polished steel", "#d2d4d6", 0.15, metal=1.0),
    }
    # desk and mat
    desk = slab_block("desk", 2400, 1600, 25, 5, textured("oak desk", ASSETS / "oak_veneer_01", 0.9, 0.9), props)
    desk.location = (0, 0, -25 * MM)
    mat = slab_block("desk mat", MAT_SIZE[0], MAT_SIZE[1], MAT_T, 14, mat_material(R.SRC / "deskmat.png"), props,
                     bevel=0.8)
    mat.location = (0, (MAT_TOP_EDGE - MAT_SIZE[1] / 2) * MM, 0)
    edge = rounded_rect(MAT_SIZE[0] - 2.2, MAT_SIZE[1] - 2.2, 13)
    tube("stitched edge", [("POLY", [(x, y + MAT_TOP_EDGE - MAT_SIZE[1] / 2, MAT_T - 1.1) for x, y in edge + edge[:1]])],
         1.3, mat_("edge stitching", "#2f2b28", 0.8, bump=0.5), props)

    # cable into the USB-C port (stand-in J1: slab box, receptacle axis 1.63 mm under the PCB)
    j1 = next(s for s in R.S["stand_ins"] if s["ref"] == "J1")
    x0, y0, x1, y1 = j1["box"]
    port = shift @ R.slab((x0 + x1) / 2, y1, R.S["pcb_bot"] - j1["h"] / 2).to_translation() / MM
    axis = (shift.to_3x3() @ R.SLAB.to_3x3() @ Vector((0, 1, 0)))
    coiled_cable(props, M, port, axis)

    # mug, plant, notebook and pen, floppies, loose keycaps and switches
    group("mug", props, mug(props, M), Matrix.Translation((265 * MM, 112 * MM, MAT_T * MM))
          @ Matrix.Rotation(math.radians(-30), 4, "Z"))
    plant_file = ASSETS / "potted_plant_04" / "potted_plant_04.gltf"
    if plant_file.exists():
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=str(plant_file))
        new = [o for o in bpy.data.objects if o not in before]
        for o in new:
            for cl in o.users_collection:
                cl.objects.unlink(o)
            props.objects.link(o)
        top = [o for o in new if o.parent is None]
        group("plant", props, top, Matrix.Translation((-268 * MM, 196 * MM, 0)) @ Matrix.Rotation(0.6, 4, "Z")
              @ Matrix.Diagonal((0.82, 0.82, 0.82, 1)))
    group("notebook", props, notebook(props, M), Matrix.Translation((-262 * MM, -118 * MM, MAT_T * MM))
          @ Matrix.Rotation(math.radians(-14), 4, "Z"))
    group("pen", props, pen(props, M), Matrix.Translation((-232 * MM, -84 * MM, (MAT_T + 11.6) * MM))
          @ Matrix.Rotation(math.radians(28), 4, "Z"))
    group("floppy 1", props, floppy(props, M, M["floppy dark"], [("LIRA", 7.0), ("FIRMWARE · RMK", 3.4),
                                                                 ("57 KEYS · USB AUDIO", 3.4)]), at(*FLOPPIES[0]))
    group("floppy 2", props, floppy(props, M, M["floppy beige"], [("VIAL LAYOUT", 5.0), ("BACKUP", 3.4)]),
          at(*FLOPPIES[1]))
    for k, (x, y, rz, rx) in SPARE_CAPS:
        lift = 0.0 if rx == 0 else max(v.co.z for v in R.MESHES[k["mesh"]].vertices) / MM
        R.add_keycap(k, at(x, y, MAT_T + lift, rz, rx), props)
    for i, (x, y, rz, rx) in enumerate(SPARE_SWITCHES):  # upright on its pins, or on its side
        loose_switch(props, at(x, y, MAT_T + (7.8 if rx else 3.16), rz, rx), "switch %d" % i)

    # light: a big soft window light from the back left, a weak fill, the HDRI for reflections
    R.render_settings()
    w = bpy.data.worlds.new("room")
    sc.world = w
    if w.node_tree is None:
        w.use_nodes = True
    env = w.node_tree.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(R.BLENDER_DATA / "studiolights/world/interior.exr"))
    w.node_tree.links.new(env.outputs["Color"], w.node_tree.nodes["Background"].inputs["Color"])
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.25

    def area(name, loc, power, size, color):
        dl = bpy.data.lights.new(name, "AREA")
        dl.energy, dl.color = power, color
        dl.shape, dl.size, dl.size_y = "RECTANGLE", size[0], size[1]
        lo = bpy.data.objects.new(name, dl)
        sc.collection.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()

    area("window", (-1.1, 0.95, 1.25), 110, (0.6, 0.4), (1.0, 0.93, 0.84))
    area("fill", (0.9, -0.7, 1.0), 14, (1.2, 1.2), (0.86, 0.92, 1.0))

    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.lens = 50
    cam.data.sensor_width = 36
    height = FRAME_W / 36 * 50  # mm above the mat
    cam.location = (0, 0, (height + MAT_T) * MM)
    cam.rotation_euler = (0, 0, 0)
    cam.data.dof.use_dof = True
    cam.data.dof.focus_distance = (height - 40) * MM  # keycap tops
    cam.data.dof.aperture_fstop = 5.6
    cam.data.clip_start, cam.data.clip_end = 0.01, 10
    sc.render.resolution_x, sc.render.resolution_y = RES
    sc.render.resolution_percentage = R.SCALE
    bpy.ops.wm.save_as_mainfile(filepath=str(R.SRC / "desk.blend"))
    out = R.IMG / "desk.png"
    R.IMG.mkdir(parents=True, exist_ok=True)
    sc.render.filepath = str(out)
    bpy.ops.render.render(write_still=True)
    print("wrote", out.relative_to(R.BUILD.parent.parent))


if __name__ == "__main__":
    main()
