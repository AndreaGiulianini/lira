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

The electronics (power, USB, programming) **follow the BlueMicro840**, a keyboard controller built with the
same E73 module, assembled by JLCPCB and sold for years, taken from its netlist. The differences (a different
charger chip, a USB hub in front of the module, ESD protection, a power switch, a reset button, a higher-impedance
battery divider…) are listed in the schematic and in `5-schematic-and-checks/differences-from-bluemicro840.txt`. The one addition
the BlueMicro840 does not have, the **built-in sound card** (a USB hub and a USB audio chip behind the USB-C
port), follows the manufacturer's reference design (C-Media CM108B demo board).

| Block | Choice | Notes |
|---|---|---|
| Microcontroller | Ebyte **E73-2G4M08S1C** module (nRF52840 + ceramic antenna) | Bluetooth already certified, JLCPCB can assemble it (LCSC C356849) |
| Power | **AP2112K** 3.3 V regulator on VDD and VDDH (like the BlueMicro840) | The chip runs at 3.3 V from the start: to load the bootloader, an SWD probe costing a few euros is enough (for example a Raspberry Pi Pico, §4) |
| USB / battery selection | B5819W Schottky diode from USB, SI2301 MOSFET from the battery | With USB connected, the battery is cut off automatically |
| Charging | **MCP73831**, 100 mA (200 mA if you close jumper JP1): same pins as the BlueMicro840's TP4054, but stable without a battery | The white LED is on while charging and off when the battery is full, without USB and without a battery. It only charges with the power switch ON |
| Without a battery | The board also works from the USB cable alone: simply do not fit the battery | Bluetooth works too, but only while the cable powers the keyboard; the battery level then reads at random |
| USB-C | HRO TYPE-C-31-M-12, USBLC6-2SC6 ESD protection, 4.7 µF on VBUS | Standard JLCPCB parts |
| USB hub | WCH **CH334P** (USB 2.0), 12 MHz crystal, right behind the USB-C port | The module is on hub port 3, the sound card on port 2: over the cable the computer sees a hub with a keyboard and a headset |
| Sound card | C-Media **CM108B** (USB audio, no drivers on macOS / Windows / Linux) + TI **TPA6132A2** headphone amplifier, 3.5 mm **headset jack** at the back | Headphones and microphone (4-pole CTIA plugs, as on phones and Macs; plain 3-pole headphones work too). A switch (TPS22919) controlled by the firmware powers it **only in USB mode**: in Bluetooth mode, even with the cable plugged in, the computer sees no sound card |
| Power switch | **C&K JS102011SAQN** (300 mA) on the battery + line, as in ZMK keyboards | OFF = battery disconnected (no charging); on USB the keyboard works anyway. JP2 bypasses it |
| Battery level | 10 MΩ / 10 MΩ divider with 10 nF on P0.31 (BlueMicro840: 806 kΩ / 2 MΩ; higher here so the charger can tell when no battery is fitted) | macOS shows the percentage in the Bluetooth menu |
| Clock | 32.768 kHz crystal with 2 × 18 pF | 18 pF centres the 12.5 pF load (the BlueMicro840 uses 22 pF) |
| Matrix | 4 rows × 17 columns, 1N4148W diodes (column → row) | The firmware takes the pins from the PCB automatically |
| Indicators | White LED = charging; red LED on P1.04 = Caps Lock, blinks in the bootloader | Visible through the rear window |
| Reset button | Double press = update mode | Right of the module; reachable with a paperclip through the hole under the case |
| Test pads | SWDIO, SWCLK, 3V3, GND, RESET, VBUS, VBAT, VIN | On the back: the five SWD pads next to the module, in one 2.54 mm column (a pogo-pin clip reaches them all); VBUS, VBAT and VIN next to the charger; every pad labelled on the silkscreen |

All SMD components are **on the bottom side** (single-sided JLCPCB assembly). The top side has only the
switches.

## 1. Ordering the PCB (JLCPCB)

1. Upload `production/1-pcb-jlcpcb/gerber-pcb.zip`. Options: 2 layers, FR4, **1.6 mm**, any colour
   (it stays hidden), **ENIG** finish (flat pads for the fine-pitch chips: 0.4 mm pins on the RP2040, 0.5 mm on the hub, sound chip and amplifier; lead-free HASL also works). The USB-C, the headset jack and the power switch stick out past the back edge: if JLCPCB asks for edge rails, accept them on the **left and right** edges.
