"""Photo-style pictures of the assembled keyboard with Blender Cycles.

    blender -b --factory-startup -P case/render.py -- build [samples [scale% [picture,...]]]
                                                                                    (run by `make renders`)
Reads build/render/ (written by case/render_parts.py): the printed case pieces, the routed PCB and the
plate exported by KiCad with every 3D model, and stand-in switches and keycaps (with legends). Writes
build/img/case-{front,back,side,top,bottom,exploded}.png and pcb-{top,bottom}.png (the bare PCB), and
saves the scene as render/keyboard.blend, to open in Blender.
Scene units are metres; the build files are in millimetres (MM converts).
"""
import json
import math
import re
import sys
from pathlib import Path

import bmesh
import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

ARGS = sys.argv[sys.argv.index("--") + 1:]
BUILD = Path(ARGS[0]).resolve()
SAMPLES = int(ARGS[1]) if len(ARGS) > 1 else 128
SCALE = int(ARGS[2]) if len(ARGS) > 2 else 100  # resolution %, for quick drafts
ONLY = ARGS[3].split(",") if len(ARGS) > 3 else None  # render only these pictures (e.g. case-front)
SRC, IMG = BUILD / "render", BUILD / "img"
S = json.loads((SRC / "scene.json").read_text())
MM = 0.001
SLAB = Matrix.Translation((0, S["ty"] * MM, S["tz"] * MM)) @ Matrix.Rotation(math.radians(S["tilt"]), 4, "X")
NORMAL = (SLAB.to_3x3() @ Vector((0, 0, 1))).normalized()  # perpendicular to the deck
BLENDER_DATA = Path(bpy.utils.resource_path("LOCAL")) / "datafiles"

# colours (sRGB hex) after the Apple M0110: warm beige case, cream and warm-grey keycaps, dark legends
CASE, CAP_ALPHA, CAP_MOD, LEGEND, BACKDROP = "#d4caaf", "#e9e2cf", "#a8a189", "#2e2c28", "#efece6"
ACCENT = "#d9662b"  # burnt orange: Esc / Return / Enter keycaps, switch stems, the desk scene's cable
KEY_W, BACKDROP_GAIN = 24.0, 1.6  # key light power (W), backdrop brightness


def srgb(hexcol):
    c = [int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]


def slab(x, y, z):
    """Slab-frame point (mm) -> world matrix."""
    return SLAB @ Matrix.Translation((x * MM, y * MM, z * MM))


# ------------------------------------------------------------------------------------------------- materials
def principled(name, color, rough, metal=0.0, coat=0.0, bevel=0.0, bump=0.0, spec=0.5):
    m = bpy.data.materials.new(name)
    if m.node_tree is None:
        m.use_nodes = True
    nt = m.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = srgb(color) if isinstance(color, str) else color
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Specular IOR Level"].default_value = spec
    if coat:
        p.inputs["Coat Weight"].default_value = coat
    normal = None
    if bevel:  # rounded-edge highlights: printed and moulded parts never have razor edges
        b = nt.nodes.new("ShaderNodeBevel")
        b.inputs["Radius"].default_value = bevel * MM
        b.samples = 4
        normal = b.outputs["Normal"]
    if bump:  # fine grain (PBT texture, matte print)
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 4000.0
        n.inputs["Detail"].default_value = 2.0
        bu = nt.nodes.new("ShaderNodeBump")
        bu.inputs["Strength"].default_value = bump
        bu.inputs["Distance"].default_value = 0.02 * MM
        nt.links.new(n.outputs["Fac"], bu.inputs["Height"])
        if normal is not None:
            nt.links.new(normal, bu.inputs["Normal"])
        normal = bu.outputs["Normal"]
    if normal is not None:
        nt.links.new(normal, p.inputs["Normal"])
    return m


MAT = {}


