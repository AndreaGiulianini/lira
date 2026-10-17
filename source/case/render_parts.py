"""Everything case/render.py (Blender) needs to render the assembled keyboard, in build/render/:

    KCLI=<kicad-cli> .venv/bin/python case/render_parts.py      (run by `make renders`)

  * pcb.glb, plate.glb - the routed PCB with its 3D models and the plate, exported by KiCad in the slab frame
  * case-*.stl         - the printed pieces, meshed finer than the print STLs (smooth chamfers and corners)
  * keycap-*.stl       - Cherry-profile keycaps (sculpted rows, cylindrical dish) made with KeyV2 (tools/KeyV2, run
                         by OpenSCAD), one per row and size
  * switch-*.stl       - a Cherry MX switch (kiswitch STEP model in lib/3dmodels), one mesh per material
  * scene.json         - slab transform, heights, and where every key and the battery go
  * deskmat.svg/.png   - the desk mat's print for case/render_desk.py (case/deskmat.py)
"""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

from build123d import Compound, export_stl, import_step

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import deskmat  # noqa: E402
import gen_case as C  # noqa: E402
import layout as L  # noqa: E402

from paths import BUILD  # noqa: E402

OUT = BUILD / "render"
U = L.U
KCLI = os.environ.get("KCLI", str(Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"))
OPENSCAD = os.environ.get("OPENSCAD", "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD")
KEYV2 = HERE.parent / "tools/KeyV2"
MX_STEP = HERE.parent / "lib/3dmodels/com_github_perigoso_keyswitch-kicad-library/3d-library.3dshapes/SW_Cherry_MX_PCB.stp"
CHERRY_ROW = {0: 2, 1: 3, 2: 4, 3: 4}  # layout row -> Cherry row (a 40%: Q row R2, home row R3, the rest R4)
CAP_Z = 6.8  # keycap rim above the plate top at rest (MX top housing 6.2 mm above the plate)
# bottom-side parts whose 3D model KiCad 10 does not ship: footprint name -> height below the PCB (mm, datasheet
# values as in case/check_fit.py), look; render.py draws them as rounded blocks on their Fab outline
STAND_INS = {"USB_C_Receptacle_HRO": (3.26, "steel"), "JST_PH_S2B-PH-SM4": (5.5, "nylon"),
             "JS102011SAQN": (3.5, "steel"), "SW-SMD_4P-L5.1-W5.1": (1.5, "steel")}
MODIFIERS = {"esc", "tab", "shift", "return", "enter", "delete", "fn", "option", "⌘", "space"}
ACCENTS = {"esc", "return", "enter"}  # accent-coloured keycaps
HOMING = {"F", "J", "5"}  # keycaps with a homing bump
# the solids of the kiswitch MX model (by index; volumes checked): what each one is and its material
MX_SOLIDS = {0: ("housing-bottom", 478.6), 1: ("housing-top", 294.8), 2: ("stem", 137.6), 6: ("stem", 63.6),
             3: ("metal", 14.4), 4: ("metal", 8.0), 5: ("spring", 6.3)}


def keycap(row, w, h, bump, path):
    """Cherry-profile keycap from KeyV2 (OpenSCAD, manifold backend): rim centred on the origin, z up, +y back.
    Skipped when the .scad it would run is unchanged and the STL exists."""
    scad = (
        'include <%s/includes.scad>\n'
        '$support_type = "disable"; $stem_support_type = "disable";\n'
        '$key_shape_type = "sculpted_square"; $height_slices = 24; $shape_facets = 64; $fn = 160;\n'
        '$key_bump = %s;\n'
        'cherry_row(%d) u(%g) uh(%g) key();\n' % (KEYV2, "true" if bump else "false", row, w, h))
    src = path.with_suffix(".scad")
    if path.exists() and src.exists() and src.read_text() == scad:
        return
    src.write_text(scad)
    subprocess.run([OPENSCAD, "--backend=manifold", "--export-format", "binstl", "-o", str(path), str(src)],
                   check=True, capture_output=True)


def switch_parts():
    """The MX switch model split by material: housing-bottom, housing-top, stem, metal, spring (z = 0: PCB top)."""
    solids = import_step(str(MX_STEP)).solids()
    groups = {}
    for i, (name, volume) in MX_SOLIDS.items():
        assert abs(solids[i].volume - volume) < 1.0, "unexpected MX model: solid %d" % i
        groups.setdefault(name, []).append(solids[i])
    for name, parts in groups.items():
        export_stl(Compound(children=parts), str(OUT / ("switch-%s.stl" % name)), tolerance=0.01, angular_tolerance=0.1)
    return sorted(groups)


def export_glb(src, dst, origin, extra, footprints=()):
    # KICAD6_3RD_PARTY: the kiswitch footprints look for their 3D models (hotswap sockets, stabilizers) there; the
    # lib/... models (module, headset jack) are found from source/, where make runs this
    cmd = [KCLI, "pcb", "export", "glb", "-f", "--subst-models", "--user-origin", "%gx%gmm" % tuple(origin),
           "-D", "KICAD6_3RD_PARTY=%s" % (HERE.parent / "lib"), *extra, "-o", str(dst), str(src)]
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    missing = set(re.findall(r"Could not add 3D model for (\S+?)\.", out.stdout + out.stderr))
    stand_in = {fp["ref"] for fp in footprints if any(key in fp["fp"] for key in STAND_INS)}
    if missing - stand_in:  # a part would be missing from the renders without anyone noticing
        raise SystemExit("no 3D model found for %s" % ", ".join(sorted(missing - stand_in)))
    print("wrote", dst.relative_to(BUILD))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    parts = json.loads((BUILD / "pcb/parts.json").read_text())
    origin = parts["kicad_origin"]
    export_glb(BUILD / "pcb/lira.kicad_pcb", OUT / "pcb.glb", origin,
               ["--include-tracks", "--include-pads", "--include-zones", "--include-silkscreen",
                "--include-soldermask", "--cut-vias-in-body"], parts["footprints"])
    export_glb(BUILD / "plate/plate.kicad_pcb", OUT / "plate.glb", origin, ["--board-only", "--include-soldermask"])

    case_parts = []
    for step in sorted((BUILD / "case").glob("case-*.step")):
        export_stl(import_step(str(step)), str(OUT / (step.stem + ".stl")), tolerance=0.004, angular_tolerance=0.05)
        case_parts.append(step.stem)
    caps = sorted({(CHERRY_ROW[k.row], k.w, k.h, k.label in HOMING) for k in L.KEYS})
    for row, w, h, bump in caps:
        keycap(row, w, h, bump, OUT / cap_name(row, w, h, bump))
    switch = switch_parts()

    keys = []
    for k in L.KEYS:
        row = CHERRY_ROW[k.row]
        keys.append({"x": k.cx * U, "y": C.KD - k.cy * U, "w": k.w, "h": k.h, "label": k.label,
                     "mesh": cap_name(row, k.w, k.h, k.label in HOMING)[:-4], "accent": k.label in ACCENTS,
                     "modifier": k.label in MODIFIERS or k.block == "numpad" and not k.label.isdigit()})
    stand_ins = []
    for fp in parts["footprints"]:
        for key, (h, look) in STAND_INS.items():
            if key in fp["fp"] and fp["side"] == "B":
                stand_ins.append({"ref": fp["ref"], "box": fp["fab"] or fp["courtyard"], "h": h, "look": look})
    bx, by = C.POCKET_AT
    scene = {
        "tilt": C.TILT, "ty": C.TY, "tz": C.TZ, "plate_top": C.PLATE_TOP, "pcb_bot": C.PCB_BOT,
        "pcb_t": C.PCB_T, "floor_top": C.FLOOR_TOP, "cap_z": C.PLATE_TOP + CAP_Z, "switch": switch,
        "key_area": [C.KW, C.KD], "case": case_parts, "keys": keys,
        # a 603450 cell lying in its pocket under the numpad (slab frame: corner, size)
        "battery": {"at": [bx + 1.5, by + 1.0, C.FLOOR_TOP - C.POCKET[2] + 0.3], "size": [52.0, 34.5, 6.2]},
        "extent": {"x": [C.X_L, C.X_R], "y": [C.Y_F, C.Y_B]}, "stand_ins": stand_ins,
    }
    (OUT / "scene.json").write_text(json.dumps(scene, indent=1, ensure_ascii=False))
    # the desk mat's drawing (case/deskmat.py), rasterised by headless Chrome at 6 px/mm
    iface = json.loads((BUILD / "pcb/interface.json").read_text())
    (OUT / "deskmat.svg").write_text(deskmat.svg(OUT, (C.X_R - C.X_L, C.DEPTH_W), iface))  # footprint from above
    subprocess.run([str(HERE.parent / "render.sh"), str(OUT / "deskmat.svg"), str(OUT / "deskmat.png"), "2700", "1200"],
                   check=True)
    print("wrote render/scene.json: %d keycaps (%d shapes), %d case pieces" % (len(keys), len(caps), len(case_parts)))


def cap_name(row, w, h, bump):
    return "keycap-r%d-%gx%g%s.stl" % (row, w, h, "-bump" if bump else "")


if __name__ == "__main__":
    main()
