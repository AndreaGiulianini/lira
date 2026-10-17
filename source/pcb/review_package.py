"""Images and files for a human design review (forums, Reddit, a paid reviewer), in build/review/:

    python3 pcb/review_package.py           (make review)

The images follow r/PrintedCircuitBoard's image rules, which are good practice anywhere: the schematic on white with
no grid; one copper layer per PNG with its silkscreen, the board edge and the drill holes and nothing that is not in
the gerbers (no net names, no pin numbers, no courtyards); 3D views straight down, in the same orientation as the 2D
images. The bottom side, where every part is, is shown as seen from below (mirrored), in 2D and in 3D alike.
Added: zooms on the electronics strip, where all the parts except the switch sockets and diodes are.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from paths import BUILD  # noqa: E402

KCLI = os.environ.get("KCLI", str(Path.home() / "Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = BUILD / "review"
PCB = BUILD / "pcb/lira.kicad_pcb"
LIB = "KICAD6_3RD_PARTY=%s" % (ROOT / "lib")
BG = "#0b1520"  # dark background for the copper layers (KiCad's colours: red top copper, blue bottom copper)
SCH_ZOOM = (0.035, 0.135, 0.985, 0.495)  # schematic: USB, hub, power path, charger, regulator, module, audio
STRIP_REFS = re.compile(r"^(U\d|J\d|Q\d|Y\d|L\d|SW10\d|D10\d|C1\d\d|R1\d\d|JP\d|TP)")


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def screenshot(html, png, w, h):
    """Rasterise an HTML page with headless Chrome at 2x: the PNG is 2w x 2h pixels."""
    page = png.with_suffix(".html")
    page.write_text(html)
    run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
         "--allow-file-access-from-files", "--window-size=%d,%d" % (w, h), "--screenshot=%s" % png, page.as_uri()])
    page.unlink()


def svg_size(svg):
    m = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    return [float(v) for v in m.groups()]


def show_svg(svg_text, png, width, bg, crop=None, label=None):
    """SVG on a solid background, optionally cropped to crop = (fx0, fy0, fx1, fy1) fractions of the image."""
    x, y, w, h = svg_size(svg_text)
    if crop:
        fx0, fy0, fx1, fy1 = crop
        x, y, w, h = x + fx0 * w, y + fy0 * h, (fx1 - fx0) * w, (fy1 - fy0) * h
        svg_text = re.sub(r'viewBox="[^"]+"', 'viewBox="%g %g %g %g"' % (x, y, w, h), svg_text, count=1)
    svg_text = re.sub(r'(<svg[^>]*?)\swidth="[^"]+"', r'\1 width="100%"', svg_text, count=1)
    svg_text = re.sub(r'(<svg[^>]*?)\sheight="[^"]+"', r'\1 height="100%"', svg_text, count=1)
    pad = 24
    ww = width // 2
    hh = int((ww - 2 * pad) * h / w) + 2 * pad + (28 if label else 0)
    cap = ('<div style="font:15px Menlo,monospace;color:%s;margin:0 0 8px 2px">%s</div>'
           % ("#c8d0d8" if bg != "#ffffff" else "#333", label)) if label else ""
    screenshot('<html><body style="margin:0;padding:%dpx;background:%s">%s<div style="width:%dpx;height:%dpx">%s'
               '</div></body></html>' % (pad, bg, cap, ww - 2 * pad, int((ww - 2 * pad) * h / w), svg_text),
               png, ww, hh)


def board_svg(layers, mirror):
    tmp = OUT / "tmp.svg"
    cmd = [KCLI, "pcb", "export", "svg", "--mode-single", "-l", layers, "--page-size-mode", "2",
           "--exclude-drawing-sheet", "--drill-shape-opt", "2", "-D", LIB, "-o", str(tmp), str(PCB)]
    if mirror:
        cmd.insert(4, "--mirror")
    run(cmd)
    text = tmp.read_text()
    tmp.unlink()
    return text


def strip_crop(parts, mirror):
    """Fractions of the board image around the electronics strip (parts outside the key matrix)."""
    bx0, by0, bx1, by1 = parts["board"][0]["outer"]  # slab frame: x right, y back
    boxes = [fp["courtyard"] or fp["fab"] for fp in parts["footprints"] if STRIP_REFS.match(fp["ref"])]
    boxes = [b for b in boxes if b]
    x0, x1 = min(b[0] for b in boxes) - 6, max(b[2] for b in boxes) + 6
    y0, y1 = min(b[1] for b in boxes) - 4, max(b[3] for b in boxes) + 3
    fx0, fx1 = (x0 - bx0) / (bx1 - bx0), (x1 - bx0) / (bx1 - bx0)
    if mirror:
        fx0, fx1 = 1 - fx1, 1 - fx0
    fy0, fy1 = (by1 - min(y1, by1)) / (by1 - by0), (by1 - max(y0, by0)) / (by1 - by0)  # back edge on top
    return max(fx0, 0), max(fy0, 0), min(fx1, 1), min(fy1, 1)


def render3d(side, png, zoom=2.9, pan=None, w=3600, h=1200):
    cmd = [KCLI, "pcb", "render", "--side", side, "--quality", "high", "--background", "opaque", "-w", str(w),
           "-h", str(h), "--zoom", str(zoom), "-D", LIB, "-o", str(png), str(PCB)]
    if pan:
        cmd[4:4] = ["--pan", pan]
    run(cmd)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    parts = json.loads((BUILD / "pcb/parts.json").read_text())
    # 1 schematic: KiCad's SVG on white (the PDF is copied as well)
    sch = sorted((BUILD / "sch/svg").glob("*.svg"))[0].read_text()
    show_svg(sch, OUT / "01-schematic.png", 4800, "#ffffff")
    show_svg(sch, OUT / "01b-schematic-power-usb-module.png", 5200, "#ffffff", SCH_ZOOM)
    shutil.copy(BUILD / "sch/lira-schematic.pdf", OUT / "01-schematic.pdf")
    # 2-5 copper layers: one per image, with silkscreen, edge and holes
    top = board_svg("F.Cu,F.Silkscreen,Edge.Cuts", False)
    bottom = board_svg("B.Cu,B.Silkscreen,Edge.Cuts", True)
    show_svg(top, OUT / "02-pcb-top-layer.png", 6000, BG, label="TOP layer (F.Cu + silkscreen + edge), seen from above")
    show_svg(bottom, OUT / "03-pcb-bottom-layer.png", 6000, BG,
             label="BOTTOM layer (B.Cu + silkscreen + edge), seen from BELOW (mirrored) - all SMD parts are here")
    show_svg(bottom, OUT / "04-pcb-bottom-layer-electronics-zoom.png", 4400, BG, strip_crop(parts, True),
             label="BOTTOM layer, electronics area (module, USB-C, hub, sound card, charger, regulator, power path), seen from below")
    show_svg(top, OUT / "05-pcb-top-layer-electronics-zoom.png", 4400, BG, strip_crop(parts, False),
             label="TOP layer, same area, seen from above")
    # 6-8 3D, straight down, same orientation as the 2D images
    render3d("top", OUT / "06-3d-top-plan.png")
    render3d("bottom", OUT / "07-3d-bottom-plan.png")
    copy_if(BUILD / "img/pcb-bottom.png", OUT / "08-3d-bottom-angled.png")
    # files
    shutil.copy(BUILD / "jlcpcb/bom.csv", OUT / "bom.csv")
    shutil.copy(BUILD / "jlcpcb/lira-pcb-gerbers.zip", OUT / "gerbers.zip")
    for src, dst in (("check-report.txt", "datasheet-checks.txt"), ("verify-report.txt", "consistency-check.txt"),
                     ("pcb/drc.rpt", "drc-report.txt"), ("sch/erc.rpt", "erc-report.txt")):
        copy_if(BUILD / src, OUT / dst)
    print("wrote", OUT.relative_to(ROOT), ":", ", ".join(sorted(p.name for p in OUT.iterdir())))


def copy_if(src, dst):
    if src.exists():
        shutil.copy(src, dst)


if __name__ == "__main__":
    main()
