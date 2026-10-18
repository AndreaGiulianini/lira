"""Copies the finished files into ../production/ with readable names and writes its README.

    python3 publish.py        (run by `make all` once everything is generated)

../production/ is rewritten from scratch every time: never edit it by hand, change source/ instead. It is built in a
sibling folder and swapped in at the end, so a failure leaves the previous production/ as it was.
"""
import csv
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "pcb"))

import layout as L  # noqa: E402
from circuit import AUDIO_DEVIATIONS, DEVIATIONS  # noqa: E402
from paths import BUILD, PUBLISH, ROOT

# pictures in build/img/, in the order the README lists them
IMAGES = ("desk", "case-front", "case-back", "case-side", "case-top", "case-bottom", "case-exploded", "pcb-top", "pcb-bottom")
DESCRIPTION = ("57 keys: numpad on the left + Agar mini 40% with a split 3u + 3u spacebar, built-in USB sound card. "
               "Wired version: USB-C only, no battery, Raspberry Pi RP2040.")
STAGE = PUBLISH.with_name(PUBLISH.name + ".new")  # built here, then renamed to PUBLISH


def copy(src, rel):
    dst = STAGE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst


def bom_summary():
    lines, parts = 0, 0
    with open(BUILD / "jlcpcb/bom.csv") as f:
        for row in csv.DictReader(f):
            lines += 1
            parts += len(row["Designator"].split(","))
    return lines, parts


def kicad_board(src, rel):
    """The board as published: its 3D models live in source/lib, which the generated board names relative to
    source/ (lib/...) or through KICAD6_3RD_PARTY; from production/kicad/ both become ${KIPRJMOD}/../../source/lib/."""
    text = src.read_text().replace('(model "lib/', '(model "${KIPRJMOD}/../../source/lib/')
    text = text.replace("${KICAD6_3RD_PARTY}/", "${KIPRJMOD}/../../source/lib/")
    dst = STAGE / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text)


