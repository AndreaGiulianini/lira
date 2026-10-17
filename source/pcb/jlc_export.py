"""Writes the JLCPCB assembly files (BOM + CPL) for the routed PCB.

    $KPY pcb/jlc_export.py build/pcb/lira.kicad_pcb build/jlcpcb/

Only footprints with an "LCSC" field are assembled. Coordinates use the board's aux origin (bottom-left corner of
the board, set by gen_pcb.py) with Y up, exactly like the gerbers exported with --use-drill-file-origin.

Hotswap sockets: the switch footprint is a top-side footprint whose socket pads are on the bottom copper, so the
socket is reported as a Bottom part placed at the midpoint of its two pads.
After uploading, ALWAYS check JLCPCB's placement preview: part rotations depend on JLC's own footprint
orientation and may need a 90/180 degree fix (diodes: the stripe = cathode = pad 1).
"""
import csv
import sys
from collections import OrderedDict
from pathlib import Path

import pcbnew

ROTATION_FIX = {}  # LCSC code -> degrees to add, filled in after checking JLC's preview


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
            comment, footprint = "Kailh MX hotswap socket CPG151101S11", "Kailh_MX_Hotswap"
            ref = ref.replace("SW", "S")  # the socket, not the switch
        else:
            pos = fp.GetPosition()
            x, y = pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)
            layer = "Bottom" if fp.IsFlipped() else "Top"
            rot = fp.GetOrientationDegrees()
            comment, footprint = fp.GetValue(), fp.GetFPID().GetLibItemName().wx_str()
        rot = (rot + ROTATION_FIX.get(lcsc, 0)) % 360
        cpl.append([ref, "%.3fmm" % (x - ox), "%.3fmm" % (oy - y), layer, "%g" % rot])
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
