# Reference designs and datasheets

Follow these; do not invent. The audio section is already proven on Lira, so its references are the
same.

## MCU
- **RP2040 datasheet** (Raspberry Pi) — pinout, power, USB.
- **RP2040 Hardware Design Guide** (Raspberry Pi) — the "minimal design example": crystal, QSPI flash,
  decoupling, USB, BOOTSEL/RUN. This is the primary source for `hardware/circuit.py`.
- **Raspberry Pi Pico schematic** (RP2040 section) — a working, minimal reference to cross-check
  decoupling values and the flash wiring.
- **W25Q128JV datasheet** — QSPI flash pinout, decoupling, the CS pull-up.

## USB / hub / audio (reused from Lira)
- **USB Type-C spec** — 5.1 kΩ Rd on CC1/CC2 for a sink.
- **USBLC6-2SC6** — flow-through ESD wiring, VBUS clamp.
- **WCH CH334P** datasheet V2.91 — hub, 12 MHz crystal with internal caps, downstream ports.
- **C-Media CM108B datasheet v1.41 + CM108B/CM119B application notes v1.50 + demo board v1.33
  sheet 4** — the codec, crystal-free, headset config, line-out, mic.
- **TI TPA6132A2 (SLOS597)** — DirectPath headphone amp, single-ended inputs, charge pump, gain
  jumpers, EN sequencing.

## Firmware
- **QMK** — RP2040 support, `RP2040` converters, Vial integration.
- **Vial** — QMK fork with the Vial protocol; RP2040 boards are supported.
- **TinyUSB** — only if the audio is moved into the MCU (Option B); UAC2 device class.

## Lira project (for reuse and cross-checks)
- `../lira/source/pcb/circuit.py` — the audio + matrix descriptions to carry over.
- `../lira/source/case/` — the case, plate and fit check (the electronics strip changes; the rest
  is reusable).
- `../lira/source/pcb/gen_plate.py`, `mount.py` — plate geometry (unchanged).