def main():
    if STAGE.exists():
        shutil.rmtree(STAGE)
    jl = BUILD / "jlcpcb"
    copy(jl / "lira-pcb-gerbers.zip", "1-pcb-jlcpcb/gerber-pcb.zip")
    copy(jl / "bom.csv", "1-pcb-jlcpcb/bom.csv")
    copy(jl / "cpl.csv", "1-pcb-jlcpcb/cpl.csv")
    copy(jl / "lira-plate-gerbers.zip", "2-plate/jlcpcb/gerber-plate.zip")
    copy(jl / "plate.dxf", "2-plate/laser-cut/plate.dxf")
    for side in ("left", "right"):
        copy(BUILD / "case" / ("plate-print-%s.stl" % side), "2-plate/3d-print/plate-%s.stl" % side)
        copy(BUILD / "case" / ("plate-print-%s.step" % side), "2-plate/3d-print/step/plate-%s.step" % side)
    pieces = []
    for stl in sorted((BUILD / "case").glob("case-*.stl")):
        name = stl.stem[len("case-"):]
        copy(stl, "3-case-3d-print/%s.stl" % name)
        copy(stl.with_suffix(".step"), "3-case-3d-print/step/%s.step" % name)
        pieces.append(name)
    fw = BUILD / "firmware"
    copy(fw / "lira.uf2", "4-firmware/lira.uf2")
    copy(fw / "vial.json", "4-firmware/vial.json")
    copy(fw / "keyboard.toml", "4-firmware/keyboard.toml")
    kicad_board(BUILD / "pcb/lira.kicad_pcb", "kicad/lira.kicad_pcb")
    for f in ("lira.kicad_pro", "lira.kicad_dru"):
        copy(BUILD / "pcb" / f, "kicad/" + f)
    copy(BUILD / "plate/plate.kicad_pcb", "kicad/plate.kicad_pcb")
    for f in ("lira.kicad_sch", "lira.kicad_sym", "sym-lib-table"):
        copy(BUILD / "sch" / f, "kicad/schematic/" + f)
    # the footprint libraries stay in source/lib: point the published schematic at them
    table = (BUILD / "sch/fp-lib-table").read_text().replace("${KIPRJMOD}/../../lib/", "${KIPRJMOD}/../../../source/lib/")
    (STAGE / "kicad/schematic/fp-lib-table").write_text(table)
    # schematic and the three verifications: ERC, netlist consistency, datasheet checks
    copy(BUILD / "sch/lira-schematic.pdf", "5-schematic-and-checks/schematic.pdf")
    copy(BUILD / "sch/svg/lira.svg", "5-schematic-and-checks/schematic.svg")
    copy(BUILD / "netlist.json", "5-schematic-and-checks/netlist.json")
    copy(BUILD / "sch/erc.rpt", "5-schematic-and-checks/erc-kicad.txt")
    for src, dst in (("check-report.txt", "datasheet-checks.txt"), ("verify-report.txt", "consistency-check.txt")):
        if (BUILD / src).exists():
            copy(BUILD / src, "5-schematic-and-checks/" + dst)
    copy(BUILD / "case/check-fit.txt", "3-case-3d-print/fit-check.txt")
    (STAGE / "5-schematic-and-checks/differences-from-wireless.txt").write_text(
        "The wired version of Lira: the wireless board (branch main) with the radio and the battery taken out.\n"
        "Differences from it:\n" + "".join("%d. %s\n" % (i + 1, d) for i, d in enumerate(DEVIATIONS)) +
        "\nSound card after C-Media's CM108B/CM119B demo board v1.33 (sheet 4). Differences:\n" +
        "".join("%d. %s\n" % (i + 1, d) for i, d in enumerate(AUDIO_DEVIATIONS)))
    copy(BUILD / "layout.png", "images/layout.png")
    for name in IMAGES:  # the renders as JPEG (90): a tenth of the size, which matters in git
        dst = STAGE / "images" / (name + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "90", str(BUILD / "img" / (name + ".png")),
                        "--out", str(dst)], check=True, stdout=subprocess.DEVNULL)
    review = BUILD / "review"  # `make review`: images and files for a human design review, and the posts
    if review.is_dir() and (review / "bom.csv").stat().st_mtime >= (jl / "bom.csv").stat().st_mtime:
        shutil.copytree(review, STAGE / "review")
        posts = ROOT / "reviews" / "review-request.md"
        if posts.exists():
            copy(posts, "review/POSTS.md")
    elif review.is_dir():
        print("review package older than the board: not published (make review)")
    write_readme(pieces)
    if PUBLISH.exists():
        shutil.rmtree(PUBLISH)
    STAGE.rename(PUBLISH)
    print("published %s" % PUBLISH)


