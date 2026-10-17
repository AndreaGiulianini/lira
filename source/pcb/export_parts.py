"""Exports the final PCB and plate geometry for the case test fit (case/check_fit.py).

Run with KiCad's Python (make case). Output: build/pcb/parts.json, in case coordinates (slab frame: x right,
y towards the back, origin at the front-left corner of the key area; same transform as interface.json):
  * every footprint: side, position, rotation, body outline (Fab layer, else courtyard) and pads
  * the board outline and its holes (mounting holes, case bolts, switch and stabilizer holes)
  * the plate: outer outline (bbox and polygon: ears and tabs of the top mount) and every opening (empty if the
    plate has no closed outline)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import pcbnew  # noqa: E402

import layout as L  # noqa: E402
from gen_pcb import KX, KY, U  # noqa: E402
from paths import BUILD  # noqa: E402

Y0 = KY + L.HEIGHT * U


def xy(x, y):
    """KiCad mm -> case slab frame."""
    return [round(x - KX, 3), round(Y0 - y, 3)]


def to_mm(v):
    return pcbnew.ToMM(v)


def bbox(box):
    """KiCad BOX2I -> [x0, y0, x1, y1] in the case frame."""
    a = xy(to_mm(box.GetLeft()), to_mm(box.GetBottom()))
    b = xy(to_mm(box.GetRight()), to_mm(box.GetTop()))
    return [a[0], a[1], b[0], b[1]]


def layer_bbox(fp, layers):
    box = None
    for item in fp.GraphicalItems():
        if item.GetLayer() in layers and "TEXT" not in item.GetClass().upper():
            b = item.GetBoundingBox()
            if box is None:
                box = b
            else:
                box.Merge(b)
    return bbox(box) if box is not None else None


def footprints(board):
    out = []
    for fp in board.GetFootprints():
        bottom = fp.GetLayer() == pcbnew.B_Cu
        fab = layer_bbox(fp, (pcbnew.B_Fab,) if bottom else (pcbnew.F_Fab,))
        crt = layer_bbox(fp, (pcbnew.B_CrtYd,) if bottom else (pcbnew.F_CrtYd,))
        pads = []
        for p in fp.Pads():
            pos = p.GetPosition()
            drill = p.GetDrillSize()
            pads.append({"num": p.GetNumber(), "xy": xy(to_mm(pos.x), to_mm(pos.y)),
                         "size": [round(to_mm(p.GetSize().x), 3), round(to_mm(p.GetSize().y), 3)],
                         "drill": round(to_mm(min(drill.x, drill.y)), 3) if drill.x > 0 else 0.0,
                         "bbox": bbox(p.GetBoundingBox())})
        pos = fp.GetPosition()
        out.append({"ref": fp.GetReference(), "fp": fp.GetFPID().GetLibItemName().wx_str(),
                    "side": "B" if bottom else "F", "xy": xy(to_mm(pos.x), to_mm(pos.y)),
                    "rot": round(fp.GetOrientationDegrees(), 2), "fab": fab, "courtyard": crt, "pads": pads})
    return out


def outlines(board):
    """Outer outline bbox and the bbox of every hole of the Edge.Cuts polygon (None if malformed)."""
    polys = pcbnew.SHAPE_POLY_SET()
    if not board.GetBoardPolygonOutlines(polys, False) or polys.OutlineCount() == 0:
        return None
    out = []
    for i in range(polys.OutlineCount()):
        chain = polys.Outline(i)
        outer = chain.BBox()
        holes = [polys.Hole(i, h).BBox() for h in range(polys.HoleCount(i))]
        pts = [xy(to_mm(chain.CPoint(k).x), to_mm(chain.CPoint(k).y)) for k in range(chain.PointCount())]
        out.append({"outer": bbox(outer), "outline": pts, "holes": [bbox(h) for h in holes]})
    return out


def main():
    plate_file = BUILD / "plate/plate.kicad_pcb"
    plate = outlines(pcbnew.LoadBoard(str(plate_file))) if plate_file.exists() else None
    pcb = pcbnew.LoadBoard(str(BUILD / "pcb/lira.kicad_pcb"))
    # kicad_origin: the KiCad point that is the slab-frame origin (case/render.py places KiCad's 3D export with it)
    data = {"kicad_origin": [KX, Y0], "footprints": footprints(pcb), "board": outlines(pcb), "plate": plate}
    path = BUILD / "pcb/parts.json"
    path.write_text(json.dumps(data, indent=1))
    print("wrote %s: %d footprints, plate %s" % (path.relative_to(BUILD.parent.parent), len(data["footprints"]),
                                               "ok" if data["plate"] else "MISSING"))


if __name__ == "__main__":
    main()
