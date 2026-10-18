# Lira — build guide: ordering, parts, programming, assembly

> [!WARNING]
> **This keyboard has never been built.** It is a design only: no prototype of either version (wireless on branch
> `main`, wired on branch `rp2040`) has ever been ordered, assembled or powered on, and nothing here has been tested
> on real hardware. The circuit, PCB, case and firmware are generated and checked automatically and reviewed on paper,
> but passing those checks does not make a working board: there may be mistakes that only a real prototype would
> reveal. **Do not put it into production, sell it or order it in quantity.** If you build one anyway, treat it as an
> untested design: order the minimum quantity and expect to debug it yourself.

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
| Power | **AP2112K** 3.3 V regulator from the USB 5 V (it also supplies the USB hub); the RP2040's own regulator makes its 1.1 V core | 0402 capacitors at the RP2040's supply pins, 1–3 mm from them on the same side: 100 nF at the I/O, ADC and core pins (two I/O pins in the middle of the matrix lines share their neighbour's through a tie under the chip, and USB_VDD shares IOVDD 49's, as Raspberry Pi's own design does), 1 µF at the internal regulator's input and output |
| USB-C | HRO TYPE-C-31-M-12, USBLC6-2SC6 ESD protection, SMF5.0A surge clamp, 4.7 µF + 1 Ω on VBUS | Standard JLCPCB parts; 5.1 kΩ on CC1 / CC2 (a plain USB device); the 1 Ω damps the ringing of the cable when it is plugged in |
| USB hub | WCH **CH334P** (USB 2.0), 12 MHz crystal, right behind the USB-C port | The RP2040 is on hub port 3 (through 27 Ω), the sound card on port 2: over the cable the computer sees a hub with a keyboard and a headset |
| Sound card | C-Media **CM108B** (USB audio, no drivers on macOS / Windows / Linux) + TI **TPA6132A2** headphone amplifier, 3.5 mm **headset jack** at the back | Headphones and microphone (4-pole CTIA plugs, as on phones and Macs; plain 3-pole headphones work too). Switched by the RP2040: on once the computer has set the keyboard up (a TPS22919 switch starts it slowly, so the hub does not see a dip), the amplifier 0.2 s later; the amplifier goes off while the computer sleeps and as soon as the USB 5 V starts to fall when the cable is pulled, so there is no click |
| Matrix | 4 rows × 17 columns, 1N4148W diodes (column → row) | The firmware takes the pins from the PCB automatically |
| Indicator | Red LED = Caps Lock | Visible through the rear window |
| Buttons | **BOOT** (restarts into the USB boot ROM when held while the keyboard starts) and **RESET** | BOOT is reachable with a paperclip through the hole under the case; RESET only with the case open |
| Test pads | SWCLK, SWDIO, RESET, GND, 3V3, VBUS | On the back: the SWD pads in one row right in front of the RP2040 (CLK, DIO, RST, GND; 3V3 behind the chip), for debugging only; every pad labelled on the silkscreen |

All SMD components are **on the bottom side** (single-sided JLCPCB assembly). The top side has only the
switches.

## 1. Ordering the PCB (JLCPCB)

1. Upload `production/1-pcb-jlcpcb/gerber-pcb.zip`. Options: 2 layers, FR4, **1.6 mm**, any colour
   (it stays hidden), **ENIG** finish (flat pads for the fine-pitch chips: 0.4 mm pins on the RP2040, 0.5 mm on the hub, sound chip and amplifier; lead-free HASL also works). The USB-C, the headset jack stick out past the back edge: if JLCPCB asks for edge rails, accept them on the **left and right** edges.
2. Turn on **PCB Assembly** → *Assemble bottom side*: 5 PCBs (JLCPCB's minimum), 2 of them assembled (the minimum). Tick *Confirm parts placement* so that you can check the rotations below before production.
3. Upload `bom.csv` and `cpl.csv` from the same folder.
4. **Check the placement preview**, part by part. The rotations depend on JLC's footprints and sometimes need
   to be corrected by 90°/180°:
   - RP2040 (QFN-56) and W25Q128 flash (SOIC-8): pin-1 dot in the right corner (compare with
     `kicad/lira.kicad_pcb`); a QFN turned by 90° still sits on its pads, so only the dot tells;
   - USB-C: opening towards the edge;
   - 1N4148W diodes: cathode stripe towards pad 1;
   - LED: cathode (pad 1) as in the footprint;
     JLCPCB's own LED drawing calls the anode pin 1, so its pin-1 dot will sit on the other pad: judge the LEDs by
     their cathode mark, not by the dot;
   - the two 12 MHz crystals (4 pads; one next to the hub, one in front of the RP2040): pin-1 mark as in the
     footprint; turned by 90° their contacts land on the ground pads and the chip does not start;
   - AP2112K, USBLC6, CH334P (hub), CM108B (sound chip), TPA6132A2 (amplifier), TPS22919 (switch): pin 1 in the
     right corner;
   - the SMF5.0A surge clamp next to the USB-C: its cathode band towards the receptacle's side (the VBUS track);
   - headset jack: opening at the rear edge (it sticks out of the board by 1.8 mm; the USB-C by 0.4 mm);
   - hot-swap sockets: their two pads on top of the PCB pads.
5. Choose **Economic** assembly: no part of this board needs Standard. "Extended" parts (a loading fee per part type): the RP2040, its crystal, its 27 Ω USB resistors, the sockets, USB-C, ESD, the VBUS surge clamp (SMF5.0A), the regulator, and for the sound card the hub, the sound chip, the amplifier, the switch and the jack (the flash is a Basic part). The amplifier (TPA6132A2, LCSC C69901) has only a few hundred in stock: check it before anything else.

## 2. The plate: cut by JLCPCB, laser cut or 3D printed

The switches clip into the plate, and the plate is what holds the keyboard together: its 6 ears and 3 back tabs
are screwed to the top frame, and the PCB hangs from the switches. The three versions have the same outline,
holes and openings, so they are interchangeable (same screws, same case).

- **Cut by JLCPCB, FR4 1.6 mm** (recommended: flat and stiff): upload `production/2-plate/jlcpcb/gerber-plate.zip`
  as a normal 2-layer 1.6 mm PCB, with no assembly. The file has no copper, only the outline and the solder mask;
  JLCPCB mills it like any board. Colour: black (looks good under warm grey keycaps) or white. Add a remark to the order (“plate: no copper, outline and holes only”), and choose *Remove Mark*, or JLCPCB prints its order number on the visible plate.
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
| Keycaps | Agar mini set + **numpad kit**: you need a 2u vertical Enter, a 2u 0, a 1u + and a 1u − (most numpad kits only have a 2u +) |
| **Screw-in PCB** stabilizers | 2 × 2u (numpad 0 and Enter) + 2 for the **3u** spacebars: check that the kit has wires for 3u (38.1 mm spacing) |
| Screws and small hardware | See the README |
| A paperclip | For the BOOT button under the case (only if a firmware update ever goes wrong) |

## 4. First power-up and programming

Do these steps **before** you fit the switches and the case. Nothing else is needed than a USB-C cable: the RP2040
has its USB bootloader in ROM, so there is no programmer to buy and no bootloader to flash.

1. **Power check**: plug in the USB-C. On the test pads you should measure about 5 V on **VBUS** and 3.3 V on
   **3V3**, relative to GND (and 1.1 V on either pad of C12, the RP2040's core supply). The computer should find a
   **USB hub** and, because the flash is still empty, a drive called **RPI-RP2**: the RP2040's boot ROM, waiting for a
   firmware. The sound card stays off until the firmware runs (its switch has a pull-down).
2. **Firmware**: drag `lira.uf2` from `production/4-firmware/` onto **RPI-RP2**. The drive disappears and the
   keyboard starts; a moment later the **USB audio device** appears ("USB Audio Device" / C-Media). On macOS 14 and later the Finder may stop the copy with error −36: copy it from the Terminal
   instead, `cp -X production/4-firmware/lira.uf2 /Volumes/RPI-RP2/`.
3. **Vial**: open <https://vial.rocks> in Chrome (or the Vial app) with the keyboard connected. To unlock the
   protected features, hold **Esc + Return**.
4. **Future updates**: **fn + Esc** (or "Reboot to bootloader" in Vial) restarts into the boot ROM: the RPI-RP2 drive
   appears, drag the new `.uf2` onto it. If a firmware ever does not start, **hold the BOOT button** (a paperclip
   through the small hole under the case) **while you plug in the cable**: the RP2040 then always starts in the boot
   ROM, whatever is in the flash. With the case open, holding BOOT and pressing RESET does the same. A new firmware
   starts again from its default keymap: save your layout first (Vial, *File → Save current layout*) and load it
   back afterwards.
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

### Testing and troubleshooting

- **Before the first plug-in**, look at the RP2040 (QFN, 0.4 mm pins) and the hub with a loupe for solder bridges, and plug in through a USB power meter: the whole board should draw roughly 60–150 mA. Much more means a short: unplug at once.
- **Matrix test before closing the case**: after step 4 of §5 (plate, PCB and switches are one unit, still out of the case), plug in, open Vial, hold **Esc + Return** to unlock it and use *Matrix tester*: press every key once. A key that does nothing is usually a switch pin bent under the socket.
- **No RPI-RP2 drive**: measure 3V3 (test pad) and 1.1 V (C12). If both are there, the crystal or the flash is the usual suspect (rotation in JLCPCB's placement, a bridge on the flash pins). Holding BOOT while plugging in must always bring the drive back, whatever is in the flash.
- **No hub / no audio device**: measure VBUS (about 5 V), 3V3 (the hub runs from it) and the hub's 12 MHz crystal area for bridges; the sound card needs the hub, so without a hub there is neither keyboard nor headset. The audio device only appears with the firmware running and the keyboard set up by the computer: then the sound card's 5 V (C113, about 5 V) and GPIO12 (U8's ON pin, 3.3 V) are on.
- **Headphones silent**: check that the computer's output is the C-Media “USB Audio Device” and that the plug is pushed fully home (the jack sits slightly inside the back wall).

## 5. Case: printing and assembly

1. **Print** the 4 pieces in the `3-case-3d-print/` folder, without supports:
   - top frame halves lying on their flat underside (the side the plate screws to), deck up: the STL files are exported tilted, as assembled, so use the slicer's “lay on face” on that flat underside;
   - bottom halves the way they sit on the desk.

   It is a good idea to print a test corner first, to check your printer's tolerances (cut a back corner of a bottom half in the slicer: it has a screw hole, an insert hole and a dowel pin hole).
   - Settings: 3 perimeters, 5 solid layers on top and 4 on the bottom; 15 % gyroid infill for the top frame,
     8 % (or "lightning") for the bottom halves. About 300–320 g of PLA in total (see the README for why it is
     not worth hollowing out the case by designing cavities).
   - Surfaces tilted by only a few degrees (the chamfers on the top frame and the resting surfaces inside the
     bottom halves) come out stepped: use the slicer's variable layer height, or 0.12 mm layers.
   - The case is 377 mm long: if your filament shrinks more than usual (some PETG and ABS), scale the pieces
     in the slicer before printing.
2. **Heat-set inserts**, all in the flat underside of the top frame (with the frame lying face down on the
   table the holes are vertical):
   - M2 (6) for the plate's ears, at the front and at the sides of the key wells;
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
   its ears (4 at the front, 1 per side): they are all outside the PCB, so a 1.5 mm hex key reaches them. From
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
  router in `source/pcb/repair.py`), passes DRC, not optimized by hand, except the connections the generator draws
  itself: around the RP2040 every supply pin to its capacitor, the 1.1 V core supply (under the chip), the crystal,
  the QSPI flash, the USB resistors and the SWD lines; the two lines that switch the sound card, along the bottom of the
  strip; the hub's crystal and supply; the codec's analog supply; the amplifier's supply and enable; the jack's ESD
  clamps; the VBUS protection; the ground pins of the chips; and the USB high-speed pair
  (480 Mbit/s, from the USB-C port through the ESD chip to the hub): about
  20 mm on the bottom layer, no vias, lengths within 0.5 mm. For about a third of the way the two lines run side by
  side, 0.5 mm apart with ground 0.2 mm beside them (about 96 Ω); around the ESD chip they split, D+ through its
  middle and D− round its side as ST lays it out, and there the impedance is higher. Over 20 mm this is normally
  harmless; and if the hub ever fell back to full speed (12 Mbit/s), the keyboard and the sound card would not notice.
  Between the hub and the RP2040 and the sound chip the lines run at 12 Mbit/s, where controlled impedance is not
  needed. No track runs on the top layer over the RP2040 (with its capacitors and crystal), the hub or the headphone
  amplifier, so the ground plane there is whole (the hub and the amplifier take their ground through a via in their
  exposed pad, the RP2040 through four, every capacitor through its own).
  Around the RP2040 the tracks are 0.2 mm (its pins are 0.4 mm apart); the matrix lines are widened to 0.3 mm
  wherever they have room.
- **Sound card**: designed from the datasheets and C-Media's reference design, not tested yet. The CM108B is
  rated 0–70 °C. The microphone bias (1.2 kΩ + 2.2 kΩ) suits phone headsets; try a couple of headsets. Very
  sensitive in-ear earphones may hiss slightly at 0 dB gain: close JP3 (−6 dB). The firmware turns the amplifier
  off when it sees the USB 5 V start to fall, before the sound chip loses its supply: unplug the keyboard while
  listening and check there is no click.
- **USB hub**: the CH334P always announces itself as self-powered (this package has no pin to say otherwise) and declares 100 mA, while the board draws about 100 mA idle and up to ~330 mA at full headphone volume. Fine on a computer's port; avoid phones, tablets and bus-powered hubs. Check on the first board what the computer sees (macOS: System Information → USB; Linux: `lsusb -v`): the hub, the RP2040 (100 mA) and the sound chip (100 mA).
- **The RP2040's power and clock layout**: every capacitor is now drawn to its pin on the bottom layer and the crystal sits next to its pins (distances in `datasheet-checks.txt`, test G01), over a whole ground plane. On the first board, still look at 1.1 V on C12 with an oscilloscope while typing and playing music (steady 1.10 V, no ringing), and run the keyboard for a day.
- **Matrix**: the firmware waits for the rows to settle after each column (a patch to RMK, `source/firmware/patch_rmk.py`); still, try every key and a few chords in Vial's matrix tester and look for a key that shows up in the next column.
- **Hot-plug**: plug the board a dozen times into a charger that gives 5.25 V or more, with an oscilloscope on VBUS (TP6) if you have one: the peak should stay under 6 V (the sound card's switch is rated 6 V; the hub now runs from 3.3 V, and VBUS has a surge clamp and a damped bulk capacitor).
- **Headset jack**: its four contacts were matched to the drawing of a near-identical jack (the maker's drawing
  does not name them). Before ordering many boards, check one loose PJ-320D-4A with a meter and a 4-pole plug:
  pad S = sleeve, R2 = ring 2, R1 = ring 1, T = tip.