def make_materials():
    MAT.update({
        "case": principled("PLA case", CASE, 0.55, bevel=0.5, bump=0.25, spec=0.4),
        "alpha": principled("PBT keycap", CAP_ALPHA, 0.5, bevel=0.6, bump=0.35, spec=0.45),
        "mod": principled("PBT keycap dark", CAP_MOD, 0.5, bevel=0.6, bump=0.35, spec=0.45),
        "accent": principled("PBT keycap accent", ACCENT, 0.5, bevel=0.6, bump=0.35, spec=0.45),
        "legend": principled("Legend", LEGEND, 0.6),
        "legend light": principled("Legend light", CAP_ALPHA, 0.6),
        "housing": principled("Switch housing, milky", "#e7e2d6", 0.35, bevel=0.2),
        "stem": principled("Switch stem", ACCENT, 0.4),
        "gold": principled("Gold contacts", "#d8b36a", 0.25, metal=1.0),
        "plate": principled("FR4 plate, black mask", "#141414", 0.3, coat=0.3, bevel=0.2),
        "steel": principled("Steel shell", "#c9cccf", 0.28, metal=1.0),
        "nylon": principled("Nylon housing", "#ece6d6", 0.5),
    })


# ---------------------------------------------------------------------------------------------------- import
def link(obj, collection):
    collection.objects.link(obj)
    return obj


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


def import_stl(path, name):
    bpy.ops.wm.stl_import(filepath=str(path), global_scale=MM)
    obj = bpy.context.selected_objects[0]
    obj.name = obj.data.name = name
    obj.data.transform(obj.matrix_basis)  # the importer scales the object; keep the scale in the mesh (shared)
    obj.matrix_basis = Matrix.Identity(4)
    for c in obj.users_collection:
        c.objects.unlink(obj)
    # smooth by angle: flat faces stay flat, curved ones (meshed in facets) look smooth
    obj.data.shade_smooth()
    obj.data.set_sharp_from_angle(angle=math.radians(35.0))
    return obj


def import_glb(path, root_name, matrix, coll):
    """KiCad GLB (metres, slab x/y, z = height above the board bottom) under one empty."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.data.objects if o not in before]
    root = link(bpy.data.objects.new(root_name, None), coll)
    root.matrix_world = matrix
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        coll.objects.link(o)
        if o.parent is None:
            o.parent = root
    return root, [o for o in new if o.type == "MESH"]


def tune_kicad_materials(meshes):
    """KiCad's GLB materials, made to look like a real board: glossy JLCPCB-green mask, white silkscreen, tin (HASL)
    pads, a darker FR4 core; part bodies come out of KiCad as rough metal, so the coloured or dark ones become
    plastic and the rest stay metal (pins, shields)."""
    done = set()
    for o in meshes:
        for m in o.data.materials:
            if m is None or m.name in done or not m.node_tree:
                continue
            done.add(m.name)
            p = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if p is None:
                continue
            col = list(p.inputs["Base Color"].default_value)
            alpha, metal = p.inputs["Alpha"].default_value, p.inputs["Metallic"].default_value
            rough = p.inputs["Roughness"].default_value
            if alpha < 0.9 and col[1] > col[0]:  # solder mask
                p.inputs["Base Color"].default_value = srgb("#0d5a2b")
                p.inputs["Alpha"].default_value = 0.9
                p.inputs["Roughness"].default_value = 0.3
                p.inputs["Coat Weight"].default_value = 0.15
            elif alpha < 1.0 and min(col[:3]) > 0.9:  # silkscreen
                p.inputs["Alpha"].default_value = 1.0
                p.inputs["Roughness"].default_value = 0.6
            elif metal > 0.5 and rough < 0.5 and col[2] < 0.1 and col[0] > 0.5:  # copper layers (gold in KiCad)
                p.inputs["Base Color"].default_value = srgb("#c98b5a")
                p.inputs["Roughness"].default_value = 0.35
            elif metal > 0.5 and rough < 0.5:  # pads: lead-free HASL
                p.inputs["Base Color"].default_value = srgb("#d4d6d8")
                p.inputs["Roughness"].default_value = 0.22
            elif metal < 0.5 and alpha > 0.95 and rough >= 0.8:  # board core seen at the edges and in the holes
                p.inputs["Base Color"].default_value = srgb("#7d7650")
                p.inputs["Roughness"].default_value = 0.7
            elif metal > 0.5:  # 3D models of the parts
                r, g, bl = col[:3]
                gold = r > g > bl and r > 0.4 and r - bl > 0.25
                grey = max(col[:3]) - min(col[:3]) < 0.12 and 0.15 < max(col[:3]) < 0.75
                if gold or grey:  # plated pins, contacts, shields
                    p.inputs["Roughness"].default_value = 0.3
                else:  # white, dark or coloured: plastic bodies
                    p.inputs["Metallic"].default_value = 0.0
                    p.inputs["Roughness"].default_value = 0.45
    # hotswap sockets: the kiswitch STEP model is white, real Kailh sockets are black nylon
    body = principled("Kailh socket body", "#1d1d1f", 0.5)
    for o in meshes:
        ref = o.parent.name if o.parent else ""
        if re.fullmatch(r"SW\d+", ref) and ref not in ("SW101", "SW102"):
            for slot in o.material_slots:
                p = slot.material and next((n for n in slot.material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
                if p and min(p.inputs["Base Color"].default_value[:3]) > 0.7:
                    slot.material = body


def top_face(mesh):
    """Extent of the keycap's top (the faces looking up): x0, x1, y0, y1 and the highest z, in metres."""
    up = [v for p in mesh.polygons if p.normal.z > 0.6 for v in (mesh.vertices[i].co for i in p.vertices)]
    xs, ys = [v.x for v in up], [v.y for v in up]
    return min(xs), max(xs), min(ys), max(ys), max(v.co.z for v in mesh.vertices)


