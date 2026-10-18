# Lira — build guide: ordering, parts, programming, assembly

The files are in `production/`.

## The circuit in brief

This is the **wired version** of Lira (git branch `rp2040`): the same keyboard, case, plate, sound card and keymap
as the wireless one (branch `main`), with the radio and the battery taken out. The sound card only ever works over the
cable, so on a keyboard that is always plugged in, the nRF52840 module, the cell, the charger, the power path and the
power switch have nothing to do: here a **Raspberry Pi RP2040** takes the module's place. Its circuit is Raspberry
Pi's own minimal design ("Hardware design with RP2040", the circuit of the Pico); everything else is the wireless
board's. The differences are listed in the schematic and in `5-schematic-and-checks/differences-from-wireless.txt`.
The **built-in sound card** (a USB hub and a USB audio chip behind the USB-C port) follows the manufacturer's reference
design (C-Media CM108B demo board).

| Block | Choice | Notes |
|---|---|---|
| Microcontroller | Raspberry Pi **RP2040** (LCSC C2040) with a **W25Q128JV** 16 MB QSPI flash | Programmed over USB from its boot ROM: no bootloader to flash and no SWD probe (§4) |
| Clock | 12 MHz **Abracon ABM8-272-T3** with 2 × 15 pF and 1 kΩ on XOUT | The crystal and the values Raspberry Pi qualified for the RP2040 |
| Power | **AP2112K** 3.3 V regulator from the USB 5 V; the RP2040's own regulator makes its 1.1 V core | 100 nF at every supply pin of the RP2040, 1 µF at its regulator's input and output |
| USB-C | HRO TYPE-C-31-M-12, USBLC6-2SC6 ESD protection | Standard JLCPCB parts; 5.1 kΩ on CC1 / CC2 (a plain USB device) |
| USB hub | WCH **CH334P** (USB 2.0), 12 MHz crystal, right behind the USB-C port | The RP2040 is on hub port 3 (through 27 Ω), the sound card on port 2: over the cable the computer sees a hub with a keyboard and a headset |
| Sound card | C-Media **CM108B** (USB audio, no drivers on macOS / Windows / Linux) + TI **TPA6132A2** headphone amplifier, 3.5 mm **headset jack** at the back | Headphones and microphone (4-pole CTIA plugs, as on phones and Macs; plain 3-pole headphones work too). On whenever the cable is plugged in: a switch (TPS22919) turned on by the USB 5 V itself starts it slowly, so the hub does not see a dip |
| Matrix | 4 rows × 17 columns, 1N4148W diodes (column → row) | The firmware takes the pins from the PCB automatically |
| Indicator | Red LED = Caps Lock | Visible through the rear window |
| Buttons | **BOOT** (restarts into the USB boot ROM when held while the keyboard starts) and **RESET** | BOOT is reachable with a paperclip through the hole under the case; RESET only with the case open |
| Test pads | SWCLK, SWDIO, RESET, GND, 3V3, VBUS | On the back: the SWD pads in one row right in front of the RP2040 (CLK, DIO, RST, GND; 3V3 behind the chip), for debugging only; every pad labelled on the silkscreen |

All SMD components are **on the bottom side** (single-sided JLCPCB assembly). The top side has only the
switches.

## 1. Ordering the PCB (JLCPCB)

1. Upload `production/1-pcb-jlcpcb/gerber-pcb.zip`. Options: 2 layers, FR4, **1.6 mm**, any colour
   (it stays hidden), lead-free HASL or ENIG finish.
