# Lira

57 keys: numpad on the left + Agar mini 40% with a split 3u + 3u spacebar, built-in USB sound card. Wired version: USB-C only, no battery, Raspberry Pi RP2040.

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
| `1-pcb-jlcpcb/` | `gerber-pcb.zip`, `bom.csv`, `cpl.csv` | PCB order at JLCPCB: 2 layers, 1.6 mm, assembly of the **bottom side** (204 parts, 37 different part numbers). |
| `2-plate/` | | The plate carries the keyboard (6 ears and 3 back tabs screw it to the top frame). Three ways to make it, all interchangeable (guide, §2): |
| | `jlcpcb/gerber-plate.zip` | cut by JLCPCB: 1.6 mm FR4, ordered like a PCB with no copper and no assembly (black or white) |
| | `laser-cut/plate.dxf` | laser cut in metal or plastic (1.5 mm aluminium or steel, POM…), e.g. JLCCNC sheet metal |
| | `3d-print/plate-left.stl`, `plate-right.stl` | 3D printed (PLA/PETG) in two pieces, top face on the bed, no supports; 4 mm ribbed, 1.5 mm where the switches clip in |
| `3-case-3d-print/` | `bottom-left.stl`, `bottom-right.stl`, `top-left.stl`, `top-right.stl` | Case to print **without supports**: the top frames lying on their flat underside (the side the plate screws to), deck up: the STL files are exported tilted, as assembled, so use the slicer's “lay on face” on that flat underside, the bottom halves the way they sit on the desk. The same pieces for CAD are in `step/` |
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

- 57 hot-swap MX switches, USB-C, Raspberry Pi RP2040, RMK firmware with Vial. Wired: no battery, no Bluetooth (the
  wireless version, with an nRF52840 and a LiPo cell, is on the git branch `main`).
- Built-in USB sound card: a 3.5 mm headset jack at the back (headphones + microphone, CTIA plugs) with a headphone
  amplifier, behind a USB hub; over the USB cable the computer sees a keyboard and a USB headset (no drivers). It is on
  whenever the cable is plugged in.
- Case in 4 pieces to print (256 mm bed), inspired by the Apple M0110; top mount (plate screwed to the top frame).

## Buy separately

| What | Notes |
|---|---|
| 57 MX switches + keycaps (Agar mini set + numpad kit) | you need a 2u vertical Enter, a 2u 0, a 1u + and a 1u − (most numpad kits only have a 2u +) |
| Screw-in PCB stabilizers: 2 × 2u + 2 for the 3u bars | 3u wire with 38.1 mm spacing |
| Screws, heat-set inserts, pins, feet | list in `../README.md` |

Every step in detail: [`../guide/build-guide.md`](../guide/build-guide.md).
