# Open questions (decide before layout)

## 1. Audio architecture — the big one

| | **A — hub + CM108B (recommended)** | **B — RP2040 does USB audio** |
|---|---|---|
| USB | USB-C → hub → {RP2040, CM108B} | one composite device (HID + UAC2) |
| Chips | + CH334P, + CM108B | + an I²S DAC (e.g. PCM5102) |
| Firmware | QMK + Vial (keyboard); audio needs none | custom TinyUSB UAC + I²S driver |
| Risk | **low** (audio already proven on Lira) | high (new firmware) |
| BOM | slightly higher | lowest, no hub/codec |

**Recommendation: A for the first spin**, then consider B only if you want to delete the hub and own
the USB-audio firmware.

## 2. Scope of the first spin

- **Full keyboard** (57 keys + audio + case), or
- **A reduced test board**: the electronics strip only (RP2040 + USB-C + hub + codec + amp + jack +
  a handful of keys + test points), on a small board, to validate the RP2040/USB/audio before the
  big layout. Cheaper and faster to iterate; the case/plate are not needed for it.

**Recommendation:** a small test board first. The RP2040 section is the only genuinely new, unproven
block; validating it on a €5 board beats finding out on a 335 mm keyboard PCB.

## 3. RP2040 crystal

Raspberry Pi recommends the **Abracon ABM8-272-T3** (12 MHz, CL 10 pF, ESR ≤ 50 Ω). Check whether it
(or an equivalent with the same CL/ESR) is stocked at LCSC/JLC; the LCSC code in `circuit.py`
(`C20625731`) is a placeholder to verify. The load capacitors are chosen for CL 10 pF (15 pF each
with ~3 pF parasitic).

## 4. QSPI flash

`W25Q128JVS` (16 MB, C97521) or `W25Q64JVSSIQ` (8 MB, C179171). 8 MB is plenty for QMK; 16 MB costs
almost nothing and is the RP2040 maximum. Either works.

## 5. Firmware

- **QMK + Vial** on RP2040 is the mature path. RMK (used on Lira) targets nRF/ESP and does **not**
  support RP2040, so this is a framework switch, not a port.
- Decide the Vial board identity (name, VID/PID) and the keymap (the Lira keymap can be carried).
- If Option B: write the USB-audio firmware with TinyUSB.

## 6. Hot-swap sockets

Same stock issue as Lira: `C2803348` (CPG151101S11) is out of stock at JLC/LCSC. Use the substitute
`C49352235` (CPG151101S11-2, verify the footprint) or fit them by hand.

## 7. Case

The bottom body has a battery pocket and the power-switch window; both are unused now. Options:
keep the case as-is (simplest), or trim: remove the battery pocket, drop the switch window, and free
the space (the case gets lighter and prints faster). The plate and the fit check are unaffected.

## 8. Verify before layout

- RP2040 QFN-56 **ePad size** (the KiCad footprint used is `EP3.2x3.2 mm`) against the datasheet.
- The **27 Ω USB series resistors** (datasheet 1.4.2) — already in `circuit.py`.
- The **QSPI_SS pull-up** value (10 kΩ) and whether to fit it (the HDG marks it DNF for the
  W25Q128JVS but recommends having the pads).
- Whether to keep **SWD pads** (recovery only now that UF2 flashing exists).
