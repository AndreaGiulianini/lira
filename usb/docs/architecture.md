# Architecture

USB-only 40% + left-numpad keyboard with a 3.5 mm headset jack (headphones + microphone) and a
headphone amplifier. RP2040 MCU. Everything runs from the USB-C cable; there is no cell, no charger,
no Bluetooth and no antenna.

## Block diagram

```
                    +------------------- USB-C (HRO TYPE-C-31-M-12) -------------------+
                    |                                VBUS 5V                          |
                 USBLC6-2SC6 (D+/D-/VBUS ESD)                                       |
                    |                                                                |
                    +----- D+/D- ---------> +---------------+                        |
                    |                       |  CH334P hub   |-- DP3/DM3 --> RP2040   |
                    |                       |  (12 MHz xtal)|-- DP2/DM2 --+         |
                    |                       +---------------+             |         |
                    |                                                     v         |
                    |                              +------------------------------+ |
                    |                              |      CM108B  USB audio       | |
                    |                              |   (crystal-less, LQFP-48)    | |
                    |                              +--------------+---------------+ |
                    |                                             | LOL/LOR         |
                    |                              +--------------v---------------+ |
                    |                              |   TPA6132A2 headphone amp    | |
                    |                              |   (DirectPath, 0 dB / -6 dB) | |
                    |                              +--------------+---------------+ |
                    |                                             |                 |
                    |                                       3.5 mm headset jack      |
                    |                                                                |
                    +---> AP2112K-3.3 ---> 3V3 (RP2040, flash, crystal)              |
                    +---> VBUS ---> CM108B AVDD/DVDD + TPA6132A2 VDD                  |
                                                                       (always on)
   Matrix: 57 switches x 1N4148W -> 4 rows x 17 columns -> 21 RP2040 GPIOs
   Status LED (Caps Lock / BOOTSEL) on one GPIO. BOOTSEL + RUN buttons. SWD test pads.
```

## MCU: why RP2040

| | nRF52840 (Lira) | **RP2040 (this board)** |
|---|---|---|
| Radio | BLE 5 (unused here: no audio over BLE) | none — not needed |
| USB | Full Speed | **Full Speed** (matches HID + CM108B) |
| Price | ~$8–10 (E73 module) | **~$1** (bare QFN-56) |
| Flashing | SWD probe once, then UF2 | **UF2, drag-and-drop** (BOOTSEL) |
| Firmware | RMK (Rust) + Vial | **QMK + Vial** (RP2040 is supported) |
| Needs | 32.768 kHz xtal, battery, charger, LDO, antenna | 12 MHz xtal + QSPI flash + LDO |

The RP2040's Full-Speed USB is not a downgrade here: the keyboard is HID and the codec is a Full-Speed
device, so High Speed was never used by anything except the hub's own upstream link.

## Required RP2040 support circuit (follow the RP2040 hardware design guide, §"Minimal design")

- **12 MHz crystal** on XIN/XOUT: load caps `2 x (CL - Cstray)`, a 1 kΩ series resistor on XIN and a
  1 MΩ start-up resistor across the crystal (as in the guide).
- **QSPI flash** (W25Q128): the dedicated QSPI pins, 100 nF decoupling, a **10 kΩ pull-up on
  QSPI_SS** (this is what enters the USB bootloader at power-up).
- **VREG_IN = 3.3 V** with 1 µF; **VREG_VOUT = 1.1 V** with 1 µF feeding **DVDD**; ~100 nF on each
  IOVDD / USB_VDD / ADC_AVDD / DVDD pin (≈20 capacitors total).
- **BOOTSEL**: button from QSPI_SS to GND. **RUN**: button to GND (internal pull-up).
- **USB DP/DM**: ESD, no external series resistors (check the guide for the exact recommendation).
- **SWD** pads (SWCLK/SWDIO/GND) for recovery, as on Lira.

## Power tree

```
USB-C VBUS (5 V)
 ├─ USBLC6-2SC6 clamp
 ├─ AP2112K-3.3  -> 3V3 : RP2040 IOVDD/USB_VDD/ADC_AVDD, flash, crystal
 ├─ CH334P V5 (5 V) -> its internal 3.3 V LDO (VDD33)
 ├─ CM108B AVDD/DVDD (through ferrite beads)
 └─ TPA6132A2 VDD
```

With USB-only operation the **TPS22919 load switch and the audio gate firmware disappear**: the
codec and amplifier are simply on whenever the cable is plugged. That also removes the EN /
power-down-ordering concern (A14 on Lira).

## Pin map (RP2040)

| Function | GPIOs |
|---|---|
| Matrix rows | 4 (assigned by the layout, like Lira) |
| Matrix columns | 17 |
| Status LED | 1 |
| USB DP/DM | dedicated |
| QSPI | dedicated |
| Spare | ~9 GPIO for expansion / encoders / a second LED |

The exact row/column pads are chosen by the same "sort nets and pads by angle" step Lira uses, so the
fan-out does not cross itself.

## Target BOM (key parts; LCSC codes verified in stock)

| Part | LCSC | Note |
|---|---|---|
| RP2040 | C2040 | QFN-56, 0.4 mm |
| W25Q128JVSIQ | C97521 | QSPI flash, SOP-8 (W25Q64JVSSIQ C179171 if 8 MB is enough) |
| 12 MHz crystal | (verify) | 3225, CL 10–15 pF |
| AP2112K-3.3 | C51118 | reuse from Lira |
| USB-C HRO TYPE-C-31-M-12 | C165948 | reuse |
| USBLC6-2SC6 | C7519 | reuse |
| CH334P | C5373042 | reuse |
| CM108B | C371347 | reuse |
| TPA6132A2 | C69901 | reuse |
| PJ-320D-4A jack | C95562 | reuse |
| Kailh hot-swap sockets | C2803348 / substitute | reuse (see Lira's stock note) |
| 1N4148W | C81598 | reuse |

Dropped versus Lira: E73 module, TP4054/MCP73831 charger, AP2112K second rail, SI2301 + B5819W
power path, battery JST, power switch, 32.768 kHz crystal, TPS22919 load switch, USB hub? (no,
the hub stays for audio), antenna keep-out.