def legend(key, cap, top, material):
    """Legend printed on the keycap: one glyph top-left, words bottom-left (as on the M0110), projected onto the
    dish."""
    text = {"space": ""}.get(key["label"], key["label"])
    if not text:
        return None
    single = len(text) == 1
    cu = bpy.data.curves.new("legend " + text, "FONT")
    cu.body = text
    cu.size = (3.4 if single else 2.2) * MM
    cu.align_x, cu.align_y = "LEFT", ("TOP" if single else "BOTTOM")
    x0, x1, y0, y1, z = top
    x, y = x0 + 1.6 * MM, (y1 - 1.6 * MM) if single else (y0 + 1.5 * MM)
    tmp = bpy.data.objects.new("tmp", cu)
    bpy.context.scene.collection.objects.link(tmp)
    dg = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(cu)
    if not mesh.vertices:  # glyph missing from the font
        return None
    mesh.materials.append(material)
    obj = bpy.data.objects.new("legend " + text, mesh)
    obj.matrix_world = cap.matrix_world @ Matrix.Translation((x, y, z + 1.0 * MM))
    sw = obj.modifiers.new("onto the dish", "SHRINKWRAP")
    sw.target, sw.wrap_method = cap, "PROJECT"
    sw.use_negative_direction, sw.use_positive_direction = True, False
    sw.use_project_z, sw.offset = True, 0.04 * MM
    return obj


SWITCH_LOOK = {"housing-bottom": "housing", "housing-top": "housing", "stem": "stem", "metal": "gold",
               "spring": "steel"}


