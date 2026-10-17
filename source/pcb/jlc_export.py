"""Writes the JLCPCB assembly files (BOM + CPL) for the routed PCB.

    $KPY pcb/jlc_export.py build/pcb/lira.kicad_pcb build/jlcpcb/

Only footprints with an "LCSC" field are assembled. Coordinates use the board's aux origin (bottom-left corner of
the board, set by gen_pcb.py) with Y up, exactly like the gerbers exported with --use-drill-file-origin.

Rotations and positions are given the way JLCPCB reads them, which is not KiCad's:
  * JLCPCB places each part with its own (LCSC / EasyEDA) footprint. Where that footprint is drawn turned from
    KiCad's, DELTA gives the angle that turns the LCSC footprint into the KiCad one (measured by fitting the pads of
    the two footprints, cross-checked with the community rotation tables of the KiCad JLCPCB plugins).
  * A bottom-side part is seen from below, without KiCad's mirroring: JLCPCB's angle is 180 - KiCad's + DELTA (the
    convention of KiKit's and Bouni's JLCPCB exports and of KiBot's "mirror_bottom").
  * Where the LCSC footprint's origin is not KiCad's (connectors), ORIGIN gives the LCSC origin in the KiCad library
    footprint's own coordinates, and the CPL point is moved there.
Hotswap sockets: the switch footprint is a top-side footprint whose socket pads are on the bottom copper, so the
socket is reported as a Bottom part placed at the midpoint of its two pads (the LCSC socket footprint's origin); the
socket is symmetric under a half turn, so its angle is the switch's.
After uploading, still check JLCPCB's placement preview (guide, section 1): the bottom-side convention has changed
before. The test is a key diode: its cathode band must lie on the pad under the silkscreen bar.
"""
import csv
import math
import sys
from collections import OrderedDict
from pathlib import Path

import pcbnew

# LCSC code -> angle (degrees) that turns the LCSC footprint into KiCad's; 0 for the rest
DELTA = {
    "C97521": 270,  # W25Q128JV, SOIC-8 208 mil
    "C51118": 270,  # AP2112K, SOT-23-5
    "C2887324": 180,  # TPS7A0233, SOT-23-5 (its LCSC footprint is not drawn like the AP2112K's)
    "C8545": 180,  # 2N7002, SOT-23
    "C424093": 270,  # MCP73831, SOT-23-5
    "C7519": 270,  # USBLC6-2SC6, SOT-23-6
    "C5373042": 270,  # CH334P, QFN-16
    "C371347": 270,  # CM108B, LQFP-48
    "C10487": 180,  # SI2301, SOT-23
    "C2149796": 180,  # TPS22919, SC-70-6
    "C95562": 90,  # PJ-320D-4A headset jack
    # 0 (same as KiCad's, checked): C193402 SMF5.0A SOD-123FL
}
# KiCad footprint name -> origin of the LCSC footprint, in the KiCad library footprint's coordinates (mm)
ORIGIN = {
    "USB_C_Receptacle_HRO_TYPE-C-31-M-12": (0.0, -1.41),
    "Jack_3.5mm_KoreanHropartsElec_PJ-320D-4A_Horizontal": (0.85, 0.0),
    "SW_SPDT_CK_JS102011SAQN": (0.0, -2.75),
}


def rotate(x, y, deg):
    """Turn (x, y) by deg counter-clockwise as seen on screen (KiCad's y points down)."""
    r = math.radians(deg)
    return x * math.cos(r) + y * math.sin(r), -x * math.sin(r) + y * math.cos(r)


def main(pcb_path, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    b = pcbnew.LoadBoard(str(pcb_path))
    origin = b.GetDesignSettings().GetAuxOrigin()
    ox, oy = pcbnew.ToMM(origin.x), pcbnew.ToMM(origin.y)
    bom = OrderedDict()
    cpl = []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        if not fp.HasField("LCSC") or fp.IsExcludedFromBOM():
            continue
        lcsc = fp.GetFieldText("LCSC")
        ref = fp.GetReference()
        is_switch = "Hotswap" in fp.GetFPIDAsString()
        if is_switch:
            pads = [p for p in fp.Pads() if p.GetNumber() in ("1", "2")]
            x = sum(pcbnew.ToMM(p.GetPosition().x) for p in pads) / 2
            y = sum(pcbnew.ToMM(p.GetPosition().y) for p in pads) / 2
            layer, rot = "Bottom", fp.GetOrientationDegrees()
            comment, footprint = "MX hot-swap socket (Kailh CPG151101S11 type)", "Kailh_MX_Hotswap"
            ref = ref.replace("SW", "S")  # the socket, not the switch
        else:
            pos = fp.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            theta = fp.GetOrientationDegrees()
            name = fp.GetFPID().GetLibItemName().wx_str()
            if name in ORIGIN:
                tx, ty = ORIGIN[name]
                dx, dy = rotate(tx, -ty if fp.IsFlipped() else ty, theta)
                x, y = x + dx, y + dy
            layer = "Bottom" if fp.IsFlipped() else "Top"
            rot = (180 - theta if fp.IsFlipped() else theta) + DELTA.get(lcsc, 0)
            comment, footprint = fp.GetValue(), fp.GetFPID().GetLibItemName().wx_str()
        cpl.append([ref, "%.3fmm" % (x - ox), "%.3fmm" % (oy - y), layer, "%g" % (round(rot) % 360)])
        e = bom.setdefault(lcsc, {"comment": comment, "footprint": footprint, "refs": []})
        e["refs"].append(ref)
    with open(out_dir / "bom.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for lcsc, e in bom.items():
            w.writerow([e["comment"], ",".join(e["refs"]), e["footprint"], lcsc])
    with open(out_dir / "cpl.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(cpl)
    print("bom: %d lines, %d parts; cpl: %d placements" % (len(bom), sum(len(e["refs"]) for e in bom.values()),
                                                           len(cpl)))
    for lcsc, e in bom.items():
        print("  %-10s x%-3d %s" % (lcsc, len(e["refs"]), e["comment"]))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
