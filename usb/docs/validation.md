# Validation

Everything run on the first-pass `hardware/circuit.py` (RP2040 + audio + 57-key matrix, 206 parts,
572 pins, 142 nets).

## 1. Structural checks — `python3 hardware/validate.py`

```
parts 206, pins 572, nets 142
SUMMARY: 42 PASS, 0 FAIL
```

Covers: unique designators; no single-pin nets; GND/3V3/VBUS present; a decoupling capacitor on
every RP2040 supply pin (6 × IOVDD, 2 × DVDD, USB_VDD, ADC_AVDD, VREG_IN, VREG_OUT); VREG_VOUT tied
to DVDD (1.1 V core); TESTEN to GND; the 12 MHz crystal on XIN/XOUT with the load caps and the series
resistor; the flash on all six QSPI lines with VCC/GND and the QSPI_SS pull-up + BOOTSEL resistor;
27 Ω on RP USB DP/DM; hub port 3 → RP2040, port 2 → codec, upstream → receptacle; 22 Ω on the codec;
USB ESD; hub/codec/amp/jack present; no load switch; amp VDD = VBUS and EN tied high; the status LED
polarity and resistor; the 57 matrix cells (col → switch → diode, cathode to the row) mapped to
RP2040 GPIOs.

## 2. RP2040 pin table vs KiCad's symbol

`MCU_RaspberryPi:RP2040` — **all 57 pin numbers/names match** the `RP2040_PINS` table used here
(so the footprint pin map is right).

## 3. Audio carried from Lira — diff

Lira's `audio()` vs this one: **only** `U8` (TPS22919 load switch), `C130`, `R117`, `R118`, `C137`,
`D104` removed; `AUD_5V` → `VBUS` on `L101`, `L102`, `C113`, `C114`, `C133`, `R112`, `U7.VDD` and
`R113` (EN pull-up). Everything else is byte-identical. Exactly the intended change.

## 4. Part availability (JLCPCB API)

| Part | LCSC | Stock |
|---|---|---|
| RP2040 | C2040 | 51 368 |
| W25Q128JVSIQ | C97521 | 66 441 (base) |
| **ABM8-272-T3** 12 MHz crystal | C20625731 | 8 535 |
| 27 Ω 0603 | C25190 | 62 570 |
| 15 pF 0603 | C1644 | 964 793 (base) |

All audio parts are the same as Lira (already checked). BOM: **33 unique LCSC codes, 200 placements**.

## 5. Lira's independent datasheet checker

```
SUMMARY: 21 PASS, 3 FAIL, 2 WARN, 29 SKIP
```

- **3 FAILs are the checker, not the board**: it only knows the E73 module as a "module"/USB device.
  - `U03` hub port 3 "reaches nothing" — the device is the RP2040, which the checker does not know.
  - `D01` LED — anode is on RP2040 GPIO25; the checker looks for an E73 GPIO.
  - `K01` matrix — "no module": the matrix check needs an E73 to verify the row/col pins.
  The RP2040-aware equivalents of all three are in `validate.py` and pass.
- **WARN A14 — amp EN is not sequenced** (tied to VBUS). With everything on VBUS, on unplug the rail
  and EN fall together, so the amplifier stays enabled while the codec browns out. The TPA6132A2 and
  CM108B have anti-pop, so it is probably fine; **listen for a pop on unplug**. If it pops, either add
  the TPS22919 gate back (an RP2040 GPIO), or accept it.
- **WARN A06** — the microphone bias current (same as Lira; bench check with TRS and TRRS plugs).

## 6. Open items (bench)

- USB Full-Speed enumeration of the RP2040 behind the hub.
- Audio playback and microphone, both plug types.
- Pop on USB unplug (A14 above).
- VBIAS level / recording quality (A06).
- The RP2040 crystal start-up (the ABM8-272-T3 is the recommended one, so this should be safe).