2. Turn on **PCB Assembly** → *Assemble bottom side*, quantity 2 (the minimum).
3. Upload `bom.csv` and `cpl.csv` from the same folder.
4. **Check the placement preview**, part by part. The rotations depend on JLC's footprints and sometimes need
   to be corrected by 90°/180°:
   - RP2040 (QFN-56) and W25Q128 flash (SOIC-8): pin-1 dot in the right corner (compare with
     `kicad/lira.kicad_pcb`); a QFN turned by 90° still sits on its pads, so only the dot tells;
   - USB-C: opening towards the edge;
   - 1N4148W diodes and B5819W Schottky: cathode stripe towards pad 1;
   - LED: cathode (pad 1) as in the footprint;
   - the two 12 MHz crystals (4 pads; one next to the hub, one in front of the RP2040): pin-1 mark as in the
     footprint; turned by 90° their contacts land on the ground pads and the chip does not start;
   - AP2112K, USBLC6, CH334P (hub), CM108B (sound chip), TPA6132A2 (amplifier), TPS22919 (switch): pin 1 in the
     right corner;
   - headset jack: opening at the rear edge (it sticks out of the board by 1.8 mm; the USB-C by 0.4 mm);
   - hot-swap sockets: their two pads on top of the PCB pads.
5. "Extended" parts (extra loading fee): the RP2040, the flash, its crystal, the sockets, USB-C, ESD, and for the
   sound card the hub, the sound chip, the amplifier, the switch and the jack.

## 2. The plate: cut by JLCPCB, laser cut or 3D printed

The switches clip into the plate, and the plate is what holds the keyboard together: its 10 ears and 3 back tabs
are screwed to the top frame, and the PCB hangs from the switches. The three versions have the same outline,
holes and openings, so they are interchangeable (same screws, same case).

- **Cut by JLCPCB, FR4 1.6 mm** (recommended: flat and stiff): upload `production/2-plate/jlcpcb/gerber-plate.zip`
  as a normal 2-layer 1.6 mm PCB, with no assembly. The file has no copper, only the outline and the solder mask;
  JLCPCB mills it like any board. Colour: black (looks good under warm grey keycaps) or white.
- **Laser cut in metal**: `production/2-plate/laser-cut/plate.dxf` (outline, openings and holes, in mm) for
  1.5 mm aluminium (5052) or steel, e.g. JLCCNC's sheet-metal service or any local laser cutter. Aluminium is a
  little heavier and stiffer than FR4; the switches clip in the same way (MX plates are 1.5 ± 0.1 mm).
- **3D printed**: `production/2-plate/3d-print/plate-left.stl` and `plate-right.stl` (two pieces, because the
  plate is 348 mm long). Print them with the **top face on the bed** (as exported), no supports, PLA or PETG,
  0.2 mm layers, 3 perimeters, 100 % infill (they are thin: about 35 g and 21 g). Where the switches clip in the
  plate is 1.5 mm thick; between the keys a grid of ribs makes it 4 mm thick, which makes it about as stiff as the
  FR4 one. The two pieces meet along the key boundaries in the middle of the main block: each has its own ears,
  and once the switches are in, the switches and the PCB hold them together (a drop of glue on the joint is
  optional). Check that a switch clips in firmly before printing the whole plate: if it is loose, the printer
  over-extrudes or prints holes too large (the openings are 14.0 mm).

## 3. Parts to buy separately

| What | Notes |
|---|---|
| 57 MX switches (3- or 5-pin) | Hot-swap: they plug in without soldering |
| Keycaps | Agar mini set + **numpad kit**: you need a 2u vertical Enter, a 2u 0, + and − |
| **Screw-in PCB** stabilizers | 2 × 2u (numpad 0 and Enter) + 2 for the **3u** spacebars: check that the kit has wires for 3u (38.1 mm spacing) |
| Screws and small hardware | See the README |
| A paperclip | For the BOOT button under the case (only if a firmware update ever goes wrong) |

## 4. First power-up and programming

Do these steps **before** you fit the switches and the case. Nothing else is needed than a USB-C cable: the RP2040
has its USB bootloader in ROM, so there is no programmer to buy and no bootloader to flash.