def build():
    groups = {g: collection(g) for g in ("bottom", "pcb", "plate", "top", "caps")}
    for name in S["case"]:
        obj = import_stl(SRC / (name + ".stl"), name)
        obj.data.materials.append(MAT["case"])
        link(obj, groups["top" if "top" in name else "bottom"])
    pcb, pcb_meshes = import_glb(SRC / "pcb.glb", "PCB", slab(0, 0, S["pcb_bot"]), groups["pcb"])
    tune_kicad_materials(pcb_meshes)
    for s in S.get("stand_ins", []):  # parts without a KiCad 3D model: blocks on their outline, under the board
        x0, y0, x1, y1 = s["box"]
        o = link(block(s["ref"], (x1 - x0, y1 - y0, s["h"]), MAT[s["look"]], 0.25), groups["pcb"])
        o.parent = pcb
        o.matrix_parent_inverse = Matrix.Identity(4)
        o.matrix_basis = Matrix.Translation(((x0 + x1) / 2 * MM, (y0 + y1) / 2 * MM, -s["h"] / 2 * MM))
    plate, plate_meshes = import_glb(SRC / "plate.glb", "plate", slab(0, 0, 0), groups["plate"])
    for o in plate_meshes:  # black FR4 plate, whatever colour KiCad gave the board
        o.data.materials.clear()
        o.data.materials.append(MAT["plate"])
    bpy.context.view_layer.update()
    top = max((o.matrix_world @ Vector(c)).dot(NORMAL) for o in plate_meshes for c in o.bound_box)
    want = (slab(0, 0, S["plate_top"]).to_translation()).dot(NORMAL)
    plate.matrix_world = Matrix.Translation(NORMAL * (want - top)) @ plate.matrix_world

    meshes = MESHES
    for part in S["switch"]:
        meshes["switch-" + part] = import_stl(SRC / ("switch-%s.stl" % part), "switch " + part).data
        meshes["switch-" + part].materials.append(MAT[SWITCH_LOOK[part]])
    for name in sorted({k["mesh"] for k in S["keys"]}):
        meshes[name] = import_stl(SRC / (name + ".stl"), name).data
    for k in S["keys"]:
        for part in S["switch"]:  # the switch model's origin is the PCB top
            sw = link(bpy.data.objects.new("switch " + part, meshes["switch-" + part]), groups["plate"])
            sw.matrix_world = slab(k["x"], k["y"], S["pcb_bot"] + S["pcb_t"])
        add_keycap(k, slab(k["x"], k["y"], S["cap_z"]), groups["caps"])
    return groups


MESHES = {}  # shared meshes: keycaps, switch parts (render_desk.py reuses them for the loose parts)


def add_keycap(k, matrix, coll):
    """Keycap of key k (an entry of scene.json keys) with its legend; colour from accent / modifier."""
    mesh = MESHES[k["mesh"]]
    cap = link(bpy.data.objects.new("keycap " + k["label"], mesh), coll)
    cap.matrix_world = matrix
    if not mesh.materials:
        mesh.materials.append(MAT["alpha"])
    look = "accent" if k.get("accent") else "mod" if k.get("modifier") else "alpha"
    if look != "alpha":  # per-object colour on a shared mesh
        cap.material_slots[0].link = "OBJECT"
        cap.material_slots[0].material = MAT[look]
    if mesh.name not in TOPS:
        TOPS[mesh.name] = top_face(mesh)
    lg = legend(k, cap, TOPS[mesh.name], MAT["legend light" if look == "accent" else "legend"])
    if lg:
        link(lg, coll)
    return cap


TOPS = {}