2. Turn on **PCB Assembly** → *Assemble bottom side*: 5 PCBs (JLCPCB's minimum), 2 of them assembled (the minimum). Tick *Confirm parts placement* so that you can check the rotations below before production.
3. Upload `bom.csv` and `cpl.csv` from the same folder.
4. **Check the placement preview**, part by part. The rotations depend on JLC's footprints and sometimes need
   to be corrected by 90°/180°:
   - E73: antenna (the side without pads) **at the rear edge** of the board;
   - USB-C: opening towards the edge; power switch: lever towards the edge;
   - 1N4148W diodes and B5819W Schottky: cathode stripe towards pad 1;
   - LEDs: cathode (pad 1) as in the footprint;
     JLCPCB's own LED drawing calls the anode pin 1, so its pin-1 dot will sit on the other pad: judge the LEDs by
     their cathode mark, not by the dot;
   - 12 MHz crystal of the hub (4 pads, next to the hub): pin-1 mark as in the footprint; turned by 90° its
     contacts land on the ground pads and the hub does not start;
   - MCP73831, AP2112K, SI2301, USBLC6, CH334P (hub), CM108B (sound chip), TPA6132A2 (amplifier), TPS22919
     (switch): pin 1 in the right corner (compare with
     `kicad/lira.kicad_pcb`);
   - battery connector J2: its pin 1 is + (marked on the silkscreen); turned by 180° it reverses the battery and destroys the charger;
   - headset jack: opening at the rear edge (it sticks out of the board by 1.8 mm; the USB-C by 0.4 mm);
   - hot-swap sockets: their two pads on top of the PCB pads.
5. Choose **Standard** assembly: the E73 module is a Standard-only part and JLCPCB X-rays it; with Standard assembly every part type has a loading fee, and JLCPCB adds the edge rails and fiducials the board needs. "Extended" parts: module, sockets, charger, regulator, 18 pF capacitors, USB-C, ESD, JST, power switch, and for the
   sound card the hub, the sound chip, the amplifier, the switch and the jack. This is normal for a wireless
   keyboard.

## 2. The plate: cut by JLCPCB, laser cut or 3D printed

The switches clip into the plate, and the plate is what holds the keyboard together: its 6 ears and 3 back tabs
are screwed to the top frame, and the PCB hangs from the switches. The three versions have the same outline,
holes and openings, so they are interchangeable (same screws, same case).

- **Cut by JLCPCB, FR4 1.6 mm** (recommended: flat and stiff): upload `production/2-plate/jlcpcb/gerber-plate.zip`
  as a normal 2-layer 1.6 mm PCB, with no assembly. The file has no copper, only the outline and the solder mask;
  JLCPCB mills it like any board. Colour: black (looks good under warm grey keycaps) or white. Add a remark to the order (“plate: no copper, outline and holes only”), and choose *Remove Mark*, or JLCPCB prints its order number on the visible plate.
  For the wireless version keep to FR4 or the printed plate: a metal plate sits 19 mm from the Bluetooth antenna and can shorten its range.
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
| 3.7 V LiPo battery **603450** (~1200 mAh) | With a protection circuit and a **JST-PH 2.0** connector, at most 52 × 35 × 6.5 mm. **Check the polarity** with a multimeter: + goes to pin 1 (marked on the PCB) |
| Screws and small hardware | See the README |
| Programmer (needed only once) | Raspberry Pi Pico (or Pico 2, ~5 €) with the official *debugprobe* firmware and 3 jumper wires. You don't need to buy it if you already have one of the alternatives in §4 |

## 4. First power-up and programming

Do these steps **before** you fit the switches and the case.

1. **Power check**: plug in the USB-C (no battery). On the test pads you should measure about 5 V on
   **VBUS**, 4.6–4.8 V on **VIN** (after the diode) and 3.3 V on **3V3**, all relative to GND. The white
   charging LED stays off with no battery. The computer should already find a **USB hub**; the **USB audio
   device** ("USB Audio Device" / C-Media) appears only once the firmware runs in USB mode (step 3), because the
   firmware switches the sound card on.
2. **Bootloader** (only once). Connect the Pico running *debugprobe*:
   GP2 → **SWCLK**, GP3 → **SWDIO**, GND → **GND** (test pads on the back, next to the module).
   The keyboard stays powered from its own USB-C. Then, with [probe-rs](https://probe.rs) installed:
   ```sh
   probe-rs download --chip nRF52840_xxAA --binary-format hex --chip-erase \
       production/4-firmware/bluemicro_nrf52840_bootloader-0.11.0_s140_6.1.1.hex
   probe-rs reset --chip nRF52840_xxAA
   ```
   This is the official BlueMicro840 bootloader (same module, same LED pins). If probe-rs says the
   chip is protected, first run `probe-rs erase --chip nRF52840_xxAA --allow-erase-all`.

   **Can you do this without buying a Pico?** Not without an SWD probe: a new nRF52840 has no USB bootloader
   built in (unlike the RP2040 or ATmega32U4), so the first time the only way in is SWD. After that,
   updates always go over USB. But the probe does not have to be a Pico:
   - **any RP2040 or RP2350 board** you already have, with pins GP2 and GP3 reachable (Pico, Pico 2,
     RP2040-Zero, XIAO RP2040, Pro Micro RP2040…): drag the *debugprobe* file onto it and use it as above;
     afterwards, put it back the way it was;
   - **a Raspberry Pi** (Zero, 3, 4 or 5) with OpenOCD on the GPIO pins;
   - **a J-Link or CMSIS-DAP/DAPLink probe**;
   - **a borrowed one**: you only need it for five minutes;
   - **JLCPCB** offers programming during assembly on request, quoted case by case: it will almost
     certainly cost more than a Pico.

   Avoid cloned **ST-Link** dongles. Recent nRF52840s leave the factory with debug protection
   (APPROTECT) turned on, and an ST-Link usually cannot send the command that removes it (OpenOCD with an
   ST-Link does not allow it). The cheapest probe that
   is sure to work is an RP2040-Zero (about 3 €).
   The SWDIO (37) and SWDCLK (39) pads are the ones used by the BlueMicro840 and nrfmicro: the Ebyte datasheet
   table has a typo in the name of the chip ball, not in the pins.
3. **Firmware**: press the reset button twice in quick succession (a paperclip through the hole under the case
   is enough). A drive called **BLUEMICRO** appears: drag the `.uf2` file from `production/4-firmware/`
   onto it. The red LED blinks while the bootloader is waiting. On macOS 14 and later the Finder may stop the copy
   with error −36: copy it from the Terminal instead, `cp -X production/4-firmware/lira.uf2 /Volumes/BLUEMICRO/`.
4. **Vial**: open <https://vial.rocks> in Chrome (or the Vial app) with the keyboard connected over USB. To
   unlock the protected features, hold **Esc + Return**.
5. **Bluetooth**: hold **fn** (the 1u key to the right of shift) and press **Q / W / E** for profiles 1–3.
   Holding them for 5 s clears the pairing of that profile. **fn + R** switches between USB and Bluetooth.
   The sound card follows that choice: it is on only in USB mode. In Bluetooth mode the keyboard still types over
   the cable while no Bluetooth host is connected, but the computer sees no sound card: press fn + R for USB.
6. **Future updates**: **fn + Esc** restarts into the bootloader, then drag the new `.uf2` onto the drive. A new
   firmware starts again from its default keymap and forgets the Bluetooth pairings: save your layout first (Vial,
   *File → Save current layout*), load it back afterwards, and pair the computers again.

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
  - Q/W/E Bluetooth profiles (hold one for 5 s to forget the computer paired to it), R USB/Bluetooth
  - Z…N media keys (mute, volume −, volume +, play/pause, previous, next)
  - Backspace = forward delete
  - Esc = bootloader

### Testing and troubleshooting

- **Before the first plug-in**, look at the hub and the sound chip with a loupe for solder bridges, and plug in without the battery, through a USB power meter: the board should draw roughly 30–150 mA. Much more means a short: unplug at once.
- **Matrix test before closing the case**: after step 4 of §5 (plate, PCB and switches are one unit, still out of the case), plug in, open Vial, hold **Esc + Return** to unlock it and use *Matrix tester*: press every key once. A key that does nothing is usually a switch pin bent under the socket.
- **No BLUEMICRO drive after the double press of reset**: the bootloader is not there (repeat §4 step 2 with the probe) or the press was too slow. With the probe connected, `probe-rs info --chip nRF52840_xxAA` shows whether the chip answers at all.
- **No hub / no audio device**: measure VBUS (about 5 V) and the hub's 12 MHz crystal area for bridges; the sound card needs the hub, so without a hub there is neither keyboard nor headset.
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
7. **Battery**: stick a 1 mm double-sided foam sheet on the bottom of the pocket under the numpad, then press the battery onto it (it must stay put when the bottom is turned over onto the frame), pushed to
   the left, with the cable coming out on the right. Plug it into the JST connector on the underside of the PCB
   (mind the polarity!): with the frame face down, the PCB's underside is right in front of you. Before closing, unplug the cable and find the switch's ON position: the battery voltage appears on the VIN test pad.
8. **Close**: lower the bottom straight down onto the frame (the power switch lever, the USB-C port and the
   headset jack enter their windows from above, the plate's ears drop into their pockets), then fasten it with the M3 screws: 8 × M3 × 12
   (front and sides) and 3 × M3 × 20 (the back ones: they go through the PCB's large holes and the plate's back
   tabs, clamping the back of the plate against the frame). Some holes are up to 21 mm deep and tilted by 8°: you
   need a long 2.5 mm hex key (1/4" screwdriver bits do not fit).
9. Turn the keyboard over, fit the keycaps, and stick on the Ø 12 mm rubber feet.

At the back, through the windows, you will find:
- the USB-C port;
- further right, the 3.5 mm headset jack (headphones / headset with microphone; it works in USB mode, fn + R, with the cable going to a computer);
- the power switch, which you move with a fingernail (it sits 0.6 mm inside the wall, so it can't be bumped by accident);
- the two LEDs (white = charging, red = Caps Lock / bootloader).

The LEDs are under the PCB and face the bottom half: you see their reflection in the window from behind, not
from your typing position. To see them from the front you would need side-firing LEDs, which means a different PCB.

You press the reset button from below with a paperclip, through the small hole in the bottom half (a guide
leads it to the button). To reach the battery or the underside of the PCB, undo the 11 M3 screws and lift
the bottom off: everything else stays together on the top frame.

## 6. How the circuit is checked

Nothing here has been built yet, so the checking relies on four things that are independent of each other and run
on every `make`:

1. **A circuit copied from boards that exist.** Power, USB and programming follow the BlueMicro840 (same module,
   assembled by JLCPCB) and the nrfmicro; the sound card follows C-Media's CM108B/CM119B demo board. The
   differences from both are listed in `5-schematic-and-checks/differences-from-bluemicro840.txt`.
2. **The schematic is generated from the same description that generates the PCB**, with KiCad's ERC:
   `erc-kicad.txt`.
3. **Pin-by-pin consistency** between circuit, PCB and schematic: `consistency-check.txt`.
4. **Datasheet tests** written independently of the design, each test citing the datasheet page it is based on:
   `datasheet-checks.txt`.

To review the circuit yourself, open `kicad/schematic/` in KiCad.

## 7. How the case is checked

An **automatic fit check** (`3-case-3d-print/fit-check.txt`, redone on every `make`) models everything that goes
inside the case from the datasheet dimensions and compares it with the printed pieces, read back from the exported
STL/STEP files:

- **collisions**, with at least 0.3 mm of clearance: PCB, components under the board with their heights, hot-swap
  sockets, switch pins, stabilizer screws, plate, keys at rest and pressed, battery and cable;
- **assembly**: the path the PCB, plate and top frame follow while they are lowered into place;
- **ports**: a bulky USB-C plug (13 × 7.5 mm), a 3.5 mm plug up to 9 mm across, power switch travel, LEDs visible
  from behind, reset hole clear to the button;
- **screws**: where the head rests, where the tip ends, how many millimetres of thread engage the insert, how much
  plastic surrounds each insert;
- **walls**: thickness measured at about 400,000 points (minimum 1.2 mm; below 0.8 mm is an error);
- **printing**: overhangs, bridges and ledges in the print orientation; size against the bed.

It reports 0 errors and three warnings: two 7–8 mm² ledges at 50° under the rear corners, which print without
supports, and a 0.93–0.99 mm spot at the floor of the headset-jack window. Print the bottom with at least
3 perimeters so that spot is solid.

One limitation would need a different PCB to fix: the status LEDs sit under the PCB facing the bottom, so from the
typing position you see their reflection in the rear window, not the LEDs themselves.

## 8. What still needs checking on the real thing

Before ordering 5 boards, it is wise to order 2.

- **Component rotations** in the JLCPCB preview: they must be checked by hand (see §1).
- **Plate openings for the stabilizers**: 7 × 16 mm, wider than the Cherry standard. In theory they work
  with any screw-in stabilizer, but they have not been tested.
- **Case tolerances** (0.5 mm around the keys and at the front and back of the PCB, 1 mm at its sides, 0.5 mm
  between the rear bosses and the PCB's 7.4 mm holes,
  0.6 mm around the plate's ears): they depend on the printer. That is why you should print a test corner
  first (§5).
- **Plate flush on the frame**: the M2 inserts must not stand proud of the frame's underside (§5).
- **Battery reading**: the divider is 10 MΩ + 10 MΩ (so the charger can tell when no battery is fitted), which makes
  it sensitive to leakage: every 10 nA through flux residue or the pin shifts the reading by about 0.1 V. Compare
  the level Vial/macOS shows with a multimeter on the battery; clean the flux around P0.31 / R105 / R106 if it is off.
- **Routing**: automatic (Freerouting; the few connections it leaves open or crossing are redone by a small
  router in `source/pcb/repair.py`), passes DRC, not optimized by hand, except the USB high-speed pair
  (480 Mbit/s, from the USB-C port through the ESD chip to the hub), which the generator draws itself: about
  20 mm on the bottom layer, no vias, lengths within 0.5 mm. For about a third of the way the two lines run side by
  side, 0.5 mm apart with ground 0.2 mm beside them (about 96 Ω); around the ESD chip they split, D+ through its
  middle and D− round its side as ST lays it out, and there the impedance is higher. The top ground plane above
  them is crossed only by the VBUS link from the receptacle, at right angles. Over 20 mm this is normally harmless;
  and if the hub ever fell back to full speed (12 Mbit/s), the keyboard and the sound card would not notice.
  Between the hub and the module and the sound chip the lines run at 12 Mbit/s, where controlled impedance is not
  needed. No track runs on the top layer over the hub or the headphone amplifier, so the ground plane there is
  whole (both chips take their ground through a via in their exposed pad).
- **Sound card**: designed from the datasheets and C-Media's reference design, not tested yet. The CM108B is
  rated 0–70 °C. Listen to the headphones the first time with the keyboard in USB mode and also connected over
  Bluetooth to another device (a phone on profile 2), so that the radio transmits while you listen: it is 7 cm away. The
  microphone bias (1.2 kΩ + 2.2 kΩ) suits phone headsets; try a couple of headsets. Very sensitive in-ear
  earphones may hiss slightly at 0 dB gain: close JP3 (−6 dB).
- **USB hub**: the CH334P always announces itself as self-powered (this package has no pin to say otherwise) and declares 100 mA, which is what lets the keyboard ask for 450 mA; the board draws about 0.3 A while charging (0.4 A with JP1 closed). Fine on a computer's port; avoid phones, tablets and bus-powered hubs. Check it on the first board (macOS: System Information → USB; Linux: `lsusb -v`).
- **Bluetooth range**: try it with no cable, with a charger cable and with a computer cable (the USB hub's 480 Mbit/s link is 13–21 mm from the antenna), with the sound card playing, and with the plate you chose.
- **Battery polarity**: a cell plugged in reversed with the switch ON destroys the charger: measure the cell's plug before connecting it, every time.
- **Battery life**: measure the current from the cell when idle; `dcdc_reg1 = true` in `keyboard.toml` (once the board works) roughly halves the radio's current.
- **Headset jack**: its four contacts were matched to the drawing of a near-identical jack (the maker's drawing
  does not name them). Before ordering many boards, check one loose PJ-320D-4A with a meter and a 4-pole plug:
  pad S = sleeve, R2 = ring 2, R1 = ring 1, T = tip.
- **Battery**: the charging circuit does not protect against reversed polarity (a cell connected the wrong way round
  destroys the charger, as on the reference boards). Always measure before connecting. Use a cell with a
  protection circuit: the keyboard has no low-battery shutdown.
- **Spare jumpers**: if the power switch does not work, JP2 bypasses it; if charging at 100 mA
  is too slow, JP1 raises it to 200 mA. Close them with a blob of solder.
