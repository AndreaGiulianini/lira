# Lira USB — RP2040, USB-only keyboard with a built-in headset DAC

A second take on [Lira](../lira): same 40% + left-numpad layout, same headset jack and sound
card, but **USB only** — no Bluetooth, no battery, no charger, no antenna.

## Why

On Lira the sound card only works in USB mode (the firmware powers it off on Bluetooth), and you
cannot ship audio over BLE without a host audio profile. So **wireless and the DAC are mutually
exclusive in use**: if the jack is the point of the board, the cable is always in, and the radio,
cell, charger and power-path FET are weight you pay for and never use.

That removes the need for the nRF52840's radio and its power hardware, which makes a cheap, native-USB
MCU the better fit: **Raspberry Pi RP2040**.

## What this is, right now

A **design scaffold**, not a finished PCB. The plan, the block diagram, the pin map, the target BOM
and the reference designs are here; the generator will be forked from `../lira/source` and the
untouched blocks (USB-C + ESD + hub + CM108B + TPA6132A2 + jack, matrix, plate, case) carried over.

```
lira-usb/
├── README.md
├── docs/
│   ├── architecture.md      blocks, power tree, pin map, BOM, decisions
│   ├── migration-from-lira.md   what is reused, what is dropped, what is new
│   ├── references.md        the datasheets / reference designs to follow
│   └── open-questions.md    what must be decided before layout
└── hardware/
    └── circuit.py           first pass of the MCU + USB + power section, as data
```

## Status

| Item | State |
|---|---|
| Architecture, pin map, BOM | drafted (`docs/architecture.md`) |
| MCU + USB + power circuit (data) | first pass (`hardware/circuit.py`) |
| Audio chain (hub, codec, amp, jack) | reused from Lira (diff-checked) |
| Matrix (57 keys) | reused from Lira |
| Structural validation | **42 PASS, 0 FAIL** (`python3 hardware/validate.py`) |
| RP2040 pin table vs KiCad symbol | 57/57 match |
| Part availability | all new parts in stock |
| Independent datasheet checker | 21 PASS; 3 FAILs are E73-only checks, re-covered in `validate.py` |
| PCB layout, checks, firmware | to do |

Results in [`docs/validation.md`](docs/validation.md).

## Decisions still open

See [`docs/open-questions.md`](docs/open-questions.md). The biggest one: keep the proven
**hub + CM108B** audio (low firmware risk) or move the audio into the RP2040 (no hub/codec, but you
write USB-audio firmware).

## Generator migration status (branch `rp2040`)

- **`source/pcb/circuit.py`** — replaced with the RP2040 circuit (done).
- **`source/pcb/electronics.py`** — placement adapted to the RP2040 block (flash, crystal, decoupling,
  BOOTSEL/RUN, 27 Ω USB); the freed left area holds the SWD pads, buttons, LED and 3.3 V regulator.
  The placed board generates: **221 footprints, 142 nets, placement DRC-clean**.
- **Routing — blocked.** Freerouting does not converge in a reasonable time on the RP2040's
  0.4 mm-pitch QFN fan-out (the E73 module's castellated pads were far easier). Next step: add
  short **escape vias** for the RP2040/QFN pads before the autorouter (as Lira does for the E73's
  inner pads), or hand-route the RP2040 fan-out.
- **`source/pcb/gen_schematic.py`** — needs the `lira:RP2040` symbol and a rewritten `build()`
  (the current one places the removed E73/charger parts). `make verify` therefore does not run yet.
- **Firmware** — QMK + Vial for RP2040 (RMK does not support it); not started.