def block(name, size, material, radius):
    """Box centred on the origin (size in mm) with rounded edges."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=[v * MM for v in size], verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material)
    o = bpy.data.objects.new(name, me)
    bevel = o.modifiers.new("round", "BEVEL")
    bevel.width, bevel.segments = min(radius, min(size) / 3) * MM, 3
    return o


# ----------------------------------------------------------------------------------------- studio and camera
def render_settings():
    """Cycles on every GPU/CPU device, denoised, AgX colour management."""
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for dev in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        try:
            prefs.compute_device_type = dev
            prefs.get_devices()
            if any(d.type == dev for d in prefs.devices):
                for d in prefs.devices:  # GPU + CPU: on an M4 this is faster than the GPU alone
                    d.use = True
                sc.cycles.device = "GPU"
                break
        except TypeError:
            continue
    sc.cycles.samples = SAMPLES
    sc.cycles.adaptive_threshold = 0.01
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.max_bounces = 8
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    for look in ("AgX - Medium High Contrast", "Medium High Contrast"):
        try:
            sc.view_settings.look = look
            break
        except TypeError:
            continue
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"


def studio():
    """Product-shot studio: seamless backdrop (shadow-catcher floor), HDRI reflections, key / fill / rim lights."""
    sc = bpy.context.scene
    render_settings()

    # world: studio HDRI for reflections and ambient light, a flat backdrop colour seen by the camera
    w = bpy.data.worlds.new("studio")
    sc.world = w
    w.use_nodes = True
    nt = w.node_tree
    bg = nt.nodes["Background"]
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    hdri = BLENDER_DATA / "studiolights/world/interior.exr"
    if hdri.exists():
        env.image = bpy.data.images.load(str(hdri))
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.35
    flat = nt.nodes.new("ShaderNodeBackground")
    flat.inputs["Color"].default_value = srgb(BACKDROP)
    flat.inputs["Strength"].default_value = BACKDROP_GAIN  # AgX shows 1.0 as a mid grey
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(bg.outputs["Background"], mix.inputs[1])
    nt.links.new(flat.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], nt.nodes["World Output"].inputs["Surface"])

    # floor: catches the shadows only, so every view sits on the same seamless backdrop
    bpy.ops.mesh.primitive_plane_add(size=6.0)
    floor = bpy.context.active_object
    floor.name = "floor"
    floor.is_shadow_catcher = True

    def area(name, loc, power, size, color=(1, 1, 1)):
        d = bpy.data.lights.new(name, "AREA")
        d.energy, d.size, d.color = power, size, color
        o = bpy.data.objects.new(name, d)
        sc.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector((0.17, 0.06, 0.02)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return o

    area("key", (-0.55, -0.75, 0.95), KEY_W, 0.9, (1.0, 0.97, 0.93))
    area("fill", (0.95, -0.45, 0.55), KEY_W * 0.3, 1.2, (0.93, 0.96, 1.0))
    area("rim", (0.25, 0.85, 0.6), KEY_W * 0.6, 0.7)
    return floor


def bbox_points(objs):
    pts = []
    for o in objs:
        if o.type in ("MESH", "FONT") and not o.hide_render:
            pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    return pts


def frame(cam, pts, direction, margin=0.06):
    """Aim the camera along -direction at the points and back off until they fill the frame."""
    sc = bpy.context.scene
    center = sum(pts, Vector()) / len(pts)
    direction = Vector(direction).normalized()
    cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    cam.data.shift_x = cam.data.shift_y = 0.0
    d = 1.0
    for _ in range(12):
        if cam.data.type == "ORTHO":
            cam.location = center + direction * 2.0
        else:
            cam.location = center + direction * d
        bpy.context.view_layer.update()
        uv = [world_to_camera_view(sc, cam, p) for p in pts]
        xs, ys = [p.x for p in uv], [p.y for p in uv]
        need = max((max(xs) - min(xs)) / (1 - 2 * margin), (max(ys) - min(ys)) / (1 - 2 * margin))
        if cam.data.type == "ORTHO":
            cam.data.ortho_scale *= need
        else:
            d *= need
        if abs(need - 1) < 0.002:
            break
    rx, ry = sc.render.resolution_x, sc.render.resolution_y
    big = max(rx, ry)
    cam.data.shift_x = ((max(xs) + min(xs)) / 2 - 0.5) * rx / big
    cam.data.shift_y = ((max(ys) + min(ys)) / 2 - 0.5) * ry / big
    return center, d


VIEWS = {
    # picture: camera direction (from the subject towards the camera), lens in mm or "ortho", resolution, f-stop (0: no
    # depth of field), pose: "desk" as assembled, "flipped" upside down, "exploded", "pcb" the bare PCB lying flat,
    # "pcb-flipped" the bare PCB with its components up
    "case-front": ((-0.42, -1.0, 0.62), 85, (2560, 1440), 11.0, "desk"),
    "case-back": ((0.55, 1.0, 0.5), 85, (2560, 1440), 11.0, "desk"),
    "case-side": ((-1.0, 0.0, 0.04), "ortho", (2560, 960), 0, "desk"),
    "case-top": (tuple(NORMAL), "ortho", (2880, 1200), 0, "desk"),
    "case-bottom": ((-0.35, -0.9, 0.75), 85, (2560, 1440), 0, "flipped"),
    "case-exploded": ((-0.5, -1.0, 0.55), 70, (2560, 1920), 0, "exploded"),
    "pcb-top": ((-0.2, -0.75, 1.0), 85, (2560, 1200), 16.0, "pcb"),
    "pcb-bottom": ((-0.2, -0.75, 1.0), 85, (2560, 1200), 16.0, "pcb-flipped"),
}
EXPLODE = {"bottom": 0, "pcb": 52, "plate": 82, "top": 112, "caps": 150}  # mm along the deck normal


def turn_over(objs, roots):
    """Upside down about the subject's own centre (rotation about the long axis would swap front and back)."""
    pts = bbox_points(objs)
    c0 = sum(pts, Vector()) / len(pts)
    flip = Matrix.Translation(c0) @ Matrix.Rotation(math.pi, 4, "Y") @ Matrix.Translation(-c0)
    for o in roots:
        o.matrix_world = flip @ o.matrix_world