def write_readme(pieces):
    lines, parts = bom_summary()
    n_keys = len(L.SWITCHES)
    stl = ", ".join("`%s.stl`" % p for p in pieces)
    text = """# Lira

{description}

> [!WARNING]
> **This keyboard has never been built.** It is a design only: no prototype of either version (wireless on branch
> `main`, wired on branch `rp2040`) has ever been ordered, assembled or powered on, and nothing here has been tested
> on real hardware. The circuit, PCB, case and firmware are generated and checked automatically and reviewed on paper,
> but passing those checks does not make a working board: there may be mistakes that only a real prototype would
> reveal. **Do not put it into production, sell it or order it in quantity.** If you build one anyway, treat it as an
> untested design: order the minimum quantity and expect to debug it yourself.

> This folder is **generated automatically** from `../source/` and is rewritten every time it is regenerated:
> do not edit it by hand.

![keyboard](images/desk.jpg)

## What is here and what to do with it

| Folder | Files | What to do with them |
|---|---|---|
| `1-pcb-jlcpcb/` | `gerber-pcb.zip`, `bom.csv`, `cpl.csv` | PCB order at JLCPCB: 2 layers, 1.6 mm, assembly of the **bottom side** ({parts} parts, {lines} different part numbers). |
| `2-plate/` | | The plate carries the keyboard (6 ears and 3 back tabs screw it to the top frame). Three ways to make it, all interchangeable (guide, §2): |
| | `jlcpcb/gerber-plate.zip` | cut by JLCPCB: 1.6 mm FR4, ordered like a PCB with no copper and no assembly (black or white) |
| | `laser-cut/plate.dxf` | laser cut in metal or plastic (1.5 mm aluminium or steel, POM…), e.g. JLCCNC sheet metal |
| | `3d-print/plate-left.stl`, `plate-right.stl` | 3D printed (PLA/PETG) in two pieces, top face on the bed, no supports; 4 mm ribbed, 1.5 mm where the switches clip in |
| `3-case-3d-print/` | {stl} | Case to print **without supports**: the top frames lying on their flat underside (the side the plate screws to), deck up: the STL files are exported tilted, as assembled, so use the slicer's “lay on face” on that flat underside, the bottom halves the way they sit on the desk. The same pieces for CAD are in `step/` |
| | `fit-check.txt` | Result of the automatic fit check: PCB, parts, plate, keys, screws and ports against the printed pieces (see guide, §7) |
| `4-firmware/` | `lira.uf2` | Firmware: a new board shows up as the **RPI-RP2** drive as soon as it is plugged in: drag the file onto it. To update it later: fn + Esc, or hold BOOT (paperclip, underside) while plugging the cable in (see guide §4) |
| | `vial.json`, `keyboard.toml` | Configuration (Vial reads it from the keyboard by itself; these are for reference only) |
| `5-schematic-and-checks/` | `schematic.pdf` | Circuit diagram, for anyone who wants to review the circuit (also `schematic.svg`) |
| | `differences-from-wireless.txt` | What changes from the wireless board (RP2040 after Raspberry Pi's own design, no battery), and the sound card's differences from the chip maker's reference design |
| | `erc-kicad.txt`, `consistency-check.txt`, `datasheet-checks.txt` | Results of the three automatic checks (see guide, §6) |
| | `netlist.json` | Every connection, pin by pin, in readable form |
| `kicad/` | `lira.kicad_pcb`, `plate.kicad_pcb`, `schematic/` | To open the PCB, plate and schematic in KiCad |
| `images/` | pictures | Layout; Blender Cycles renders: the keyboard on a desk (`desk.jpg`), the case from every side, an exploded view, the PCB |

## Summary

- {n_keys} hot-swap MX switches, USB-C, Raspberry Pi RP2040, RMK firmware with Vial. Wired: no battery, no Bluetooth (the
  wireless version, with an nRF52840 and a LiPo cell, is on the git branch `main`).
- Built-in USB sound card: a 3.5 mm headset jack at the back (headphones + microphone, CTIA plugs) with a headphone
  amplifier, behind a USB hub; over the USB cable the computer sees a keyboard and a USB headset (no drivers). It is on
  whenever the cable is plugged in.
- Case in {n_pieces} pieces to print (256 mm bed), inspired by the Apple M0110; top mount (plate screwed to the top frame).

## Buy separately

| What | Notes |
|---|---|
| {n_keys} MX switches + keycaps (Agar mini set + numpad kit) | you need a 2u vertical Enter, a 2u 0, a 1u + and a 1u − (most numpad kits only have a 2u +) |
| Screw-in PCB stabilizers: 2 × 2u + 2 for the 3u bars | 3u wire with 38.1 mm spacing |
| Screws, heat-set inserts, pins, feet | list in `../README.md` |

Every step in detail: [`../guide/build-guide.md`](../guide/build-guide.md).
""".format(description=DESCRIPTION, parts=parts, lines=lines, stl=stl,
           n_keys=n_keys, n_pieces=len(pieces))
    (STAGE / "README.md").write_text(text)


if __name__ == "__main__":
    main()