1. **Power check**: plug in the USB-C. On the test pads you should measure about 5 V on **VBUS** and 3.3 V on
   **3V3**, relative to GND (and 1.1 V on either pad of C12, the RP2040's core supply). The computer should find a
   **USB hub**, a **USB audio device** ("USB Audio Device" / C-Media: the sound card is on whenever the cable is in)
   and, because the flash is still empty, a drive called **RPI-RP2**: the RP2040's boot ROM, waiting for a firmware.
2. **Firmware**: drag `lira.uf2` from `production/4-firmware/` onto **RPI-RP2**. The drive disappears and the
   keyboard starts. On macOS 14 and later the Finder may stop the copy with error −36: copy it from the Terminal
   instead, `cp -X production/4-firmware/lira.uf2 /Volumes/RPI-RP2/`.
3. **Vial**: open <https://vial.rocks> in Chrome (or the Vial app) with the keyboard connected. To unlock the
   protected features, hold **Esc + Return**.
4. **Future updates**: **fn + Esc** (or "Reboot to bootloader" in Vial) restarts into the boot ROM: the RPI-RP2 drive
   appears, drag the new `.uf2` onto it. If a firmware ever does not start, **hold the BOOT button** (a paperclip
   through the small hole under the case) **while you plug in the cable**: the RP2040 then always starts in the boot
   ROM, whatever is in the flash. With the case open, holding BOOT and pressing RESET does the same.
5. The SWD pads (CLK, DIO, RST, GND in a row in front of the RP2040, on the underside) are only for debugging the
   firmware with a probe; you do not need them to build or update the keyboard.

### Default keymap (everything can be changed in Vial)

- **Base**: as printed on the Agar keycaps. Left spacebar = space. Right spacebar = space, but when held it
  turns on the *numbers* layer.
- **Right-hand keys**: right shift, fn, right ⌘ and right option send **↑ → ← ↓** when tapped, and
  act as modifiers when held.
- **Numbers layer** (hold the right spacebar):
  - top row: ` 1 2 3 4 5 6 7 8 9 0 - =
  - H/J = [ ], ; = ', . = /
  - arrows = PgUp / Home / PgDn / End, Tab = Caps Lock
  - numpad = F1–F12, − and + become / and *
- **System layer** (hold fn):
  - Z…N media keys (mute, volume −, volume +, play/pause, previous, next)
  - Backspace = forward delete
  - Esc = bootloader

## 5. Case: printing and assembly

1. **Print** the 4 pieces in the `3-case-3d-print/` folder, without supports:
   - top frame halves with the flat face on the bed;
   - bottom halves the way they sit on the desk.

   It is a good idea to print a test corner first, to check your printer's tolerances.
   - Settings: 3 perimeters, 5 solid layers on top and 4 on the bottom; 15 % gyroid infill for the top frame,
     8 % (or "lightning") for the bottom halves. About 300–320 g of PLA in total (see the README for why it is
     not worth hollowing out the case by designing cavities).
   - Surfaces tilted by only a few degrees (the chamfers on the top frame and the resting surfaces inside the
     bottom halves) come out stepped: use the slicer's variable layer height, or 0.12 mm layers.
   - The case is 377 mm long: if your filament shrinks more than usual (some PETG and ABS), scale the pieces
     in the slicer before printing.
2. **Heat-set inserts**, all in the flat underside of the top frame (with the frame lying face down on the
   table the holes are vertical):
   - M2 (10) for the plate's ears, at the front and at the sides of the key wells;
   - M3 (11) for the case screws and the back bolts.

   Press them in flush with the surface, never proud of it: the plate lies directly on this surface (it is a
   **top mount** case), and an insert standing out by even 0.2 mm lifts the plate. If one does, level it with a
   flat file or the iron. The holes are deeper than the inserts: the extra space is for the screw tips.
3. **Stabilizers**: fit them to the PCB now. Their screws are tightened from under the PCB.
4. **Plate + PCB + switches**, one unit: lay the plate on the PCB (the stabilizers come up through their
   openings), then push the switches through the plate into the hot-swap sockets: the four corners first,
   then all the others, supporting the PCB under each socket as you press. The PCB now hangs from the switches;
   nothing else holds it.
5. **Top frame**: join the two halves with the dowel pins, lay the frame face down, and put the unit in: plate
   face down on the frame's underside, switches in the key wells. Fasten the plate with 6 M2 × 5 screws through
   its ears (6 at the front, 2 per side): they are all outside the PCB, so a 1.5 mm hex key reaches them. From
   now on the plate also holds the two halves of the frame together.
6. **Bottom**: join the two halves with the dowel pins (a drop of glue if you like). Measure the length: it must
   be 377.4 mm. If it is more than 1 mm short, the plate's side ears may not fit their pockets: reprint with the
   corrected scale.
7. **Close**: lower the bottom straight down onto the frame (the USB-C port and the headset jack enter their windows
   from above, the plate's ears drop into their pockets), then fasten it with the M3 screws: 8 × M3 × 12
   (front and sides) and 3 × M3 × 20 (the back ones: they go through the PCB's large holes and the plate's back
   tabs, clamping the back of the plate against the frame). Some holes are up to 21 mm deep and tilted by 8°: you
   need a long 2.5 mm hex key (1/4" screwdriver bits do not fit).
8. Turn the keyboard over, fit the keycaps, and stick on the Ø 12 mm rubber feet.

At the back, through the windows, you will find:
- the USB-C port;
- further right, the 3.5 mm headset jack (headphones / headset with microphone);
- the red LED (Caps Lock), left of the USB-C port.

The LED is under the PCB and faces the bottom half: you see its reflection in the window from behind, not
from your typing position. To see it from the front you would need a side-firing LED, which means a different PCB.

You press the BOOT button from below with a paperclip, through the small hole in the bottom half (a guide
leads it to the button). To reach the underside of the PCB, undo the 11 M3 screws and lift the bottom off:
everything else stays together on the top frame.

## 6. How the circuit is checked

Nothing here has been built yet, so the checking relies on four things that are independent of each other and run
on every `make`:

1. **Circuits taken from designs that exist.** The RP2040's is Raspberry Pi's own minimal design (the Pico's), with
   the crystal Raspberry Pi qualified for the chip; USB-C, ESD, hub, sound card and matrix are the wireless
   board's, with the differences listed in `differences-from-wireless.txt`. The sound card follows C-Media's
   CM108B/CM119B demo board.
2. **The schematic is generated from the same description that generates the PCB**, with KiCad's ERC:
   `erc-kicad.txt`.
3. **Pin-by-pin consistency** between circuit, PCB and schematic: `consistency-check.txt`.
4. **Datasheet tests** written independently of the design, each test citing the datasheet page it is based on,
   including the RP2040, its flash and crystal: `datasheet-checks.txt`.

To review the circuit yourself, open `kicad/schematic/` in KiCad.

## 7. How the case is checked

The case is the wireless version's, with the battery pocket gone and the paperclip hole moved under the BOOT
button.

An **automatic fit check** (`3-case-3d-print/fit-check.txt`, redone on every `make`) models everything that goes
inside the case from the datasheet dimensions and compares it with the printed pieces, read back from the exported
STL/STEP files:

- **collisions**, with at least 0.3 mm of clearance: PCB, components under the board with their heights (RP2040,
  flash, USB-C, headset jack, sound chip, buttons), hot-swap sockets, switch pins, stabilizer screws, plate, keys at
  rest and pressed;
- **assembly**: the path the PCB, plate and top frame follow while they are lowered into place;
- **ports**: a bulky USB-C plug (13 × 7.5 mm), a 3.5 mm plug up to 9 mm across, the LED visible from behind, BOOT
  hole clear to the button;
- **screws**: where the head rests, where the tip ends, how many millimetres of thread engage the insert, how much
  plastic surrounds each insert;
- **walls**: thickness measured at about 400,000 points (minimum 1.2 mm; below 0.8 mm is an error);
- **printing**: overhangs, bridges and ledges in the print orientation; size against the bed.

It reports 0 errors and three warnings: two 7–8 mm² ledges at 50° under the rear corners, which print without
supports, and a 0.93–0.99 mm spot at the floor of the headset-jack window. Print the bottom with at least
3 perimeters so that spot is solid.

One limitation would need a different PCB to fix: the status LED sits under the PCB facing the bottom, so from the
typing position you see its reflection in the rear window, not the LED itself.

## 8. What still needs checking on the real thing

Before ordering 5 boards, it is wise to order 2.

- **Component rotations** in the JLCPCB preview: they must be checked by hand (see §1).
- **RP2040 bring-up**: on the first board, check 1.1 V on C12 and that the RPI-RP2 drive appears on its own (the
  flash is empty). If it does not, the crystal is the usual suspect: look at its rotation in the preview. Once the
  firmware is in, check that the keyboard still enumerates after a cold start with the cable plugged into the
  computer (the RP2040 is the second device behind the hub).
- **Plate openings for the stabilizers**: 7 × 16 mm, wider than the Cherry standard. In theory they work
  with any screw-in stabilizer, but they have not been tested.
- **Case tolerances** (0.5 mm around the keys and at the front and back of the PCB, 1 mm at its sides, 0.5 mm
  between the rear bosses and the PCB's 7.4 mm holes,
  0.6 mm around the plate's ears): they depend on the printer. That is why you should print a test corner
  first (§5).
- **Plate flush on the frame**: the M2 inserts must not stand proud of the frame's underside (§5).
- **Routing**: automatic (Freerouting; the few connections it leaves open or crossing are redone by a small
  router in `source/pcb/repair.py`), passes DRC, not optimized by hand, except a few short connections the generator
  draws itself (the RP2040's 1.1 V core supply, under the chip, and its SWD lines; the hub's crystal; the
  amplifier's supply; the ground pins of the chips) and the USB high-speed pair
  (480 Mbit/s, from the USB-C port through the ESD chip to the hub): about
  20 mm on the bottom layer, no vias, lengths within 0.5 mm. For about a third of the way the two lines run side by
  side, 0.5 mm apart with ground 0.2 mm beside them (about 96 Ω); around the ESD chip they split, D+ through its
  middle and D− round its side as ST lays it out, and there the impedance is higher. Over 20 mm this is normally
  harmless; and if the hub ever fell back to full speed (12 Mbit/s), the keyboard and the sound card would not notice.
  Between the hub and the RP2040 and the sound chip the lines run at 12 Mbit/s, where controlled impedance is not
  needed. No track runs on the top layer over the hub or the headphone amplifier, so the ground plane there is
  whole (both chips take their ground through a via in their exposed pad; the RP2040 through five).
  Around the RP2040 the tracks are 0.2 mm (its pins are 0.4 mm apart); the matrix lines are widened to 0.3 mm
  wherever they have room.
- **Sound card**: designed from the datasheets and C-Media's reference design, not tested yet. The CM108B is
  rated 0–70 °C. The microphone bias (1.2 kΩ + 2.2 kΩ) suits phone headsets; try a couple of headsets. Very
  sensitive in-ear earphones may hiss slightly at 0 dB gain: close JP3 (−6 dB). Unplugging the keyboard while
  listening may make a click in the headphones: the amplifier and the sound chip lose their supply together.
- **USB hub**: the CH334P announces itself as self-powered (its default), which lets the keyboard ask for its
  450 mA; check it on the first board (macOS: System Information → USB; Linux: `lsusb -v`).
- **Headset jack**: its four contacts were matched to the drawing of a near-identical jack (the maker's drawing
  does not name them). Before ordering many boards, check one loose PJ-320D-4A with a meter and a 4-pole plug:
  pad S = sleeve, R2 = ring 2, R1 = ring 1, T = tip.