def render_views(groups):
    sc = bpy.context.scene
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    everything = [o for g in groups.values() for o in g.all_objects]
    roots = [o for o in everything if o.parent is None]
    home = {o: o.matrix_world.copy() for o in roots}
    IMG.mkdir(parents=True, exist_ok=True)
    for name, (direction, lens, res, fstop, pose) in VIEWS.items():
        if ONLY and name not in ONLY:
            continue
        bare_pcb = pose.startswith("pcb")
        for g, coll in groups.items():  # the bare PCB views show the PCB alone
            for o in list(coll.all_objects):
                o.hide_render = bare_pcb and g != "pcb"
        for o in roots:
            o.matrix_world = home[o]
            if bare_pcb and o.name == "PCB":
                o.matrix_world = Matrix.Identity(4)  # flat on the desk, in KiCad's orientation
            if pose == "exploded":
                g = next(g for g, coll in groups.items() if o.name in coll.all_objects)
                o.matrix_world = Matrix.Translation(NORMAL * EXPLODE[g] * MM) @ home[o]
        bpy.context.view_layer.update()
        if pose in ("flipped", "pcb-flipped"):
            turn_over(everything, roots)
        bpy.context.view_layer.update()
        # rest on the desk: the lowest point (case base, keycaps when flipped, PCB parts) touches the floor
        low = min(p.z for p in bbox_points(everything))
        for o in roots:
            o.matrix_world = Matrix.Translation((0, 0, -low)) @ o.matrix_world
        bpy.context.view_layer.update()
        sc.render.resolution_x, sc.render.resolution_y = res
        sc.render.resolution_percentage = SCALE
        if lens == "ortho":
            cam.data.type = "ORTHO"
            cam.data.ortho_scale = 0.4
        else:
            cam.data.type = "PERSP"
            cam.data.lens = lens
        center, _ = frame(cam, bbox_points(everything), direction)
        cam.data.dof.use_dof = bool(fstop)
        if fstop:
            cam.data.dof.focus_distance = (cam.location - center).length
            cam.data.dof.aperture_fstop = fstop
        cam.data.clip_start, cam.data.clip_end = 0.01, 20.0
        out = IMG / (name + ".png")
        sc.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        print("wrote", out.relative_to(BUILD.parent.parent))
    for o in everything:
        o.hide_render = False
    for o in roots:
        o.matrix_world = home[o]


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    make_materials()
    groups = build()
    studio()
    bpy.context.view_layer.update()
    bpy.ops.wm.save_as_mainfile(filepath=str(SRC / "keyboard.blend"))
    render_views(groups)


if __name__ == "__main__":
    main()
