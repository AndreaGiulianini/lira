#!/usr/bin/env python3
"""check_circuit.py - independent electrical rule check for the Lira netlists.

Usage:  python3 check_circuit.py netlist.json [another.json ...]
Exit status is 1 if any check FAILs (WARN and SKIP do not change the exit status).

Standard library only.  Every rule is derived from the component datasheets
(file names below refer to the datasheets/ folder of the review inputs) or from the
USB Type-C specification (CC pull-downs for a sink).  Parts are located by their
value / LCSC code / footprint / pin names, never by reference designator, so the
same checks run unchanged on the BlueMicro840 reference netlist.

Also covered: MCP73831 charger (C01-C06, replacing the TP4054 checks; the
TP4054 is still recognised for the VBAT role, D01 and P04), USB through a CH334P hub (M04, U02, U03,
H01-H03), CM108B USB codec (A01-A06), TPA6132A2 headphone amplifier (A11-A14), TPS22919 audio
load switch and its GPIO enable (S01-S03), PJ-320D-4A CTIA headset jack (J01).

Also covered: the wired variant (branch rp2040) replaces the E73 module with a bare Raspberry
Pi RP2040 (QFN-56, LCSC C2040) and its minimum circuit.  "The MCU" is now the E73 module or the RP2040 (found by
LCSC code / value / footprint + pin names): the GPIO, LED, matrix, encoder, USB-port, enable and floating-pin rules
(M10, M11, D01, K01-K03, U03, H03, A14, S02, L01, N01, R01) accept either; the E73-only rules (M01-M09, M12, B01)
SKIP without the module.  New RP2040 rules Q01-Q12 (pin table, ground / TESTEN, supply levels, decoupling, 1.1 V
core, 12 MHz crystal, W25Q128JV QSPI flash, BOOTSEL strap, RUN, SWD, USB pins, 3.3 V budget) cite the RP2040
datasheet, Hardware design with RP2040, the Pico datasheet, the W25Q128JV and ABM8-272-T3 datasheets.  P01 applies
the power-path rules only when there is a power path (VIN / battery); S02 and A14 judge an enable tied to VBUS.
With no module and no RP2040 the old behaviour is unchanged; the E73 netlist gives the same results as before.

Netlist format:
  {"parts": {REF: {"value", "footprint", "lcsc", "dnp", "note",
                   "pins": {PIN: {"name", "net"}}}},
   "nets": {NET: [[REF, PIN], ...]},
   "matrix": {...}, "gpio": {...}}          (matrix / gpio are optional)
A pin with "net": null is unconnected.

Result levels:
  PASS  requirement met
  FAIL  a datasheet requirement or a wiring rule is violated (exit status 1)
  WARN  a datasheet recommendation is not followed, or something that depends on
        layout / firmware / assembly and cannot be proven from the netlist
  SKIP  the check does not apply to this netlist (part not present)
"""

import json
import math
import re
import sys
from collections import defaultdict, deque

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

# ----------------------------------------------------------------------------
# Datasheet sources (file in datasheets/, PDF page, section)
# ----------------------------------------------------------------------------
SRC = {
    "VBUS_prot": "SMF5.0A_C2857263.pdf (unidirectional TVS, SOD-123FL: VRWM 5.0 V, VBR 6.4-7.0 V at 10 mA, IR <= 200 uA "
                 "at VRWM, VC 9.2 V at IPP 21.7 A 10/1000 us, 200 W); USB 2.0 7.2.4.1 (at most 10 uF on VBUS at attach); "
                 "USB Type-C 2.0 4.4 / Table 4-2 (vSafe5V 4.75-5.5 V); TPS22919_C2149796.pdf p.4 (VIN abs max 6 V); "
                 "AP2112.pdf p.3 (VIN abs max 6.5 V); RC snubber damping of an LC input (R. D. Middlebrook, 'Design "
                 "techniques for preventing input-filter oscillations', 1978: damping capacitor several times the one "
                 "damped, resistor near the characteristic impedance)",
    "VBUS_sense": "rp2040-datasheet.pdf 4.9 p.557-560 (ADC: GPIO26-29 = ADC0-3, input range 0-ADC_AVDD, 12 bit), "
                  "Table 625 p.616 (pad voltage <= IOVDD + 0.5 V abs max); USB Type-C 2.0 Table 4-2 (vSafe5V max 5.5 V)",
    "layout": "Hardware design with RP2040 2.1.2 p.7 (decoupling close to the power pins), 2.1.3 p.8 (1 uF close to "
              "VREG_IN and VREG_OUT), 2.3 p.9-10 (crystal: keep the tracks short), 2.4.1 p.11 (27 Ohm close to the "
              "RP2040); rp2040-datasheet.pdf 2.10.1 p.156 (the regulator's 1 uF close to its pins); "
              "CM108B_CM119B_DemoBoard_v133.pdf sheet 4 (0.1 uF at AVDD); ESD clamps between the connector and the "
              "circuit they protect (usblc6.pdf p.5-6)",
    "E73_pins": "E73-2G4M08S1C_C356849.pdf p.7 (ch.3 pin table, nRF52840 ball per pin)",
    "E73_limits": "E73-2G4M08S1C_C356849.pdf p.5 (2.1 abs max 0-5.5 V; 2.2 supply 1.7-5.5 V, "
                  ">=3.3 V for rated TX power, 3.3 V I/O level)",
    "E73_5V": "E73-2G4M08S1C_C356849.pdf p.9 (5.1: 5 V level signals need a 1k-5.1k series resistor, "
              "not recommended)",
    "PS_supply": "nrf52840_ps_a.pdf 5.3.1 p.61 (normal voltage mode = VDD shorted to VDDH), "
                 "5.3.8 p.80 (VDD 1.7-3.6 V), 9 p.612 Table 173 (VDD abs max 3.9 V)",
    "PS_dcdc": "nrf52840_ps_a.pdf 5.3.1.1 p.61-62 (LC filter needed only when a DC/DC regulator "
               "is enabled; Fig.13 normal voltage mode, LDO only), 7.3 p.583-590 (reference circuits)",
    "PS_usb": "nrf52840_ps_a.pdf 5.3.2 p.66 (5 V on VBUS for USB), 8 p.611 (VBUS 4.35-5.5 V), "
              "9 p.612 (VBUS abs max 5.8 V), 7.1 p.577 (AD2 VBUS, AD4 D-, AD6 D+), "
              "7.3 p.583 (series resistor on VBUS recommended for new designs)",
    "PS_swd": "nrf52840_ps_a.pdf 4.8.1 p.51 (SWDIO internal pull-up, SWDCLK internal pull-down), "
              "p.53 (Rpull 13 kOhm), 7.1 p.577 (AA24 SWDCLK, AC24 SWDIO)",
    "PS_reset": "nrf52840_ps_a.pdf 5.3.6.2 p.69 (pin reset), 7.1 p.577 (AC13 P0.18 configurable as "
                "nRESET), p.81 (tPINR vs capacitance on the reset pin); "
                "bluemicro_nrf52840_board.h (BUTTON_DFU = P0.18, BUTTON_PULL = PULLUP)",
    "PS_lfxo": "nrf52840_ps_a.pdf 5.4.2.4 p.86-87 (Fig.23: C1/C2 from XL1/XL2 to GND, equal values, "
               "CL per crystal datasheet), 5.4.4.3 p.97 (CL 12.5 pF, C0 <=2 pF, ESR <=100 kOhm, "
               "drive 0.5 uW, Cpin 4 pF); C32346.pdf p.1 (Epson FC-135 Q13FC13500004: CL 12.5 pF, "
               "ESR 70 kOhm max, C0 1 pF, drive level 0.5 uW max)",
    "PS_nfc": "nrf52840_ps_a.pdf 6.14.3 p.209 (NFC1/NFC2 shared with P0.09/P0.10, UICR NFCPINS "
              "selects GPIO use), 7.1 p.576 (L24 P0.09/NFC1, J24 P0.10/NFC2)",
    "PS_gpio": "nrf52840_ps_a.pdf 6.9.3.1 p.156 (IOH/IOL standard drive 1-4 mA, high drive 6-15 mA), "
               "9 p.612 (VI/O max VDD+0.3 V)",
    "PS_saadc": "nrf52840_ps_a.pdf 6.23 p.376 (inputs AIN0-AIN7), 6.23.1.1 p.377-378 Fig.147 (the SAADC connects a "
                "sample capacitor to the input for TACQ) and Table 95 (max source resistance per TACQ, 800 kOhm at 40 us, "
                "for a resistive source), 6.23.2 p.379 (gain 1/6 + 0.6 V reference = 3.6 V range, AIN <= VDD), "
                "6.23.10 p.397 (CSAMPLE 2.5 pF at maximum gain = the largest, RINPUT > 1 MOhm, tACQ table), p.398 "
                "(RLADDER 160 kOhm); Nordic DevZone blog 'Measuring Lithium battery voltage with nRF52' (O. Bauck, "
                "2016-05-23: reservoir Cext = Csample x 2^12 ~ 10 nF, R1 4M / R2 10M, TACQ 3 us, SAADC input seen "
                "as 1/(fsample Csample))",
    # TP4054 (BlueMicro840 reference only: still recognised as the charger for the VBAT role,
    # for D01's CHRG sink and for P04; its C01-C05 checks were replaced by the MCP73831 ones)
    "TP_limits": "C32574.pdf (TP4054) p.2 (abs max: VCC 10 V, BAT 7 V, CHRG 10 V, BAT pin 800 mA, "
                 "PROG pin 800 uA; BAT -> VCC reverse current blocked), p.3 (VCC 4.0-9.0 V, VFLOAT 4.2 V +-1 %)",
    "TP_chrg": "C32574.pdf (TP4054) p.6-7 (CHRG open drain: ~10 mA pull-down while charging, "
               "20 uA weak pull-down when done, Hi-Z in UVLO), p.11 (sinks up to 10 mA for a LED), "
               "p.3 (VOL 0.3 V typ, 0.5 V max at 5 mA)",
    # MCP73831T-2ACI/OT (LCSC C424093), MCP73831_C424093.pdf = Microchip DS20001984H (PDF page = printed page)
    "MCP_pins": "MCP73831_C424093.pdf p.1 (Package Types, SOT-23-5: 1 STAT, 2 VSS, 3 VBAT, 4 VDD, 5 PROG), "
                "p.11 Table 3-1 (pin functions), p.3 (abs max VDD 7.0 V, all other pins -0.3..VDD+0.3 V; "
                "VDD 3.75-6 V; VREG 4.168/4.20/4.232 V for MCP7383X-2), p.11 3.1 ([VREG+0.3 V] to 6 V "
                "recommended), p.26 (product ID: -2ACI = 4.20 V, option AC: IPREG 10 %, VPTH 66.5 %, ITERM 7.5 %, "
                "VRTH 96.5 %)",
    "MCP_vdd": "MCP73831_C424093.pdf p.11 3.1 (VDD: bypass to VSS with a minimum of 4.7 uF), p.18 6.1.1.2 "
               "(input overvoltage protection must be used with hot-pluggable sources, USB cables included: "
               "a transzorb from V+ to 0 V), p.17 Fig.6-1 (SMAJ5.0A); usblc6.pdf p.2 (VBUS-GND breakdown "
               ">= 6 V at 1 mA)",
    "MCP_prog": "MCP73831_C424093.pdf p.15 5.1.2 (IREG [mA] = 1000 V / RPROG [kOhm]), p.4 (RPROG charge "
                "range 2-67 kOhm, shutdown impedance 70-200 kOhm), p.3 (IREG 90-110 mA at 10k, 450-550 mA at 2k), "
                "p.13 4.3 / p.15 5.2.2 (PROG open = charger disabled), p.18 6.1.1.3 (P = (VDDMAX - VPTHMIN) * "
                "IREGMAX), p.5 (SOT-23-5 theta-JA 230 C/W), p.14 Fig.4-2 (thermal regulation); C221660.pdf p.1 "
                "(slide switch 0.3 A)",
    "MCP_stat": "MCP73831_C424093.pdf p.15 5.2.1 Table 5-1 (STAT: shutdown Hi-Z, no battery Hi-Z, "
                "preconditioning / fast charge / constant voltage L, charge complete H on the MCP73831), "
                "p.4 (STAT sink <= 25 mA, VOL 0.4 V typ / 1 V max at 4 mA; source <= 35 mA, VOH VDD-0.4 V typ / "
                "VDD-1 V min at 4 mA; Hi-Z leakage <= 1 uA), p.11 3.3 (LED or pull-up to a host MCU), "
                "p.13 Fig.4-1",
    "MCP_vbat": "MCP73831_C424093.pdf p.11 3.2 (VBAT: bypass to VSS with a minimum of 4.7 uF to ensure "
                "loop stability when the battery is disconnected), p.18 6.1.1.4 (stable with or without "
                "battery; 4.7 uF at the output usually sufficient up to 500 mA, any ESR)",
    "MCP_det": "MCP73831_C424093.pdf p.13 4.2 (battery detection: 6 uA typ sourced by VBAT; VBAT >= VREG + "
               "100 mV -> no battery; 'in order to correctly detect a battery insertion, the impedance seen by "
               "the VBAT pin before the battery is connected must be greater than 7 MOhm due to the minimum "
               "battery detection current of 0.6 uA'), p.4 (IBAT_DET 0.6 uA min / 6 uA typ; ZNO_BAT 7 MOhm min; "
               "charge-complete output current -5.5 uA typ), p.5 (tTERM 0.4-3.2 ms), p.15 Table 5-1 (no battery: "
               "STAT Hi-Z), p.26 (option AC: recharge at 96.5 % of VREG)",
    # WCH CH334P (LCSC C5373042), CH334_C5373042.pdf = CH334/CH335 datasheet V2.91 (Chinese)
    "CH_pins": "CH334_C5373042.pdf p.2 Fig.1-1 / CH334_C5373042-p2-pinout.png (CH334P QFN-16: 1 XO, 2 XI, "
               "3 DM4, 4 DP4, 5 DM3, 6 DP3, 7 DM2, 8 DP2, 9 DM1, 10 DP1, 11 DMU, 12 DPU, 13 RESET#/CDP, "
               "14 PGANG, 15 V5, 16 VDD33, 0 = exposed pad = GND), p.3 Table 1-1 (CH334P: no over-current / "
               "power-switch pins), p.4-5 Table 1-3 (pin functions)",
    "CH_power": "CH334_C5373042.pdf p.4 Table 1-3 (V5: 5 V or 3.3 V input, 1 uF or more; VDD33: LDO output "
                "and 3.3 V input, 0.1 uF + 10 uF or 1 uF; GND pad), p.19 4.1 (abs max V5 5.5 V, VDD33 4.0 V), "
                "p.19 4.2 (V5 4.5-5.0-5.25 V with the internal LDO, 3.15-3.5 V without; LDO external load "
                "<= 20 mA), p.26 6.1 (bus-powered application: V5 from the upstream VBUS, C1 1 uF, "
                "C2 0.1 uF + C8 10 uF on VDD33), p.28 6.4 (embedded hub: V5 = VDD33 = on-board 3.3 V suggested)",
    "CH_xtal": "CH334_C5373042.pdf p.1 (crystal oscillator with built-in capacitors), p.4 Table 1-3 (XI/XO: "
               "12 MHz crystal, 24 MHz only on the CH334X), p.26 6.1 (XI and XO have ~16 pF built in: no "
               "external load capacitors), p.27 6.2 (crystal-free option only on parts ordered with it: "
               "XO open and XI to GND)",
    "CH_cfg": "CH334_C5373042.pdf p.4 Table 1-3 (RESET#/CDP: internal pull-up, active low, leave fully "
              "floating when no reset is needed), p.10-11 3.2 (internal power-on reset; ~25 kOhm pull-up; "
              "Table 3-2: low = reset, driven high at power-up = CDP on and low-power sleep off, open = default), "
              "p.5 (PGANG: internal pull-up configuration input during reset, status output afterwards; pull-"
              "down only through a resistor)",
    "CH_usb": "CH334_C5373042.pdf p.1 (USB 2.0 hub: upstream HS/FS with a built-in 1.5 kOhm pull-up, "
              "downstream ports with built-in host pull-downs), p.4 Table 1-3 (DPU/DMU upstream D+/D-, DPn/DMn "
              "downstream port n), p.19 4.1 (USB pins -0.4..VDD33+0.4 V), p.29 6.5 (ESD protection advised on "
              "every USB signal); nrf52840_ps_a.pdf 7.3 p.585 Fig.210 (D+/D- wired straight to the USB "
              "connector, no series parts); CM108B_appnotes_v1.50.pdf p.9 3.5 (series resistors for PHY "
              "impedance matching, 39 Ohm in the figure) and C-Media demo board v1.33 sheet 4 (R4/R66 22 Ohm, "
              "C1/C2 100 pF)",
    # C-Media CM108B (LCSC C371347): CM108B_datasheet_v1.41.pdf (= CM108B_C371347.pdf), application notes v1.50,
    # demo board CM108B/CM119B v1.33 sheet 4 (reference/CM108B_CM119B_demoboard_v133_sheet4.png + .txt)
    "CM_pins": "CM108B_datasheet_v1.41.pdf p.6 4.1-4.2 (LQFP-48 pin assignment), p.7-8 4.3 (pin descriptions)",
    "CM_power": "CM108B_datasheet_v1.41.pdf p.4 (DVdd = AVdd = 5 V), p.7 (29/34 AVDD 5 V, 35 DVDD 5 V, "
                "8 DREG18 1.8 V / 9 DREG33 3.3 V (40 mA) / 37 AREG36 3.6 V regulator outputs, 14/36 DVSS, "
                "24/33 AVSS), p.20 8.1-8.2 (supplies 4.5-5.0-5.5 V, abs max 6 V; 37.25 mA; 0-70 C); "
                "CM108B_appnotes_v1.50.pdf p.8 3.4 (1 uF on DREG18, 0.1 uF on DREG33), p.25 (AVDD36: 10 uF to "
                "AGND); demo board v1.33 sheet 4 (L2/L3 beads USB5V -> DVDD/AVDD, DVDD 4.7 uF + 0.1 uF, AVDD "
                "0.1 uF, AVDD36 10 uF, C23/C24 10 nF DVDD -> REGV/DVDD18 'close to IC')",
    "CM_ref": "CM108B_datasheet_v1.41.pdf p.7-8 (26 VREF: decoupling capacitor for the bandgap, 1.75 V; "
              "31 LOBS: 1.75 V DC line-out bias; 25 VBIAS: microphone bias 3 V, 'small driving capability'), "
              "p.20 (analog pins -0.3..3.96 V); demo board v1.33 sheet 4 (VREF C14 10 uF, LOBS C10 10 uF, "
              "cap-less option L10/R18 not fitted); CM108B_appnotes_v1.50.pdf p.7 3.2 (cap-less = LOBS as "
              "the headphone return)",
    "CM_cfg": "CM108B_datasheet_v1.41.pdf p.7-8 (MODE PD: L = headset = playback + recording, H = speaker = "
              "playback only; PWRSEL PU; MSEL PU; ADSEL PD: L = internal ADC; TEST PD: L = normal operation; "
              "'H: push up to 3.3V' i.e. to REGV/DREG33; MUTER/MUTEP/VOLUP/VOLDN PU), p.15 7.2 (mode table), "
              "p.12 (headset configuration: bus powered, 100 mA)",
    "CM_usb": "CM108B_datasheet_v1.41.pdf p.8 (41 USBDP, 42 USBDM), p.20 (analog pins -0.3..3.96 V); "
              "CM108B_appnotes_v1.50.pdf p.9 3.5 (R1/R2 series resistors for PHY impedance matching; no "
              "pull-up on USBDP, it is inside the PHY), p.23 5.3; demo board v1.33 sheet 4 (R4/R66 22 Ohm "
              "in USBDP/USBDM)",
    "CM_audio": "CM108B_datasheet_v1.41.pdf p.7 (25 VBIAS 3 V 'small driving capability', 27 MICIN 10 kOhm "
                "input, 30 LOL / 32 LOR line out, 31 LOBS 1.75 V DC), p.21 (DAC output 0.94 Vrms into 10 kOhm), "
                "p.20 (analog pins -0.3..3.96 V); CM108B_appnotes_v1.50.pdf p.23 5.4 (R + C in series in the "
                "MIC path); demo board v1.33 sheet 4 (VBIAS - R13 2k2 - C15 4.7 uF - R14 8k2 - MIC; MIC - "
                "R10 0 R - C12 1 uF - MICIN; C16 100 pF on MIC; LOL/LOR via C9/C8 100 uF)",
    # TI TPA6132A2RTER (LCSC C69901), TPA6132A2_C69901.pdf = SLOS597B
    "TPA_pins": "TPA6132A2_C69901.pdf p.3 (RTE pinout and pin functions: 1 INL-, 2 INL+, 3 INR+, 4 INR-, "
                "5 OUTR, 6 G0, 7 G1, 8 HPVSS, 9 CPN, 10 PGND, 11 CPP, 12 HPVDD, 13 EN, 14 VDD, 15 SGND, "
                "16 OUTL; thermal pad to ground or floating), p.18 10.1 (pad: same ground as PGND or floating, "
                "never VDD), p.18 10.3 (SGND must go to the headphone ground pin, within +-0.3 V), p.4 "
                "(VDD 2.3-5.5 V, abs max 6 V)",
    "TPA_cp": "TPA6132A2_C69901.pdf p.3 (HPVSS: 1 uF to GND; 1 uF between CPP and CPN; HPVDD: 2.2 uF, do not "
              "connect to VDD), p.4 (HPVDD abs max 1.9 V, never an external supply), p.15 8.2.1.2.2 (HPVSS "
              "cap >= flying cap, 1-2.2 uF typical, >= 0.47 uF), p.17 9 / 9.1 (2.2 uF X5R at VDD within "
              "5 mm; HPVDD only to a 2.2 uF capacitor; boxed warning: HPVDD to VDD can damage the device)",
    "TPA_in": "TPA6132A2_C69901.pdf p.1 + p.3 (single-ended inputs: INL+ and INR+ to ground, signal into "
              "INL-/INR-), p.16 Fig.27 (1 uF in series with each single-ended input), p.15 8.2.1.2.1 (input "
              "capacitors block the DC of the source; fc = 1 / (2 pi RIN CIN)), p.5 (RIN 26.4 / 19.8 / 16.5 / "
              "13.2 kOhm at -6 / 0 / 3 / 6 dB), p.4 (input voltage 0..HPVDD+0.3 V), p.12 7.3.2",
    "TPA_ctl": "TPA6132A2_C69901.pdf p.4 (EN/G0/G1: VIH >= 1.3 V, VIL <= 0.6 V, abs max -0.3..VDD+0.3 V), "
               "p.5 (EN/G0/G1 input current <= 1 uA; gain -0.5/-1.0/-1.41/-2.0 V/V), p.13 7.4.1 (G0/G1 <= "
               "0.5 V or >= 1.3 V: -6 / 0 / 3 / 6 dB), p.12 7.3.2 (activate after the audio sources have "
               "settled, deactivate before the sources; tON 5 ms); C8598.pdf (B5819W) p.1; nrf52840_ps_a.pdf p.156 "
               "(IOL >= 1 mA standard / >= 6 mA high drive at 0.4 V); CM108B_datasheet_v1.41.pdf p.20 (37.25 mA); "
               "TPS22919_C2149796.pdf p.5 (tON, tOFF, RPD,QOD), p.13 8.3.3",
    # TI TPS22919DCKR (LCSC C2149796), TPS22919_C2149796.pdf = SLVSEN5B
    "TPS_pins": "TPS22919_C2149796.pdf p.3 (DCK SC-70-6: 1 IN, 2 GND, 3 ON 'do not leave floating', 4 NC "
                "'leave floating', 5 QOD, 6 VOUT), p.4 (abs max VIN/VOUT/VON/VQOD 6 V; VIN 1.6-5.5 V; IMAX "
                "1.5 A), p.5 (RON 89 mOhm at 5 V; tON 1.95 ms and 3.2 mV/us at 5 V), p.17 10 (CIN 1 uF usually "
                "sufficient)",
    "TPS_on": "TPS22919_C2149796.pdf p.3 (ON: active high, do not leave floating), p.4 (ON VIH >= 1 V, "
              "VIL <= 0.35 V, abs max 6 V), p.5 (ON leakage <= 100 nA; smart pull-down 530 kOhm while ON <= "
              "VIL), p.13 8.3.1 (the smart pull-down exists only once VIN is applied); nrf52840_ps_a.pdf 6.9.3.1 "
              "p.156 (GPIO drive) and 9 p.612 (VI/O max VDD + 0.3 V); reference/bluemicro_nrf52840_board.h "
              "(pins the bootloader drives)",
    "TPS_qod": "TPS22919_C2149796.pdf p.3 (QOD: resistor to VOUT, tied to VOUT, or floating = no discharge), "
               "p.13-14 8.3.3 + Table 2 (ON low: VOUT to GND through RPD,QOD (24 Ohm) + RQOD; tFALL = 2.2 * "
               "(RDIS || RL) * CL), p.5 (RPD,QOD 24 Ohm), p.6 (tFALL 0.4 ms with 10 uF)",
    # Hroparts PJ-320D-4A (LCSC C95562): drawing only
    "JACK": "PJ-320D-4A_C95562.pdf p.1 / PJ-320D-4A_C95562-p1.png (PJ-320D-A schematic: pin 1 = the long "
            "contact reaching the jack opening = sleeve; pins 4 / 3 / 2 = contacts at 3.20 / 6.20 / 10.20 mm "
            "from the front face = ring 2 / ring 1 / tip; pad 1 at 11.30 mm on the other side; 0.5 A 30 V); "
            "KiCad footprint Jack_3.5mm_KoreanHropartsElec_PJ-320D-4A_Horizontal: pads R2 / R1 / T / S sit "
            "on the drawing's pads 4 / 3 / 2 / 1; CTIA headset plug (tip L, ring 1 R, ring 2 GND, sleeve MIC) "
            "- convention, not in the datasheet set; TPA6132A2_C69901.pdf p.3 / p.18 10.3",
    "AP_pins": "C51118.pdf (AP2112) p.2 (SOT25 pins: 1 VIN, 2 GND, 3 EN, 4 NC, 5 VOUT; typical "
               "application CIN = COUT = 1 uF), p.1 (stable with 1.0 uF ceramic)",
    "AP_limits": "C51118.pdf (AP2112) p.3 (abs max VCC 6.5 V, recommended VIN 2.5-6.0 V), "
                 "p.8 (AP2112-3.3: VOUT 3.3 V +-1.5 %, dropout 250 mV typ at 600 mA, "
                 "VEN high >= 1.5 V, low <= 0.4 V, EN pull-down 3 MOhm)",
    "SI_pins": "C10487.pdf (Si2301CDS) p.1 (SOT-23: 1 G, 2 S, 3 D; VDS -20 V, VGS +-8 V), "
               "p.2 (VGS(th) -0.4..-1 V, body diode VSD -0.8 V), p.7 (AN807: pin 1 gate, "
               "pin 2 source, pin 3 drain)",
    "B58_pins": "C8598.pdf (B5819W) p.1 (marking bar = cathode; IO 1 A, VRRM 40 V, VF 0.6 V at 1 A)",
    "USBC": "C165948.pdf (HRO TYPE-C-31-M-12) p.1 pin table (A1/B1/A12/B12 GND, A4/A9/B4/B9 VBUS, "
            "A5 CC1, B5 CC2, A6/B6 DP, A7/B7 DN, A8/B8 SBU; 5 A / 20 V rating); "
            "USB Type-C specification (sink: Rd = 5.1 kOhm +-10 % on each CC) - not in the datasheet set",
    "USBLC6": "usblc6.pdf p.1 Fig.1 (SOT23-6L: 1 I/O1, 2 GND, 3 I/O2, 4 I/O2, 5 VBUS, 6 I/O1), "
              "p.2 (VBR VBUS-GND 6 V min, leakage 150 nA at 5.25 V), p.5-6 (place next to the "
              "connector, short tracks), p.9 Fig.18 (100 nF on VBUS)",
    "LED_red": "C2286.pdf (KT-0603R) p.3 (IF max 25 mA, VF 1.8-2.4 V at 20 mA, VR 5 V), "
               "p.4 (VF bins 1.9-2.0 V)",
    "LED_white": "C2290.pdf (KT-0603W) p.3 (IF max 30 mA, VF 2.6-3.1 V at 5 mA)",
    "D4148": "C81598.pdf (1N4148W) p.1 (PINNING: 1 cathode, 2 anode; VR 75 V, IF(AV) 150 mA, "
             "VF <= 0.715 V at 1 mA)",
    "TACT": "C318884.pdf (TS-1187A) p.1 (circuit diagram: A-B and C-D joined internally, contact "
            "between the two pairs; 50 mA 12 VDC)",
    "SLIDE": "C221660.pdf (C&K JS series) p.1 (contact rating 6 VDC at 0.3 A), p.4 (JS102011SAQN "
             "SPDT circuit diagram: C = common = centre terminal 2)",
    "JST": "C295747.pdf (JST PH) p.1 (2 A rating; 'Circuit No.1' marking on the SM4 footprint)",
    "EC11": "C470754.pdf (Alps EC11) p.1 (rating 10 mA 5 V DC; A/B two-phase output), "
            "p.3 (terminals A C B, C common; separate push-switch terminals)",
    "HOTSWAP": "C2803348.pdf (Kailh hotswap socket; replaced by C41430893, HanElectricity CPG151101S11-16, same drawing): two terminals, no polarity",
    # Raspberry Pi RP2040 (LCSC C2040) and its minimum circuit.  The three Raspberry Pi documents print
    # their own page numbers, one less than the PDF page: p. below = printed page.  rp2040-datasheet.pdf = RP2040
    # Datasheet build 2025-02-20 (3184e62); hardware-design-with-rp2040.pdf = build 2026-08-20; pico-datasheet.pdf =
    # build 2026-07-03.  W25Q128JV.pdf = Winbond rev F 2018-03-27 (printed page = PDF page - 1).
    "RP_pins": "rp2040-datasheet.pdf 1.4.2 Table 1 p.11-12 (pin functions; GND 'single external ground connection' "
               "= the central pad; TESTEN 'Factory test mode pin. Tie to GND'), 5.5.2 Tables 614-621 p.612-614 (QFN-56 "
               "numbers 1-56, 57 = GND pad; QSPI_SS = QSPI_CSn, SWDIO = 'SWD'; reset state: pull-down on GPIO, TESTEN, "
               "QSPI_SCLK; pull-up on QSPI_CSn, SWCLK, SWDIO, RUN), 5.1 p.607 (ePad smaller than usual), 5.1.2 "
               "Fig.167 p.608 (recommended footprint: 3.20 mm ePad)",
    "RP_power": "rp2040-datasheet.pdf 2.9 p.150-152 (single 3.3 V supply, Fig.16: IOVDD, USB_VDD, ADC_AVDD and "
                "VREG_VIN on one 3.3 V rail; 'USB_VDD should not be left unconnected'; ADC compromised below 2.97 V), "
                "5.6 Table 634 p.622 (IOVDD / VREG_VIN / ADC_AVDD 1.62-3.63 V, USB_VDD 3.135-3.63 V, DVDD 1.05-1.16 V), "
                "5.5.3.1 Table 622 p.614 (IOVDD abs max 3.63 V); C51118.pdf (AP2112) p.8 (3.3 V +-1.5 %)",
    "RP_decoup": "rp2040-datasheet.pdf 2.9.1-2.9.5 p.151-152 (100 nF close to each IOVDD pin, each DVDD pin, USB_VDD "
                 "and ADC_AVDD; 1 uF close to VREG_VIN), 2.10.1 p.156 ('the regulator must have 1 uF capacitors "
                 "placed close to its input (VREG_VIN) and output (VREG_VOUT) pins'); hardware-design-with-rp2040.pdf "
                 "2.1.2 p.7-8 (100 nF per power pin; pins 48 and 49 share one on the minimal design), 2.1.3 p.8 (1 uF at "
                 "VREG_VIN and VREG_VOUT; small ceramic chip capacitors meet the ESR limits)",
    "RP_vreg": "rp2040-datasheet.pdf 2.9.2 p.151 (VREG_VOUT to DVDD is made off-chip), 2.9.7.1-2.9.7.2 p.152-153 "
               "(single 3.3 V supply; with an external core supply VREG_VOUT stays unconnected, VREG_VIN still powered), "
               "1.4.2 p.12 / 2.10 p.155 (1.1 V at power-on, 100 mA max), 5.6 Table 634 p.622 (DVDD 1.05-1.16 V)",
    "RP_xosc": "rp2040-datasheet.pdf 1.4.2 p.11 (the USB bootloader needs a 12 MHz crystal or clock), 2.16.1 p.216-217 "
               "(1-15 MHz crystals; ABM8-272-T3 recommended, Table 257; crystal and damping resistor tuned for 3.3 V; "
               "other crystals must be tested over temperature), 2.15 p.181 (margin for up to 1000 ppm XOSC error); "
               "hardware-design-with-rp2040.pdf 2.3 p.9-10 (C2 = C3 = "
               "15 pF: 7.5 pF in series + 3 pF parasitic = 10.5 pF for CL 10 pF; ESR <= 50 Ohm and the 1 kOhm series "
               "resistor R5 on XOUT keep the crystal from being over-driven at 3.3 V), 2.3.1 Table 1 p.10; "
               "ABM8-272-T3.pdf (Abracon drawing 456603 rev B, 2024-09-16) page 2 of 9 (12.000 MHz fundamental, +-30 "
               "ppm, +-30 ppm, ESR 50 Ohm max, C0 3 pF max, CL 10 pF, drive 10 uW typ / 200 uW max), page 4 of 9 (pads "
               "1 and 3 crystal, 2 and 4 GND); pico-datasheet.pdf Appendix B Fig.19 p.25 (R14 1K, C16/C17 15p, R15 "
               "not fitted)",
    "RP_flash": "W25Q128JV.pdf 3.1 / 3.3 p.5 (SOIC-8 208-mil: 1 /CS, 2 DO(IO1), 3 /WP(IO2), 4 GND, 5 DI(IO0), 6 CLK, "
                "7 /HOLD(IO3), 8 VCC), 9.1 p.60 (VCC abs max 4.6 V), 9.2 p.60 (VCC 3.0-3.6 V for 133 MHz, 2.7-3.0 V up "
                "to 104 MHz), 9.4 p.62 (ICC <= 25 mA; VIL <= 0.3 VCC, VIH >= 0.7 VCC); rp2040-datasheet.pdf 5.5.2 "
                "Table 616 p.613 (QSPI pins 51-56); hardware-design-with-rp2040.pdf 2.2 p.9 (W25Q128JVS, 16 MB = the "
                "largest the RP2040 supports; QSPI pins wired directly, short), Fig.11 p.13 (SD0 -> DI_IO0, SD1 -> "
                "DO_IO1, SD2 -> /WP_IO2, SD3 -> /HOLD_IO3, C5 100 nF at VCC), 2.6 p.13-14 (03h, 02h, 05h, 06h, 20h)",
    "RP_boot": "rp2040-datasheet.pdf 2.8.1 p.129-130 ('Check if SPI CS pin is tied low (bootrom button), and skip flash "
               "boot if so'; no valid image after 0.5 s -> USB boot), Table 616 p.613 (QSPI_CSn pull-up), 5.5.3.4 "
               "Table 625 p.615-616 (VIL <= 0.8 V at IOVDD 3.3 V; VOH >= 2.62 V at the selected drive current; RPU "
               "50-80 kOhm), Table 614 p.612 (default drive 4 mA); hardware-design-with-rp2040.pdf 2.2 p.9 (R2 10k "
               "pull-up: the flash's /CS must be at its VCC at power-up, DNF on the minimal design; R1 1k to the "
               "USB_BOOT jumper 'allows the QSPI_SS pin to safely over-drive the applied pull-down'); W25Q128JV.pdf "
               "4.1 p.9, 6.5 p.12 (/CS must track VCC at power-up and power-down; a pull-up can be used); "
               "pico-datasheet.pdf Fig.19 p.25 (BOOTSEL: SW1 - R11 1K - QSPI_SS, R4 pull-up not fitted)",
    "RP_run": "rp2040-datasheet.pdf 1.4.2 p.11 (RUN: reset when low; 'if no external reset is required, this pin can "
              "be tied directly to IOVDD'), 2.7 p.128 (RUN low holds the chip in reset), Table 619 p.613 (RUN Digital "
              "In (FT), pull-up); pico-datasheet.pdf 2.1 p.8 (RUN internal pull-up ~50 kOhm; short low to reset)",
    "RP_swd": "rp2040-datasheet.pdf 1.4.2 p.11 (SWCLK / SWDIO: debug access, can download code), Table 618 p.613 "
              "(SWCLK 24, SWDIO 'SWD' 25, both pull-up), 2.8.1 p.130 (code is normally loaded over USB by the boot "
              "ROM); pico-datasheet.pdf 4.8 p.23 (internal pull-ups on SWDIO and SWCLK, nominally 60 kOhm)",
    "RP_usb": "rp2040-datasheet.pdf 1.4.2 p.11 ('A 27 Ohm series termination resistor is required on each pin, but bus "
              "pull-ups and pull-downs are provided internally'), Tables 614 / 620 p.612 / p.614 (USB_DP 47, USB_DM 46, "
              "power domain USB_VDD), Table 626 p.616-617 (USB IO levels), 4.1.2.10 p.394 (VBUS detect / enable / "
              "overcurrent GPIOs optional: 'VBUS detect can be forced in USB_PWR'); hardware-design-with-rp2040.pdf 2.4.1 p.11 "
              "(27 Ohm placed close to the chip; 90 Ohm differential over ground); pico-datasheet.pdf 4.7 p.23, "
              "Fig.19 p.25 (R12/R13 27R)",
    "RP_io": "rp2040-datasheet.pdf 5.5.2.1 Table 614 p.612 (GPIO0-25 Digital IO (FT), GPIO26-29 Digital IO / Analogue, "
             "not FT; drive 2/4/8/12 mA, default 4 mA), 5.5.3.1 Table 622 p.614 (VPIN abs max IOVDD + 0.5 V), 5.5.3.4 "
             "Table 625 p.615-616 (VIH max IOVDD + 0.3 V; VOH >= 2.62 V at the selected drive current, 3.3 V; RPU / "
             "RPD 50-80 kOhm; IIOVDD_MAX = IIOVSS_MAX = 50 mA for all GPIO and QSPI pins together), 5.5.3.5 p.617",
    "RP_budget": "rp2040-datasheet.pdf 2.10 p.155 (core regulator up to 100 mA), Table 625 p.616 (IIOVDD_MAX 50 mA), "
                 "5.7.2 Table 637 p.623 (USB_VDD <= 2.0 mA max, BOOTSEL with USB activity); W25Q128JV.pdf 9.4 p.62 (ICC "
                 "<= 25 mA program / erase); AP2112 datasheet Diodes DS39724 rev 2-2 (June 2017) p.3 (SOT25 theta-JA "
                 "184 C/W, VIN 2.5-6.0 V, TJ <= +150 C, TA -40..+85 C), p.8 (AP2112-3.3: IOUT(MAX) >= 600 mA, dropout "
                 "250 mV typ / 400 mV max at 600 mA)",
    # the sound-card enables tied to VBUS on the wired board (S02, A14), TI documents as above
    "TPS_on_rail": "TPS22919_C2149796.pdf p.3 (ON: active high, 'do not leave floating'), p.4 (VIN 1.6-5.5 V; ON VIH "
                   "1-5.5 V, VIL <= 0.35 V; abs max VON 6 V), p.5 (tON 1.95 ms, 3.2 mV/us at 5 V), p.12-14 8.1 / 8.3 / "
                   "8.4 Table 2 (no reverse-current blocking specified; QOD acts only with ON low), p.13 8.3.1 (smart "
                   "pull-down only until ON is driven high)",
    "TPA_ctl_rail": "TPA6132A2_C69901.pdf p.12 7.3.2 ('activate the TPA6132A2 after all audio sources have been "
                    "activated and their output voltages have settled. On power-down, deactivate the TPA6132A2 before "
                    "deactivating the audio input source'; EN <= 0.6 V off, >= 1.3 V on), p.4 (EN abs max VDD + 0.3 V; "
                    "VDD 2.3-5.5 V; no undervoltage lockout listed), p.5 (EN input current <= 1 uA); "
                    "CM108B_datasheet_v1.41.pdf p.20 (supply 4.5 V minimum, 37.25 mA); TPS22919_C2149796.pdf p.5 "
                    "(tON); C8598.pdf (B5819W) p.1 (VF 0.6 V at 1 A only); rp2040-datasheet.pdf 4.1.2.8.4 p.391 "
                    "(without VBUS detection a disconnect looks like a suspend)",
    "BOOT": "reference/bluemicro_nrf52840_board.h (LED_PRIMARY_PIN P1.04, LED_SECONDARY_PIN P1.10, "
            "LED_STATE_ON 1, BUTTON_DFU P0.18 = RESET, BUTTON_DFU_OTA P1.01 not on the module)",
    "NETLIST": "netlist structure (no datasheet needed)",
}

# ----------------------------------------------------------------------------
# E73-2G4M08S1C pin table (E73 datasheet p.7).  pin -> (function, nRF52840 aQFN73 ball)
# The ball names were cross-checked with nrf52840_ps_a.pdf 7.1 p.575-578.
# ----------------------------------------------------------------------------
E73_PINS = {
    1: ("P1.11", "B19"), 2: ("P1.10", "A20"), 3: ("P0.03/AIN1", "B13"), 4: ("P0.28/AIN4", "B11"),
    5: ("GND", "-"), 6: ("P1.13", "A16"), 7: ("P0.02/AIN0", "A12"), 8: ("P0.29/AIN5", "A10"),
    9: ("P0.31/AIN7", "A8"), 10: ("P0.30/AIN6", "B9"), 11: ("P0.00/XL1", "D2"), 12: ("P0.26", "G1"),
    13: ("P0.01/XL2", "F2"), 14: ("P0.06", "L1"), 15: ("P0.05/AIN3", "K2"), 16: ("P0.08", "N1"),
    17: ("P1.09", "R1"), 18: ("P0.04/AIN2", "J1"), 19: ("VDD", "-"), 20: ("P0.12", "U1"),
    21: ("GND", "-"), 22: ("P0.07", "M2"), 23: ("VDDH", "-"), 24: ("GND", "-"), 25: ("DCCH", "AB2"),
    26: ("P0.18/RESET", "AC13"), 27: ("VBUS", "AD2"), 28: ("P0.15", "AD10"), 29: ("D-", "AD4"),
    30: ("P0.17", "AD12"), 31: ("D+", "AD6"), 32: ("P0.20", "AD16"), 33: ("P0.13", "AD8"),
    34: ("P0.22", "AD18"), 35: ("P0.24", "AD20"), 36: ("P1.00", "AD22"), 37: ("SWDIO", "AC24"),
    38: ("P1.02", "-"), 39: ("SWDCLK", "AA24"), 40: ("P1.04", "U24"), 41: ("P0.09/NFC1", "L24"),
    42: ("P1.06", "R24"), 43: ("P0.10/NFC2", "J24"),
}
E73_GND = (5, 21, 24)
E73_VDD, E73_VDDH, E73_DCCH, E73_RESET, E73_VBUS = 19, 23, 25, 26, 27
E73_DN, E73_DP, E73_SWDIO, E73_SWDCLK = 29, 31, 37, 39
E73_XL1, E73_XL2, E73_NFC1, E73_NFC2 = 11, 13, 41, 43
E73_FIXED = set(E73_GND) | {E73_VDD, E73_VDDH, E73_DCCH, E73_VBUS, E73_DN, E73_DP, E73_SWDIO, E73_SWDCLK}
# Every pin that can be a GPIO (XL1/XL2, NFC and RESET included: they are P0.xx pins too)
E73_GPIO = {p for p in E73_PINS if p not in E73_FIXED}
E73_AIN = {p for p, (n, _) in E73_PINS.items() if "/AIN" in n}
E73_P1_04, E73_P1_10 = 40, 2  # bootloader LED pins


def e73_pin_by_name(name):
    """'P0_05' / 'P0.05' / 'P1.04' -> module pin number, or None."""
    n = name.strip().upper().replace("_", ".")
    for pin, (fn, _) in E73_PINS.items():
        if fn.split("/")[0].upper() == n:
            return pin
    return None


# ----------------------------------------------------------------------------
# Raspberry Pi RP2040 QFN-56 (rp2040-datasheet.pdf 5.5.2 Tables 615-621 p.612-614; pad 57 = the GND ePad)
# ----------------------------------------------------------------------------
RP_PINS = {
    1: "IOVDD", 2: "GPIO0", 3: "GPIO1", 4: "GPIO2", 5: "GPIO3", 6: "GPIO4", 7: "GPIO5", 8: "GPIO6", 9: "GPIO7",
    10: "IOVDD", 11: "GPIO8", 12: "GPIO9", 13: "GPIO10", 14: "GPIO11", 15: "GPIO12", 16: "GPIO13", 17: "GPIO14",
    18: "GPIO15", 19: "TESTEN", 20: "XIN", 21: "XOUT", 22: "IOVDD", 23: "DVDD", 24: "SWCLK", 25: "SWDIO", 26: "RUN",
    27: "GPIO16", 28: "GPIO17", 29: "GPIO18", 30: "GPIO19", 31: "GPIO20", 32: "GPIO21", 33: "IOVDD", 34: "GPIO22",
    35: "GPIO23", 36: "GPIO24", 37: "GPIO25", 38: "GPIO26/ADC0", 39: "GPIO27/ADC1", 40: "GPIO28/ADC2",
    41: "GPIO29/ADC3", 42: "IOVDD", 43: "ADC_AVDD", 44: "VREG_VIN", 45: "VREG_VOUT", 46: "USB_DM", 47: "USB_DP",
    48: "USB_VDD", 49: "IOVDD", 50: "DVDD", 51: "QSPI_SD3", 52: "QSPI_SCLK", 53: "QSPI_SD0", 54: "QSPI_SD2",
    55: "QSPI_SD1", 56: "QSPI_SS", 57: "GND",
}
# names other documents / symbols use for the same pin (datasheet Table 616: QSPI_CSn; Table 618: 'SWD'; the
# design guide's schematic: VREG_IN, QSPI_~{SS}; KiCad: GPIO26_ADC0)
RP_ALIASES = {"QSPI_SS": ("QSPI_CSN", "QSPI_SSN", "QSPI_~{SS}", "QSPI_CS"), "SWDIO": ("SWD",),
              "VREG_VIN": ("VREG_IN",), "VREG_VOUT": ("VREG_OUT",), "GND": ("EP", "PAD", "VSS", "EPAD")}
RP_IOVDD = (1, 10, 22, 33, 42, 49)
RP_DVDD = (23, 50)
RP_ADC_AVDD, RP_VREG_VIN, RP_VREG_VOUT, RP_USB_VDD = 43, 44, 45, 48
RP_GND, RP_TESTEN, RP_XIN, RP_XOUT, RP_SWCLK, RP_SWDIO, RP_RUN = 57, 19, 20, 21, 24, 25, 26
RP_USB_DM, RP_USB_DP = 46, 47
RP_QSPI = {"QSPI_SS": 56, "QSPI_SCLK": 52, "QSPI_SD0": 53, "QSPI_SD1": 55, "QSPI_SD2": 54, "QSPI_SD3": 51}
RP_GPIO = {p for p, n in RP_PINS.items() if n.startswith("GPIO")}       # user bank GPIO0-29
RP_ADC = {p for p, n in RP_PINS.items() if "/ADC" in n}                 # GPIO26-29: not fault tolerant (Table 614)
RP_SUPPLY_PINS = set(RP_IOVDD) | set(RP_DVDD) | {RP_ADC_AVDD, RP_VREG_VIN, RP_VREG_VOUT, RP_USB_VDD, RP_GND}
# Table 634 p.622: supply ranges (V); ADC performance compromised below 2.97 V (note c, 2.9.5)
RP_RANGE = {"IOVDD": (1.62, 3.63), "VREG_VIN": (1.62, 3.63), "USB_VDD": (3.135, 3.63), "ADC_AVDD": (1.62, 3.63),
            "DVDD": (1.05, 1.16)}
RP_ADC_GOOD = 2.97
RP_VREG_IMAX = 0.100          # 2.10 p.155
RP_IIOVDD_MAX = 0.050         # Table 625: all GPIO + QSPI sourced current
RP_USB_VDD_MAX = 0.0020       # Table 637: BOOTSEL with USB activity, maximum average
RP_RPU = (50e3, 80e3)         # Table 625 pull-up / pull-down range
RP_VIL, RP_VIH = 0.8, 2.0     # Table 625 at IOVDD = 3.3 V
RP_VOH_MIN, RP_DRIVE_DEFAULT = 2.62, 4e-3   # Table 625 (at the selected drive current), Table 614 (default 4 mA)
RP_STRAY = 3e-12              # design guide 2.3 p.9: PCB + XIN/XOUT parasitic capacitance assumed
# Abracon ABM8-272-T3 (LCSC C20625731): ABM8-272-T3.pdf page 2 of 9 = RP2040 datasheet Table 257
XTAL_ABM8 = {"f": 12e6, "CL": 10e-12, "ESR": 50.0, "C0": 3e-12, "drive_max": 200e-6, "ppm": 30 + 30 + 5}
# Winbond W25Q128JV, SOIC-8 208-mil / WSON-8 (W25Q128JV.pdf 3.1 / 3.3 p.5) and the RP2040 QSPI pin on each
W25_PINS = {"1": "/CS", "2": "DO(IO1)", "3": "/WP(IO2)", "4": "GND", "5": "DI(IO0)", "6": "CLK", "7": "/HOLD(IO3)",
            "8": "VCC"}
W25_ALIASES = {"/CS": ("CS", "CS#", "NCS", "~{CS}"), "DO(IO1)": ("DO", "IO1", "SO", "DO_IO1", "SO/IO1"),
               "/WP(IO2)": ("WP", "IO2", "/WP", "~{WP}_IO2", "WP/IO2", "/WP/IO2"),
               "DI(IO0)": ("DI", "IO0", "SI", "DI_IO0", "SI/IO0"), "CLK": ("SCK", "SCLK"),
               "/HOLD(IO3)": ("HOLD", "IO3", "/HOLD", "~{HOLD}_IO3", "/HOLD/IO3", "/HOLDOR/RESET(IO3)",
                              "HOLD/IO3", "/RESET(IO3)"),
               "VCC": ("VDD",), "GND": ("VSS",)}
W25_QSPI = {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "5": "QSPI_SD0", "6": "QSPI_SCLK", "7": "QSPI_SD3"}
W25_VCC = (2.7, 3.6)          # 9.2 p.60 (3.0-3.6 V for 133 MHz)
W25_VCC_ABS = 4.6             # 9.1 p.60
W25_ICC_MAX = 0.025           # 9.4 p.62
AP2112_THETA_JA = 184.0       # SOT25, C/W (DS39724 p.3)
CH334_I_MAX = 0.085           # CH334 datasheet p.28: "maximum power consumption of the HUB chip 85 mA"
AP2112_IOUT = 0.600           # IOUT(MAX) min (p.8)


def rp_norm(s):
    """Pin-name key for the RP2040 / flash tables: norm_pin_name, also ignoring '/', '{', '}'."""
    return re.sub(r"[/{}()]", "", norm_pin_name(s))


def rp_pin_by_name(name):
    """'PIN_26' / 'GPIO26' / 'GP26' / 'GPIO26/ADC0' -> RP2040 pad number, or None."""
    m = re.fullmatch(r"(?:PIN_?|GPIO|GP)(\d+)(?:[/_]ADC\d)?", (name or "").strip().upper())
    if not m:
        return None
    want = "GPIO%d" % int(m.group(1))
    for pad, nm in RP_PINS.items():
        if nm.split("/")[0] == want:
            return pad
    return None


# Other fixed pinouts (datasheets)
USBC_ROLE = {"A1": "GND", "A4": "VBUS", "A5": "CC1", "A6": "D+", "A7": "D-", "A8": "SBU", "A9": "VBUS",
             "A12": "GND", "B1": "GND", "B4": "VBUS", "B5": "CC2", "B6": "D+", "B7": "D-", "B8": "SBU",
             "B9": "VBUS", "B12": "GND"}
USBLC6_ROLE = {"1": "IO1", "2": "GND", "3": "IO2", "4": "IO2", "5": "VBUS", "6": "IO1"}
AP2112_ROLE = {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"}
SOT23_PMOS_ROLE = {"1": "G", "2": "S", "3": "D"}

# Single-cell Li-ion chargers in SOT-23-5.  Both models put the same functions on the same pins
# (TP4054: C32574.pdf p.6; MCP73831: MCP73831_C424093.pdf p.1 / p.11 Table 3-1); the roles are generic,
# "aliases" are the names each datasheet (or a KiCad symbol) uses for the pin.
CHARGER_ROLE = {"1": "STAT", "2": "GND", "3": "BAT", "4": "VDD", "5": "PROG"}
CHARGER_ALIASES = {"STAT": {"STAT", "CHRG", "/CHRG", "STAT1"}, "GND": {"GND", "VSS"},
                   "BAT": {"BAT", "BATT", "VBAT"}, "VDD": {"VDD", "VCC", "VIN"}, "PROG": {"PROG"}}
CHARGER_MODELS = {
    # model: STAT output type, VOL typ at the LED current, sink / source limits (mA), VDD bypass minimum,
    #        VBAT capacitor minimum (None = only recommended), source key
    "TP4054": {"stat": "open-drain", "vol": 0.3, "sink_mA": 10.0, "source_mA": 0.0, "vdd_cap": 1e-6,
               "vbat_cap": None, "src": "TP_chrg", "lcsc": "C32574"},
    "MCP73831": {"stat": "tri-state", "vol": 0.4, "sink_mA": 25.0, "source_mA": 35.0, "voh_drop": 0.4,
                 "vdd_cap": 4.7e-6, "vbat_cap": 4.7e-6, "src": "MCP_stat", "lcsc": "C424093"},
    "MCP73832": {"stat": "open-drain", "vol": 0.4, "sink_mA": 25.0, "source_mA": 0.0,
                 "vdd_cap": 4.7e-6, "vbat_cap": 4.7e-6, "src": "MCP_stat", "lcsc": ""},
}
# MCP7383X-n regulation voltage (MCP73831_C424093.pdf p.3 / p.26) and the option-AC thresholds (p.26)
MCP_VREG = {"2": 4.20, "3": 4.35, "4": 4.40, "5": 4.50}
MCP_OPT_AC = {"ipreg": 0.10, "vpth": 0.665, "vpth_min": 0.64, "iterm": 0.075, "vrth": 0.965}
MCP_LCSC_PART = {"C424093": "MCP73831T-2ACI/OT"}   # PARTS.txt
MCP_THETA_JA = 230.0          # SOT-23-5, C/W (p.5)
MCP_RPROG = (2e3, 67e3)       # charge-current range (p.4)
MCP_ZNOBAT = 7e6              # minimum VBAT impedance for battery-insertion detection (p.4, p.13)
MCP_IDET_MIN = 0.6e-6         # minimum battery detection current (p.4, p.13)

# WCH CH334P QFN-16 (CH334_C5373042-p2-pinout.png); the exposed pad is "pin 0" in the drawing.
CH334P_PINS = {"1": "XO", "2": "XI", "3": "DM4", "4": "DP4", "5": "DM3", "6": "DP3", "7": "DM2", "8": "DP2",
               "9": "DM1", "10": "DP1", "11": "DMU", "12": "DPU", "13": "RESET#/CDP", "14": "PGANG",
               "15": "V5", "16": "VDD33"}
# C-Media CM108B LQFP-48 (CM108B_datasheet_v1.41.pdf p.6-8)
CM108B_PINS = {"1": "SPDIFO", "2": "DR", "3": "DW", "4": "SK", "5": "CS", "6": "MUTER", "7": "PWRSEL",
               "8": "DREG18", "9": "DREG33", "10": "MODE", "11": "NC", "12": "LEDO", "13": "GPIO3",
               "14": "DVSS", "15": "GPIO4", "16": "SDIN", "17": "ADSCLK", "18": "MUTEP", "19": "ADLRCK",
               "20": "ADMCLK", "21": "LEDR", "22": "ADSEL", "23": "TEST", "24": "AVSS", "25": "VBIAS",
               "26": "VREF", "27": "MICIN", "28": "NC", "29": "AVDD", "30": "LOL", "31": "LOBS", "32": "LOR",
               "33": "AVSS", "34": "AVDD", "35": "DVDD", "36": "DVSS", "37": "AREG36", "38": "MSEL",
               "39": "VOLUP", "40": "PDSW", "41": "USBDP", "42": "USBDM", "43": "GPIO1", "44": "SDOUT",
               "45": "DAMCLK", "46": "DALRCK", "47": "DASCLK", "48": "VOLDN"}
CM108B_FLOAT_OK = {  # pins that may stay open: internal pull-up / pull-down or outputs (p.7-8), N.C.
    "SPDIFO", "DR", "DW", "SK", "CS", "MUTER", "PWRSEL", "MODE", "NC", "LEDO", "GPIO3", "GPIO4", "SDIN",
    "ADSCLK", "MUTEP", "ADLRCK", "ADMCLK", "LEDR", "ADSEL", "TEST", "MSEL", "VOLUP", "PDSW", "GPIO1",
    "SDOUT", "DAMCLK", "DALRCK", "DASCLK", "VOLDN"}
CM108B_JUMPERS = {"PWRSEL": "PU", "MODE": "PD", "MSEL": "PU", "ADSEL": "PD", "TEST": "PD"}
# TI TPA6132A2 RTE (TPA6132A2_C69901.pdf p.3); thermal pad separate
TPA6132_PINS = {"1": "INL-", "2": "INL+", "3": "INR+", "4": "INR-", "5": "OUTR", "6": "G0", "7": "G1",
                "8": "HPVSS", "9": "CPN", "10": "PGND", "11": "CPP", "12": "HPVDD", "13": "EN", "14": "VDD",
                "15": "SGND", "16": "OUTL"}
TPA_RIN = {"-6": 26.4e3, "0": 19.8e3, "3": 16.5e3, "6": 13.2e3}   # p.5, per input pin
TPA_GAIN = {(0, 0): "-6", (1, 0): "0", (0, 1): "3", (1, 1): "6"}  # (G0, G1) -> dB, p.13
# TI TPS22919 DCK (TPS22919_C2149796.pdf p.3)
TPS22919_PINS = {"1": "IN", "2": "GND", "3": "ON", "4": "NC", "5": "QOD", "6": "VOUT"}
TPS_RQOD = 24.0               # internal quick-output-discharge resistance (p.5)
TPS_SR = 3.2e3                # turn-on slew rate at VIN = 5 V, V/s (p.5)
# Hroparts PJ-320D-4A: contact per drawing pin number and per KiCad footprint pad name (see SRC["JACK"])
JACK_CONTACT = {"1": "sleeve", "2": "tip", "3": "ring1", "4": "ring2",
                "S": "sleeve", "T": "tip", "R1": "ring1", "R2": "ring2"}
JACK_CTIA = {"tip": "left", "ring1": "right", "ring2": "ground", "sleeve": "mic"}

# Nominal / maximum voltages used for current and level estimates
V_VBUS_NOM, V_VBUS_MAX = 5.0, 5.5          # USB
V_VBAT_MAX = 4.2                           # 4.2 V Li-ion float voltage (TP4054 / MCP73831-2)
V_VDD = 3.3                                # AP2112K-3.3
V_SCHOTTKY = 0.35                          # B5819W at ~100 mA (VF 0.6 V at 1 A)
SAADC_CSAMPLE = 2.5e-12                    # nrf52840 PS p.397, at maximum gain (the largest value)
SAADC_FS_1_6 = 3.6                         # gain 1/6 with the 0.6 V internal reference (PS p.379)
SAADC_TACQ = [(10e3, 3), (40e3, 5), (100e3, 10), (200e3, 15), (400e3, 20), (800e3, 40)]   # Table 95
LED_DATA = {  # key -> (Vf typical, Vf min, IF max mA, source)
    "C2286": (2.0, 1.8, 25.0, "LED_red"),
    "C2290": (2.85, 2.6, 30.0, "LED_white"),
}
CRYSTAL_FC135 = {"CL": 12.5e-12, "ESR": 70e3, "C0": 1e-12, "drive": 0.5e-6}
NRF_LFXO = {"CL": 12.5e-12, "ESR_max": 100e3, "C0_max": 2e-12, "drive_max": 0.5e-6, "Cpin": 4e-12}


# ----------------------------------------------------------------------------
# Value parsing
# ----------------------------------------------------------------------------
_SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6,
       "R": 1.0, "r": 1.0, "": 1.0}


def parse_number(text, unit):
    """Parse '10k', '5k1', '4R7', '806k', '2M', '10uF', '22pF', '1nF'.  unit: 'R' or 'F'."""
    if text is None:
        return None
    s = text.strip()
    m = re.fullmatch(r"(\d+)([pnuµmkKMRr])(\d+)", s)
    if m:
        return (float(m.group(1)) + float(m.group(3)) / 10 ** len(m.group(3))) * _SI[m.group(2)]
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([pnuµmkKM]?)\s*(?:F|f|Ω|[Oo]hms?|R)?", s)
    if m:
        mult = m.group(2)
        if unit == "R" and mult == "m":
            return None  # milliohm resistors are not plausible here; refuse to guess
        return float(m.group(1).replace(",", ".")) * _SI[mult]
    return None


def fmt_r(r):
    if r is None:
        return "?"
    if r >= 1e6:
        return "%gM" % (r / 1e6)
    if r >= 1e3:
        return "%gk" % (r / 1e3)
    return "%g" % r


def fmt_c(c):
    if c is None:
        return "?"
    if c >= 1e-6:
        return "%guF" % (c / 1e-6)
    if c >= 1e-9:
        return "%gnF" % (c / 1e-9)
    return "%gpF" % (c / 1e-12)


# ----------------------------------------------------------------------------
# Part classification (never by reference designator)
# ----------------------------------------------------------------------------
def charger_model(p):
    """'TP4054' / 'MCP73831' / 'MCP73832' from LCSC code or value (never from a free-text note), else None."""
    vu = (p.get("value") or "").upper()
    lcsc = (p.get("lcsc") or "").upper()
    if "TP4054" in vu or lcsc == "C32574":
        return "TP4054"
    if lcsc in MCP_LCSC_PART or "MCP73831" in vu:
        return "MCP73831"
    if "MCP73832" in vu:
        return "MCP73832"
    return None


def mcp_vreg(p):
    """Regulation voltage of an MCP7383X from its LCSC code or ordering code in value/note, else None."""
    lcsc = (p.get("lcsc") or "").upper()
    txt = MCP_LCSC_PART.get(lcsc, "") + " " + (p.get("value") or "") + " " + (p.get("note") or "")
    m = re.search(r"MCP7383[12]T?-(\d)", txt.upper())
    return MCP_VREG.get(m.group(1)) if m else None


def norm_pin_name(s):
    """Pin-name comparison key: case, spaces, dots, underscores and '#' ignored ('N.C.' == 'NC')."""
    return re.sub(r"[\s._#~]", "", (s or "").upper())


def classify(p):
    v = (p.get("value") or "")
    vu = v.upper()
    fp = (p.get("footprint") or "").upper()
    lcsc = (p.get("lcsc") or "").upper()
    pins = p.get("pins", {})
    pin_names = {str(k): (d.get("name") or "").upper() for k, d in pins.items()}
    n = len(pins)
    if lcsc == "C356849" or "E73-2G4M08S1C" in vu or ("E73" in fp and n >= 40):
        return "module"
    names = {rp_norm(x) for x in pin_names.values()}
    if lcsc == "C2040" or re.search(r"\bRP2040\b", vu) \
            or (n >= 56 and "QFN-56" in fp and {"QSPISS", "VREGVOUT", "USBVDD", "TESTEN"} <= names):
        return "rp2040"
    if lcsc == "C97521" or re.search(r"\bW25Q\d+", vu) \
            or (n == 8 and {"CS", "CLK", "VCC", "GND"} <= names and ("DIIO0" in names or "IO0" in names)):
        return "flash"
    if lcsc == "C165948" or "TYPE-C" in fp or "USB_C" in fp or "USB-C" in fp or "USB-C" in vu \
            or ("A5" in pins and "B5" in pins and "A4" in pins):
        return "usbc"
    if "USBLC6" in vu or lcsc == "C7519":
        return "esd"
    if charger_model(p):
        return "charger"
    if lcsc == "C5373042" or re.search(r"\bCH33[45]", vu):
        return "hub"
    if lcsc == "C371347" or re.search(r"CM10[89]B?|CM119", vu):
        return "codec"
    if lcsc == "C69901" or "TPA6132" in vu:
        return "hpamp"
    if lcsc == "C2149796" or "TPS22919" in vu:
        return "loadsw"
    if lcsc == "C95562" or "PJ-320D" in vu or "PJ-320D" in fp:
        return "jack"
    if "AP2112" in vu or lcsc == "C51118":
        return "ldo"
    if lcsc == "C10487" or re.search(r"SI2301|AO3407|AO3401|DMG2301|DMG3415", vu):
        return "pmos"
    if lcsc == "C8598" or re.search(r"B58(17|18|19)W|1N5819|SS1[24]|MBR0520", vu):
        return "schottky"
    if lcsc == "C81598" or "1N4148" in vu:
        return "mdiode"
    if lcsc in ("C2857263", "C193402") or re.search(r"\bSM[AFB]J?5\.0A\b", vu):
        return "tvs"
    if lcsc == "C32346" or "CRYSTAL" in fp or re.search(r"32[.,]?768", vu):
        return "xtal"
    if lcsc in ("C2286", "C2290", "C72043", "C72041") or "LED" in fp or "LED" in vu \
            or vu.startswith("KT-0603") or vu.startswith("19-217"):
        return "led"
    if lcsc in ("C2803348", "C41430893", "C49352235") or "HOTSWAP" in fp or "SWITCH_KEYBOARD" in fp:
        return "key"
    if lcsc == "C470754" or "EC11" in vu or "ROTARYENCODER" in fp:
        return "enc"
    if lcsc == "C221660" or "JS102011" in vu or "SW_SPDT" in fp:
        return "slide"
    if lcsc == "C318884" or "SW-SMD_4P" in fp or "SW_PUSH" in fp or "TACT" in fp or "TS-1187" in vu \
            or (vu == "RESET" and n == 4):
        return "tact"
    if "JUMPER" in fp or "SOLDERJUMPER" in vu or "JUMPER" in vu:
        return "jumper"
    if "TESTPOINT" in fp or "TESTPOINT" in vu or "TEST_POINT" in fp:
        return "tp"
    if re.search(r"RESISTOR|(^|:)R_\d{4}", fp) or (n == 2 and not fp and parse_number(v, "R") is not None
                                                   and not re.search(r"F$", v)):
        return "res"
    if re.search(r"CAPACITOR|(^|:)C_\d{4}", fp) or re.fullmatch(r"\d+(?:[.,]\d+)?\s*[pnuµ]F?", v):
        return "cap"
    if re.search(r"INDUCTOR|(^|:)L_\d{4}", fp):
        return "ind"
    if lcsc == "C295747" or "JST" in fp or "BATTERY" in vu or "CONN" in vu or "PINHEADER" in fp \
            or "CONNECTOR" in fp or "PRO_MICRO" in fp or "PROMICRO" in vu:
        return "conn"
    return "other"


def led_params(p):
    """(Vf typ, Vf min, IF max, source) for a LED part; generic assumption when unknown."""
    lcsc = (p.get("lcsc") or "").upper()
    vu = (p.get("value") or "").upper()
    if lcsc in LED_DATA:
        return LED_DATA[lcsc] + (False,)
    if "KT-0603R" in vu or "RED" in vu:
        return LED_DATA["C2286"] + (True,)
    if "KT-0603W" in vu or "WHITE" in vu:
        return LED_DATA["C2290"] + (True,)
    if "BHC" in vu or "BLUE" in vu:
        return (2.8, 2.5, 20.0, "LED_white", True)   # blue: assumed similar to white
    if "GHC" in vu or "GREEN" in vu:
        return (2.1, 1.8, 20.0, "LED_red", True)     # green: assumed ~2.1 V
    return (2.0, 1.8, 20.0, "LED_red", True)


# ----------------------------------------------------------------------------
# Netlist model
# ----------------------------------------------------------------------------
class Netlist:
    def __init__(self, data):
        self.data = data
        self.parts = data["parts"]
        self.nets = data["nets"]
        self.kind = {ref: classify(p) for ref, p in self.parts.items()}
        self.members = defaultdict(list)       # net -> [(ref, pin)] fitted parts only
        self.members_all = defaultdict(list)   # including DNP parts
        for ref, p in self.parts.items():
            for pin, pd in p["pins"].items():
                net = pd.get("net")
                if net is None:
                    continue
                self.members_all[net].append((ref, str(pin)))
                if not p.get("dnp"):
                    self.members[net].append((ref, str(pin)))
        self.module = self.first("module")
        # the MCU: the E73 module, or (wired variant) a bare RP2040; the E73 keeps precedence
        rps = [r for r in self.refs("rp2040") if not self.dnp(r)]
        self.rp = rps[0] if rps and not self.module else None
        self.mcu = self.module or self.rp
        self.mcu_word = "module" if self.module else ("RP2040" if self.rp else "MCU")
        self.labels = {}
        self._roles()

    # --- basic access ------------------------------------------------------
    def refs(self, kind):
        return [r for r, k in self.kind.items() if k == kind]

    def first(self, kind):
        lst = self.refs(kind)
        return lst[0] if lst else None

    def dnp(self, ref):
        return bool(self.parts[ref].get("dnp"))

    def value(self, ref):
        return self.parts[ref].get("value") or ""

    def net(self, ref, pin):
        pd = self.parts[ref]["pins"].get(str(pin))
        return pd.get("net") if pd else None

    def pin_name(self, ref, pin):
        pd = self.parts[ref]["pins"].get(str(pin))
        return (pd.get("name") or "") if pd else ""

    def pins_of(self, ref):
        return list(self.parts[ref]["pins"].keys())

    def modpin(self, pin):
        return self.net(self.module, pin) if self.module else None

    def desc(self, ref):
        p = self.parts[ref]
        return "%s (%s%s)" % (ref, p.get("value") or "?", ", DNP" if p.get("dnp") else "")

    def label(self, net):
        if net is None:
            return "<unconnected>"
        role = self.labels.get(net)
        return "%s[=%s]" % (net, role) if role and role != net else net

    def mems(self, net, exclude=None):
        return [(r, p) for r, p in self.members.get(net, []) if r != exclude]

    def module_pins_on(self, net):
        if not self.module:
            return []
        return [int(p) for r, p in self.members.get(net, []) if r == self.module]

    # --- the MCU (E73 module or RP2040) ----------------------------------------
    def rppin(self, pin):
        return self.net(self.rp, pin) if self.rp else None

    def mcupin(self, pin):
        return self.net(self.mcu, pin) if self.mcu else None

    def mcu_gpio(self):
        """GPIO-capable pins of the MCU (E73: every P0.xx/P1.xx pin; RP2040: GPIO0-29)."""
        if self.module:
            return set(E73_GPIO)
        return set(RP_GPIO) if self.rp else set()

    def mcu_pin_label(self, pin):
        if self.module:
            return E73_PINS[int(pin)][0]
        return RP_PINS.get(int(pin), "?") if self.rp else "?"

    def mcu_pin_by_name(self, name):
        if self.module:
            return e73_pin_by_name(name)
        return rp_pin_by_name(name) if self.rp else None

    def mcu_pins_on(self, net):
        if not self.mcu:
            return []
        return [int(p) for r, p in self.members.get(net, []) if r == self.mcu]

    def mcu_gpio_nets(self):
        """{net: pin} for the connected MCU GPIO pins."""
        g = self.mcu_gpio()
        return {self.mcupin(p): p for p in g if self.mcupin(p)}

    def pin_by_role(self, ref, roles, want):
        """pin number of part ref whose datasheet role is `want` (roles: pin -> role)."""
        for pin, role in roles.items():
            if role == want and pin in self.parts[ref]["pins"]:
                return pin
        return None

    def other_end(self, ref, pin):
        """For a 2-pin part: (other pin, other net)."""
        pins = self.pins_of(ref)
        if len(pins) != 2:
            return None, None
        o = pins[0] if pins[1] == str(pin) else pins[1]
        return o, self.net(ref, o)

    def two_pin_parts_on(self, net, kinds, exclude=None):
        """[(ref, pin, other_net)] for fitted 2-pin parts of the given kinds touching `net`."""
        out = []
        for ref, pin in self.members.get(net, []):
            if ref == exclude or self.kind[ref] not in kinds or len(self.pins_of(ref)) != 2:
                continue
            o, onet = self.other_end(ref, pin)
            out.append((ref, pin, onet))
        return out

    def resistors_between(self, a, b):
        return [(ref, parse_number(self.value(ref), "R"))
                for ref, pin, onet in self.two_pin_parts_on(a, ("res",)) if onet == b]

    def caps_between(self, a, b):
        return [(ref, parse_number(self.value(ref), "F"))
                for ref, pin, onet in self.two_pin_parts_on(a, ("cap",)) if onet == b]

    # --- diode / LED polarity helpers ----------------------------------------
    def diode_ak(self, ref):
        """(anode pin, cathode pin, assumed) using pin names K/A, else SOD-123/LED convention 1=K 2=A."""
        pins = self.pins_of(ref)
        names = {p: self.pin_name(ref, p).upper() for p in pins}
        a = [p for p, n in names.items() if n in ("A", "ANODE", "+")]
        k = [p for p, n in names.items() if n in ("K", "C", "CATHODE", "-")]
        if len(a) == 1 and len(k) == 1:
            return a[0], k[0], False
        if "1" in pins and "2" in pins:
            return "2", "1", True
        return None, None, True

    # --- role nets -----------------------------------------------------------
    def _roles(self):
        self.gnd = self.vbus = self.vdd = self.vddh = None
        self.vin = self.vbat = self.batp = None
        self.ldo_main = None
        u = self.first("usbc")
        if self.module:
            self.gnd = self.modpin(E73_GND[0])
            self.vbus = self.modpin(E73_VBUS)
            self.vdd = self.modpin(E73_VDD)
            self.vddh = self.modpin(E73_VDDH)
        # the receptacle defines VBUS and GND when present (the module pins are then checked against it)
        if u:
            vbus_pads = [p for p, r in USBC_ROLE.items() if r == "VBUS" and p in self.parts[u]["pins"]]
            gnd_pads = [p for p, r in USBC_ROLE.items() if r == "GND" and p in self.parts[u]["pins"]]
            if vbus_pads and self.net(u, vbus_pads[0]) is not None:
                self.vbus = self.net(u, vbus_pads[0])
            if gnd_pads and self.net(u, gnd_pads[0]) is not None and self.gnd is None:
                self.gnd = self.net(u, gnd_pads[0])
        if self.rp:
            # RP2040: the 3.3 V rail is the IOVDD net (pin 1); GND from the receptacle, else the RP2040 ground pad
            if self.gnd is None:
                self.gnd = self.rppin(RP_GND)
            self.vdd = self.rppin(RP_IOVDD[0])
        for ldo in self.refs("ldo"):
            if self.net(ldo, "5") == self.vdd and self.vdd is not None:
                self.ldo_main = ldo
                vin = self.net(ldo, "1")
                # VIN is the power-path node behind the Schottky; an LDO fed straight from VBUS has none
                self.vin = vin if vin != self.vbus else None
        # charger (TP4054 or MCP73831/2: same SOT-23-5 functions, BAT = pin 3)
        chs = [r for r in self.refs("charger") if not self.dnp(r)]
        self.charger = chs[0] if chs else None
        self.chg_model = charger_model(self.parts[self.charger]) if self.charger else None
        if self.charger:
            self.vbat = self.net(self.charger, self.pin_by_role(self.charger, CHARGER_ROLE, "BAT"))
        # switched audio rail: output of a TPS22919 whose input is VBUS
        self.vaud = None
        for sw in self.refs("loadsw"):
            if not self.dnp(sw) and self.net(sw, "1") == self.vbus and self.vbus is not None \
                    and self.net(sw, "6") not in (None, self.vbus, self.gnd):
                self.vaud = self.net(sw, "6")
                break
        # battery connector: 2 signal pins, one on GND; the other one is BAT+
        self.batconn = None
        for ref in self.refs("conn"):
            sig = [p for p in self.pins_of(ref) if self.pin_name(ref, p).upper() not in ("MP", "SHIELD", "S1")
                   and not p.upper().startswith("MP")]
            if len(sig) != 2:
                continue
            nets = [self.net(ref, p) for p in sig]
            if self.gnd in nets and any(n and n != self.gnd for n in nets):
                other = [n for n in nets if n != self.gnd][0]
                if other == self.vbat or self._reaches_vbat(other):
                    self.batconn = ref
                    self.batp = other
                    break
        for net, role in ((self.gnd, "GND"), (self.vbus, "VBUS"), (self.vdd, "VDD"), (self.vin, "VIN"),
                          (self.vbat, "VBAT"), (self.batp, "BAT+"), (self.vaud, "VAUD")):
            if net is not None and net not in self.labels:
                self.labels[net] = role

    def _reaches_vbat(self, net):
        """True if `net` is tied to VBAT through a slide switch or a jumper (power switch in series)."""
        if self.vbat is None:
            return False
        for ref, pin in self.members_all.get(net, []):
            if self.kind[ref] in ("slide", "jumper"):
                for p in self.pins_of(ref):
                    if self.net(ref, p) == self.vbat:
                        return True
        return False

    def power_nets(self):
        return {n: r for n, r in ((self.gnd, "GND"), (self.vbus, "VBUS"), (self.vdd, "VDD"),
                                  (self.vin, "VIN"), (self.vbat, "VBAT"), (self.batp, "BAT+"),
                                  (self.vaud, "VAUD")) if n}

    # --- helpers for the IC checks ---------------------------------------------
    def fitted(self, kind):
        return [r for r in self.refs(kind) if not self.dnp(r)]

    def extra_pins(self, ref, table):
        """Pins of `ref` that are not in the datasheet pin table (exposed pad, mounting pads)."""
        return [p for p in self.pins_of(ref) if p not in table]

    def name_mismatches(self, ref, table, aliases=None):
        """['pin p named X, datasheet Y', ...] for named pins that disagree with the datasheet table."""
        out = []
        aliases = aliases or {}
        for p, want in table.items():
            if p not in self.parts[ref]["pins"]:
                out.append("pin %s missing from the symbol (datasheet: %s)" % (p, want))
                continue
            got = self.pin_name(ref, p)
            if not got or got in ("~",):
                continue
            ok = {norm_pin_name(want)} | {norm_pin_name(a) for a in aliases.get(want, ())}
            if norm_pin_name(got) not in ok:
                out.append("pin %s is named '%s' in the netlist but the datasheet has %s" % (p, got, want))
        return out

    def cap_list(self, net, other=None):
        """[(ref, farad)] capacitors from `net` to `other` (default GND)."""
        if net is None:
            return []
        return self.caps_between(net, self.gnd if other is None else other)

    def cap_total(self, net, other=None):
        return sum(c for _, c in self.cap_list(net, other) if c)

    def non_cap_members(self, net, exclude=()):
        """Members of `net` other than capacitors to GND and the parts in `exclude`."""
        out = []
        for r, p in self.mems(net):
            if r in exclude:
                continue
            if self.kind[r] == "cap" and len(self.pins_of(r)) == 2 and self.other_end(r, p)[1] == self.gnd:
                continue
            out.append((r, p))
        return out

    def through_series(self, net, kinds=("ind",), max_ohm=None, depth=2, exclude=(), no_enter=()):
        """Nets reachable from `net` through 2-pin parts of `kinds` (resistors only if <= max_ohm), never
        entering the nets in `no_enter`: {net: [refs on the way]} including `net` itself."""
        seen = {net: []}
        frontier = [net]
        for _ in range(depth):
            nxt = []
            for n in frontier:
                for ref, pin, onet in self.two_pin_parts_on(n, kinds):
                    if ref in exclude or onet is None or onet in seen or onet in no_enter:
                        continue
                    if self.kind[ref] == "res" and max_ohm is not None:
                        v = parse_number(self.value(ref), "R")
                        if v is None or v > max_ohm:
                            continue
                    seen[onet] = seen[n] + [ref]
                    nxt.append(onet)
            frontier = nxt
        return seen

    def resistance_to_rails(self, start, rails, skip_kinds=()):
        """DC resistance from `start` to the set of `rails` (all at 0 V) through resistors only
        (nodal analysis on the resistor network reachable from `start`).  Returns (ohms or None if no
        path, [resistor refs used])."""
        nodes, used, q = {start}, set(), [start]
        while q:
            n = q.pop()
            if n in rails:
                continue
            for ref, pin, onet in self.two_pin_parts_on(n, ("res",)):
                if onet is None or self.kind[ref] in skip_kinds:
                    continue
                if parse_number(self.value(ref), "R") is None:
                    continue
                used.add(ref)
                if onet not in nodes:
                    nodes.add(onet)
                    q.append(onet)
        if not (nodes & set(rails)):
            return None, sorted(used)
        inner = sorted(n for n in nodes if n not in rails and n != start)
        idx = {n: i for i, n in enumerate(inner)}
        size = len(inner)
        a = [[0.0] * (size + 1) for _ in range(size)]   # G * v = b, start held at 1 V, rails at 0 V
        for ref in used:
            p1, p2 = self.pins_of(ref)
            n1, n2 = self.net(ref, p1), self.net(ref, p2)
            g = 1.0 / parse_number(self.value(ref), "R")
            for x, y in ((n1, n2), (n2, n1)):
                if x in idx:
                    a[idx[x]][idx[x]] += g
                    if y in idx:
                        a[idx[x]][idx[y]] -= g
                    elif y == start:
                        a[idx[x]][size] += g * 1.0
        for i in range(size):                            # Gaussian elimination
            piv = max(range(i, size), key=lambda r: abs(a[r][i]))
            a[i], a[piv] = a[piv], a[i]
            if abs(a[i][i]) < 1e-30:
                continue
            for r in range(size):
                if r != i and a[r][i]:
                    f = a[r][i] / a[i][i]
                    a[r] = [x - f * y for x, y in zip(a[r], a[i])]
        v = {n: (a[idx[n]][size] / a[idx[n]][idx[n]] if abs(a[idx[n]][idx[n]]) > 1e-30 else 0.0) for n in inner}
        v[start] = 1.0
        current = 0.0
        for ref in used:
            p1, p2 = self.pins_of(ref)
            n1, n2 = self.net(ref, p1), self.net(ref, p2)
            g = 1.0 / parse_number(self.value(ref), "R")
            if n1 == start and n2 != start:
                current += g * (1.0 - v.get(n2, 0.0))
            elif n2 == start and n1 != start:
                current += g * (1.0 - v.get(n1, 0.0))
        return (1.0 / current if current > 0 else None), sorted(used)

    def net_voltage_max(self, net):
        """Worst-case (highest) DC voltage on a power net, None if not a power net."""
        if net is None:
            return None
        if net == self.gnd:
            return 0.0
        if net in (self.vbus, self.vaud):
            return V_VBUS_MAX
        if net == self.vin:
            return V_VBUS_MAX - 0.3
        if net in (self.vbat, self.batp):
            return V_VBAT_MAX
        if net == self.vdd:
            return V_VDD
        return None

    def net_voltage_nom(self, net):
        if net is None:
            return None
        if net == self.gnd:
            return 0.0
        if net in (self.vbus, self.vaud):
            return V_VBUS_NOM
        if net == self.vin:
            return V_VBUS_NOM - V_SCHOTTKY
        if net in (self.vbat, self.batp):
            return 3.8
        if net == self.vdd:
            return V_VDD
        return None


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.items = []

    def add(self, code, name, status, source_key, details=None):
        src = SRC.get(source_key, source_key)
        self.items.append((code, name, status, src, list(details or [])))

    def print(self, title):
        print("=" * 100)
        print("check_circuit.py - %s" % title)
        print("=" * 100)
        for code, name, status, src, details in self.items:
            print("[%s] %s  %s" % (status, code, name))
            print("       source: %s" % src)
            for d in details:
                print("       - %s" % d)
        counts = {s: sum(1 for i in self.items if i[2] == s) for s in (PASS, FAIL, WARN, SKIP)}
        print("-" * 100)
        print("SUMMARY: %d PASS, %d FAIL, %d WARN, %d SKIP" % (counts[PASS], counts[FAIL], counts[WARN], counts[SKIP]))
        for s in (FAIL, WARN):
            lst = [i for i in self.items if i[2] == s]
            if lst:
                print("%s:" % s)
                for code, name, status, src, details in lst:
                    print("  %s %s" % (code, name))
        print()
        return counts[FAIL] == 0


# ----------------------------------------------------------------------------
# Checks
# ----------------------------------------------------------------------------
def check_consistency(nl, rep):
    """N00: parts[].pins[].net and nets{} describe the same connectivity."""
    bad = []
    seen = set()
    for net, conns in nl.nets.items():
        for ref, pin in conns:
            seen.add((ref, str(pin)))
            if ref not in nl.parts:
                bad.append("net %s lists unknown part %s" % (net, ref))
            elif nl.net(ref, pin) != net:
                bad.append("net %s lists %s.%s but that pin says net %s" % (net, ref, pin, nl.net(ref, pin)))
    for ref, p in nl.parts.items():
        for pin, pd in p["pins"].items():
            if pd.get("net") is not None and (ref, str(pin)) not in seen:
                bad.append("%s.%s says net %s but the net does not list it" % (ref, pin, pd["net"]))
            if pd.get("net") is not None and pd["net"] not in nl.nets:
                bad.append("%s.%s refers to undefined net %s" % (ref, pin, pd["net"]))
    rep.add("N00", "netlist self-consistency (parts vs nets tables)", FAIL if bad else PASS, "NETLIST",
            bad[:20] or ["%d parts, %d nets" % (len(nl.parts), len(nl.nets))])


def check_module_gnd(nl, rep):
    if not nl.module:
        rep.add("M01", "E73 ground pads", SKIP, "E73_pins", ["no E73-2G4M08S1C module found"])
        return
    nets = {p: nl.modpin(p) for p in E73_GND}
    d = ["pin %d -> %s" % (p, nl.label(n)) for p, n in nets.items()]
    ok = len(set(nets.values())) == 1 and None not in nets.values()
    if ok:
        g = nl.gnd
        u = nl.first("usbc")
        if u and nl.net(u, "A1") not in (None, g):
            ok = False
            d.append("USB-C GND pad A1 is on %s, not on the module ground net" % nl.label(nl.net(u, "A1")))
        if len(nl.mems(g)) < 5:
            ok = False
            d.append("ground net has only %d connections" % len(nl.mems(g)))
    rep.add("M01", "E73 ground pads 5/21/24 all on the single ground net", PASS if ok else FAIL, "E73_pins", d)


def check_module_supply(nl, rep):
    if not nl.module:
        rep.add("M02", "E73 VDD/VDDH supply", SKIP, "PS_supply", [])
        return
    vdd, vddh = nl.modpin(E73_VDD), nl.modpin(E73_VDDH)
    d = ["VDD (pin 19) -> %s ; VDDH (pin 23) -> %s" % (nl.label(vdd), nl.label(vddh))]
    status = PASS
    if vdd is None or vddh is None:
        status = FAIL
        d.append("VDD and VDDH must both be connected")
    elif vdd != vddh:
        # high-voltage mode: VDDH supplied, VDD must then be an output (decoupled only)
        status = WARN
        d.append("VDD and VDDH on different nets: high-voltage mode (VDDH 2.5-5.5 V, VDD becomes the REG0 "
                 "output); Lira intends normal-voltage mode, so this is unexpected")
    else:
        d.append("same net -> normal voltage mode (allowed: PS 5.3.1 'pin VDD shorted to pin VDDH'); "
                 "VDD operating range 1.7-3.6 V, abs max 3.9 V")
        ldo = nl.ldo_main
        if ldo:
            vu = nl.value(ldo).upper()
            vout = 3.3 if "3.3" in vu else None
            if vout is None:
                status = WARN
                d.append("LDO %s feeding VDD: output voltage not recognisable from value '%s'" % (ldo, nl.value(ldo)))
            else:
                hi = vout * 1.015
                d.append("rail from %s: %.2f V +-1.5 %% -> max %.3f V (<= 3.6 V operating, < 3.9 V abs max)"
                         % (nl.desc(ldo), vout, hi))
                if hi > 3.6:
                    status = FAIL
                d.append("E73 datasheet: >= 3.3 V supply guarantees the rated output power (p.5)")
        else:
            sources = [(r, p) for r, p in nl.mems(vdd) if nl.kind[r] in ("ldo", "pmos", "conn", "jumper", "ind", "res", "other")]
            if sources:
                status = WARN
                d.append("no AP2112 LDO drives the VDD net; possible sources %s - rail voltage not verified" % sources)
            else:
                status = FAIL
                d.append("the VDD net has no supply at all (only module pins, capacitors, test points)")
        # VDD rail decoupling / bulk capacitor
        caps = [c for c in nl.caps_between(vdd, nl.gnd)]
        tot = sum(c for _, c in caps if c)
        d.append("capacitance VDD-GND on the board: %s (%s)" % (fmt_c(tot) if caps else "none",
                                                                 ", ".join(r for r, _ in caps) or "-"))
        if tot < 1e-6:
            status = FAIL if status == PASS else status
            d.append("at least the LDO output capacitor (>= 1 uF) must sit on this rail")
    rep.add("M02", "E73 VDD and VDDH tied together on the 3.3 V rail (normal voltage mode)", status, "PS_supply", d)


def check_module_vbus(nl, rep):
    if not nl.module:
        rep.add("M03", "E73 VBUS pin", SKIP, "PS_usb", [])
        return
    vbus = nl.modpin(E73_VBUS)
    d = ["VBUS (pin 27) -> %s" % nl.label(vbus)]
    status = PASS
    u = nl.first("usbc")
    if vbus is None:
        status = FAIL
        d.append("VBUS must be connected to the USB 5 V for USB operation")
    elif u:
        pads = [p for p, r in USBC_ROLE.items() if r == "VBUS" and p in nl.parts[u]["pins"]]
        bad = [p for p in pads if nl.net(u, p) != vbus]
        if bad:
            status = FAIL
            d.append("USB-C VBUS pads %s are on %s, not on the module VBUS pin net (the module must see the raw "
                     "USB 5 V, 4.35-5.5 V, not the post-diode VIN or another rail)" % (bad, nl.label(nl.vbus)))
        else:
            d.append("USB-C VBUS pads %s on the same net; USB 5 V is within 4.35-5.5 V operating, 5.8 V abs max" % pads)
    # series resistor recommendation (PS 7.3 p.583)
    direct = any(r == u for r, p in nl.mems(vbus)) if u else False
    if direct:
        d.append("note: the nRF52840 reference circuits (bare chip) put an optional 4R7 series resistor between the "
                 "USB supply and the VBUS pin, 'recommended for new designs' against connection transients; "
                 "none here (the BlueMicro840 has none either) - low risk with the module's internal decoupling")
        status = WARN if status == PASS else status
    rep.add("M03", "E73 VBUS pin on the USB-C VBUS (5 V) net", status, "PS_usb", d)


def check_module_swd(nl, rep):
    if not nl.module:
        rep.add("M05", "SWDIO/SWDCLK", SKIP, "PS_swd", [])
        return
    status = PASS
    d = []
    for pin, nm in ((E73_SWDIO, "SWDIO"), (E73_SWDCLK, "SWDCLK")):
        net = nl.modpin(pin)
        if net is None:
            status = FAIL
            d.append("%s (pin %d) unconnected: no way to flash the bootloader" % (nm, pin))
            continue
        others = nl.mems(net, exclude=nl.module)
        kinds = sorted(set(nl.kind[r] for r, _ in others))
        d.append("%s (pin %d) -> %s : %s" % (nm, pin, nl.label(net), others or "nothing else"))
        if not others:
            status = FAIL
            d.append("%s has no test point / header: programming impossible" % nm)
        if any(k not in ("tp", "conn", "res") for k in kinds):
            status = FAIL
            d.append("%s is loaded by %s - only test points / debug header (and series R) allowed" % (nm, kinds))
        if net in nl.power_nets():
            status = FAIL
            d.append("%s is shorted to %s" % (nm, nl.labels[net]))
    d.append("no external pull resistors needed: SWDIO has an internal pull-up, SWDCLK an internal pull-down (13 kOhm)")
    # programmer also needs GND and VDD (target reference voltage)
    tp_nets = {nl.net(r, p) for r in nl.refs("tp") for p in nl.pins_of(r)}
    for net, nm in ((nl.gnd, "GND"), (nl.vdd, "VDD")):
        if net not in tp_nets and not any(nl.kind[r] == "conn" for r, _ in nl.mems(net)):
            status = WARN if status == PASS else status
            d.append("no test point or header on %s for the programmer" % nm)
    rep.add("M05", "SWDIO/SWDCLK reach a test point or header, nothing else on them", status, "PS_swd", d)


def check_module_reset(nl, rep):
    if not nl.module:
        rep.add("M06", "RESET pin", SKIP, "PS_reset", [])
        return
    net = nl.modpin(E73_RESET)
    d = ["P0.18/RESET (pin 26) -> %s" % nl.label(net)]
    status = PASS
    if net is None:
        status = WARN
        d.append("reset pin unconnected: no hardware reset / DFU entry (double reset) possible")
    else:
        if net in nl.power_nets():
            status = FAIL
            d.append("RESET tied to %s - the chip would be held in reset or the pin shorted" % nl.labels[net])
        others = nl.mems(net, exclude=nl.module)
        d.append("other connections: %s" % (others or "none"))
        for r, p in others:
            k = nl.kind[r]
            if k in ("tp", "conn"):
                continue
            if k == "tact":
                o = [q for q in nl.pins_of(r) if nl.net(r, q) not in (None, net)]
                onets = {nl.net(r, q) for q in o}
                if onets == {nl.gnd}:
                    d.append("%s: push button between RESET and GND (active-low reset, DFU by double tap)" % r)
                elif onets:
                    status = FAIL
                    d.append("%s: button other side on %s, must be GND" % (r, [nl.label(n) for n in onets]))
                continue
            if k == "res":
                _, onet = nl.other_end(r, p)
                if onet == nl.vdd:
                    d.append("%s: external pull-up to VDD (not required: pin has an internal pull-up when used as reset)" % r)
                else:
                    status = FAIL
                    d.append("%s resistor from RESET to %s" % (r, nl.label(onet)))
                continue
            if k == "cap":
                d.append("%s: capacitor on RESET lengthens tPINR (PS p.81) - allowed" % r)
                continue
            status = FAIL
            d.append("%s (%s) must not be connected to RESET" % (r, k))
        d.append("the bootloader maps BUTTON_DFU to P0.18 with pull-up: no external resistor required")
    rep.add("M06", "RESET pin: only button-to-GND / test point / header, never tied to a rail", status, "PS_reset", d)


def check_crystal(nl, rep):
    if not nl.module:
        rep.add("M07", "32.768 kHz crystal and load capacitors", SKIP, "PS_lfxo", [])
        return
    xl1, xl2 = nl.modpin(E73_XL1), nl.modpin(E73_XL2)
    d = ["XL1 (pin 11) -> %s ; XL2 (pin 13) -> %s" % (nl.label(xl1), nl.label(xl2))]
    # the crystal whose pins touch XL1/XL2 (other crystals, e.g. the 12 MHz USB-hub one, are checked elsewhere)
    xt = [r for r in nl.refs("xtal") if not nl.dnp(r)
          and {nl.net(r, p) for p in nl.pins_of(r)} & ({xl1, xl2} - {None})]
    if not xt or xl1 is None or xl2 is None:
        rep.add("M07", "32.768 kHz crystal and load capacitors", FAIL, "PS_lfxo",
                d + ["no crystal between XL1 and XL2 - the E73 module has no 32.768 kHz crystal inside "
                     "(E73 p.6: '32.768KHz crystal must be external'); the bootloader/firmware expect the LFXO"])
        return
    status = PASS
    y = xt[0]
    ynets = {nl.net(y, p) for p in nl.pins_of(y)}
    if ynets != {xl1, xl2}:
        status = FAIL
        d.append("%s pins on %s, expected exactly XL1 and XL2" % (y, [nl.label(n) for n in ynets]))
    else:
        d.append("%s between XL1 and XL2" % nl.desc(y))
    lcsc = (nl.parts[y].get("lcsc") or "").upper()
    if lcsc == "C32346" or "FC-135" in nl.value(y).upper():
        cl = CRYSTAL_FC135["CL"]
        d.append("crystal FC-135: CL 12.5 pF (= PS CL_LFXO 12.5 pF), ESR 70k <= 100k, C0 1 pF <= 2 pF, "
                 "drive 0.5 uW <= 0.5 uW -> all within the nRF52840 LFXO limits")
    else:
        cl = NRF_LFXO["CL"]
        status = WARN if status == PASS else status
        d.append("crystal '%s' not identified; assuming CL = 12.5 pF (PS 5.4.4.3) for the load-cap check" % nl.value(y))
    # load capacitors: C1 = C2 ~ 2*CL - Cpin - Cstray(1-2 pF)
    target = 2 * cl - NRF_LFXO["Cpin"]
    lo, hi = target - 6e-12, target + 2e-12
    vals = {}
    for net, nm in ((xl1, "XL1"), (xl2, "XL2")):
        caps = nl.caps_between(net, nl.gnd)
        extra = [(r, p) for r, p in nl.mems(net) if r not in (nl.module, y) and nl.kind[r] != "cap"]
        if extra:
            status = FAIL
            d.append("%s also connects %s - crystal pins must carry nothing else" % (nm, extra))
        if len(caps) != 1:
            status = FAIL
            d.append("%s: expected exactly one load capacitor to GND, found %s" % (nm, caps))
            continue
        ref, c = caps[0]
        vals[nm] = c
        d.append("%s load capacitor %s = %s" % (nm, ref, fmt_c(c)))
        if c is None or not (lo <= c <= hi):
            status = FAIL if status != FAIL else status
            d.append("%s: C should be about 2*CL - Cpin - Cstray = %s - stray (accepted %s..%s)"
                     % (nm, fmt_c(target), fmt_c(lo), fmt_c(hi)))
    if len(vals) == 2 and vals["XL1"] != vals["XL2"]:
        status = FAIL
        d.append("C1 and C2 must have the same value (PS p.87)")
    rep.add("M07", "32.768 kHz crystal on XL1/XL2 with matched load capacitors (2*CL - Cpin)", status, "PS_lfxo", d)


def check_nfc(nl, rep):
    if not nl.module:
        rep.add("M08", "NFC pins", SKIP, "PS_nfc", [])
        return
    status = PASS
    d = []
    for pin in (E73_NFC1, E73_NFC2):
        net = nl.modpin(pin)
        if net is None:
            d.append("pin %d %s unconnected (fine)" % (pin, E73_PINS[pin][0]))
            continue
        others = nl.mems(net, exclude=nl.module)
        d.append("pin %d %s -> %s : %s" % (pin, E73_PINS[pin][0], nl.label(net), others))
        if net in nl.power_nets():
            status = FAIL
            d.append("NFC pin tied to %s" % nl.labels[net])
        elif others:
            status = WARN if status == PASS else status
            d.append("used as GPIO: UICR NFCPINS.PROTECT must be set to 'Disabled' by the firmware/bootloader, "
                     "and the two pins have higher capacitance / mutual leakage")
    rep.add("M08", "NFC1/NFC2 (P0.09/P0.10) free, or used as GPIO with NFCPINS disabled", status, "PS_nfc", d)


def check_dcch(nl, rep):
    if not nl.module:
        rep.add("M09", "DCCH pin", SKIP, "PS_dcdc", [])
        return
    net = nl.modpin(E73_DCCH)
    d = ["DCCH (pin 25) -> %s" % nl.label(net)]
    status = PASS
    if net is not None:
        fitted = nl.mems(net, exclude=nl.module)
        allm = [(r, p) for r, p in nl.members_all.get(net, []) if r != nl.module]
        if not fitted:
            d.append("only unfitted parts on this net (%s): electrically open -> LDO-only operation" % allm)
        else:
            inds = [(r, p) for r, p in fitted if nl.kind[r] == "ind"]
            if len(fitted) == len(inds) == 1 and nl.other_end(inds[0][0], inds[0][1])[1] == nl.vdd:
                status = WARN
                d.append("inductor %s from DCCH to VDD: DC/DC REG1 configuration (needs the PS LC values, "
                         "firmware may enable DCDCEN only with the inductor fitted)" % inds[0][0])
            else:
                status = FAIL
                d.append("DCCH may only carry the DC/DC inductor to VDD, found %s" % fitted)
    else:
        d.append("unconnected: correct when the internal DC/DC converter is not used (LDO only, PS Fig.13)")
    rep.add("M09", "DCCH open (no DC/DC inductor) or inductor to VDD only", status, "PS_dcdc", d)


def check_gpio_nets(nl, rep):
    if nl.rp:
        check_rp_gpio_nets(nl, rep)
        return
    if not nl.module:
        rep.add("M10", "GPIO nets", SKIP, "E73_pins", [])
        return
    status = PASS
    d = []
    pn = nl.power_nets()
    seen = {}
    for pin in sorted(E73_GPIO):
        net = nl.modpin(pin)
        if net is None:
            continue
        if net in pn:
            status = FAIL
            d.append("pin %d %s is on %s" % (pin, E73_PINS[pin][0], nl.labels[net]))
        if net in seen:
            status = FAIL
            d.append("pins %d and %d (%s, %s) are shorted on net %s" % (seen[net], pin, E73_PINS[seen[net]][0],
                                                                        E73_PINS[pin][0], net))
        seen[net] = pin
    # fixed pins must not share nets with GPIO either
    for pin in (E73_VBUS, E73_DP, E73_DN, E73_SWDIO, E73_SWDCLK):
        net = nl.modpin(pin)
        if net in seen:
            status = FAIL
            d.append("fixed pin %d %s shares net %s with GPIO pin %d" % (pin, E73_PINS[pin][0], net, seen[net]))
    used = sorted(seen.values())
    d.append("%d GPIO-capable pins connected (incl. XL1/XL2, RESET, AIN): %s"
             % (len(used), [E73_PINS[p][0].split("/")[0] for p in used]))
    rep.add("M10", "no GPIO tied to a power rail, no two module pins shorted together", status, "E73_pins", d)


def check_gpio_overvoltage(nl, rep):
    """M11: nothing pulls a module GPIO above VDD (CHRG-style pull-up to 5 V, LED from VBUS, ...)."""
    if nl.rp:
        check_rp_gpio_overvoltage(nl, rep)
        return
    if not nl.module:
        rep.add("M11", "GPIO over-voltage", SKIP, "PS_gpio", [])
        return
    status = PASS
    d = []
    hi_nets = {n for n in (nl.vbus, nl.vin, nl.vbat, nl.batp, nl.vaud) if n}
    for pin in sorted(E73_GPIO):
        net = nl.modpin(pin)
        if net is None:
            continue
        name = E73_PINS[pin][0]
        for ref, p, onet in nl.two_pin_parts_on(net, ("res", "ind", "jumper", "led", "schottky", "mdiode")):
            if onet not in hi_nets:
                continue
            k = nl.kind[ref]
            vmax = nl.net_voltage_max(onet)
            if k == "res":
                rtop = parse_number(nl.value(ref), "R")
                rbot = [v for _, v in nl.resistors_between(net, nl.gnd)]
                if not rbot or rtop is None or any(v is None for v in rbot):
                    status = FAIL
                    d.append("pin %d %s pulled to %s through %s with no divider to GND -> %.1f V on a 3.3 V I/O"
                             % (pin, name, nl.labels[onet], ref, vmax))
                    continue
                rb = 1 / sum(1 / v for v in rbot)
                v = vmax * rb / (rtop + rb)
                d.append("pin %d %s: divider %s / %s from %s -> %.2f V max (limit VDD+0.3 = %.1f V)"
                         % (pin, name, fmt_r(rtop), fmt_r(rb), nl.labels[onet], v, V_VDD + 0.3))
                if v > V_VDD + 0.3:
                    status = FAIL
            elif k == "led":
                vf_typ, vf_min, _, _, _ = led_params(nl.parts[ref])
                v = vmax - vf_min
                a, kk, _ = nl.diode_ak(ref)
                if nl.net(ref, a) == onet:
                    d.append("pin %d %s: LED %s from %s to the pin -> up to %.2f V when the pin is high-Z"
                             % (pin, name, ref, nl.labels[onet], v))
                    if v > V_VDD + 0.3:
                        status = WARN if status == PASS else status
                        d.append("exceeds VI/O max VDD+0.3 V: use a LED with higher VF or drive from VDD")
            else:
                status = FAIL
                d.append("pin %d %s directly bridged to %s by %s" % (pin, name, nl.labels[onet], ref))
    if not d:
        d.append("no resistor / LED / jumper from a GPIO net to VBUS, VIN, VBAT or the switched 5 V (VAUD)")
    d.append("E73 I/O level is 3.3 V; 5 V signals would need 1k-5.1k series resistors (E73 p.9) - none present")
    rep.add("M11", "no pull-up above VDD into a GPIO (divider/LED analysis vs VI/O max VDD+0.3 V)", status, "PS_gpio", d)


def check_module_pin_names(nl, rep):
    if not nl.module:
        rep.add("M12", "module symbol pin names", SKIP, "E73_pins", [])
        return
    status = PASS
    d = []
    pins = nl.parts[nl.module]["pins"]
    missing = [p for p in E73_PINS if str(p) not in pins]
    if missing:
        status = FAIL
        d.append("module symbol lacks pins %s" % missing)
    named = 0
    for p, (fn, ball) in E73_PINS.items():
        nm = nl.pin_name(nl.module, p).upper().replace("USB_", "")
        if not nm:
            continue
        named += 1
        exp = fn.upper()
        if nm.split("/")[0] != exp.split("/")[0] and nm != exp:
            status = FAIL
            d.append("pin %d is named '%s' in the netlist but the datasheet says %s (ball %s)" % (p, nm, fn, ball))
    d.append("%d of 43 pins carry a name in the netlist; all compared names match the datasheet" % named
             if status == PASS else "%d pins named" % named)
    rep.add("M12", "E73 symbol pin numbers/names agree with the datasheet pin table", status, "E73_pins", d)


# ----------------------------------------------------------------- RP2040 ---
# Wired variant: a bare RP2040 with the minimum circuit of Hardware design with RP2040 (the Pico's).
def rp_chip(nl, rep, code, title, src):
    """The RP2040 ref, or None after adding a SKIP line for `code`."""
    if nl.rp:
        return nl.rp
    rep.add(code, title, SKIP, src, ["no RP2040 in this netlist%s" % (" (the MCU is the E73 module)" if nl.module else "")])
    return None


def rp_label(pin):
    return "%s (%d)" % (RP_PINS[int(pin)], int(pin))


def rp_rail(nl, net):
    """(nominal, min, max, ldo) of a rail made by a recognised AP2112K-3.3 (C51118.pdf p.8: +-1.5 %), else None."""
    for ldo in nl.refs("ldo"):
        if net is not None and not nl.dnp(ldo) and nl.net(ldo, "5") == net and "3.3" in nl.value(ldo):
            return (V_VDD, V_VDD * 0.985, V_VDD * 1.015, ldo)
    return None


def parallel(*rs):
    rs = [r for r in rs if r]
    return 1.0 / sum(1.0 / r for r in rs) if rs else None


def rp_boot_paths(nl):
    """[(resistor, ohms, strap net)] from QSPI_SS through one resistor to a net that is not a power rail."""
    ss = nl.rppin(RP_QSPI["QSPI_SS"])
    if ss is None:
        return []
    return [(ref, parse_number(nl.value(ref), "R"), onet) for ref, pin, onet in nl.two_pin_parts_on(ss, ("res",))
            if onet is not None and onet not in nl.power_nets()]


def button_to_gnd(nl, t, net):
    """True if tact switch t has its used pads on exactly `net` and GND."""
    used = {nl.net(t, p) for p in nl.pins_of(t)} - {None}
    return used == {net, nl.gnd}


def check_rp_gpio_nets(nl, rep):
    """M10 on an RP2040: no GPIO or signal pin on a power rail, no two RP2040 signal pins on one net."""
    status = PASS
    d = []
    pn = nl.power_nets()
    seen = {}
    for pin in sorted(RP_PINS):
        if pin in RP_SUPPLY_PINS or pin == RP_TESTEN:
            continue                                    # supplies share their rails by design (Q03-Q05, Q02)
        net = nl.rppin(pin)
        if net is None:
            continue
        if pin == RP_RUN and net == nl.vdd:
            d.append("RUN tied to IOVDD: allowed when no external reset is needed (1.4.2; Q09)")
            continue
        if net in pn:
            status = FAIL
            d.append("pin %s is on %s" % (rp_label(pin), nl.labels[net]))
        if net in seen:
            status = FAIL
            d.append("pins %s and %s are shorted on net %s" % (rp_label(seen[net]), rp_label(pin), net))
        seen[net] = pin
    used = sorted(p for p in seen.values() if p in RP_GPIO)
    d.append("%d of 30 GPIOs connected: %s" % (len(used), [RP_PINS[p].split("/")[0] for p in used]))
    if status == PASS:
        d.append("XIN/XOUT, SWD, RUN, USB and the six QSPI pins each on a net of their own")
    rep.add("M10", "no GPIO / signal pin tied to a power rail, no two RP2040 pins shorted together", status, "RP_pins", d)


def check_rp_gpio_overvoltage(nl, rep):
    """M11 on an RP2040: nothing pulls a GPIO / QSPI / RUN / SWD pin above IOVDD."""
    status = PASS
    d = []
    hi_nets = {n for n in (nl.vbus, nl.vin, nl.vbat, nl.batp, nl.vaud) if n}
    rv = rp_rail(nl, nl.vdd)
    iovdd = rv[1] if rv else V_VDD                      # the limits follow IOVDD: take the rail's minimum
    lim_op, lim_abs = iovdd + 0.3, iovdd + 0.5
    for pin in sorted(RP_GPIO | set(RP_QSPI.values()) | {RP_RUN, RP_SWCLK, RP_SWDIO}):
        net = nl.rppin(pin)
        if net is None:
            continue
        for ref, p, onet in nl.two_pin_parts_on(net, ("res", "ind", "jumper", "led", "schottky", "mdiode")):
            if onet not in hi_nets:
                continue
            k = nl.kind[ref]
            vmax = nl.net_voltage_max(onet)
            if k == "res":
                rtop = parse_number(nl.value(ref), "R")
                rbot = [v for _, v in nl.resistors_between(net, nl.gnd)]
                if not rbot or rtop is None or any(v is None for v in rbot):
                    status = FAIL
                    d.append("pin %s pulled to %s through %s with no divider to GND -> %.1f V on a 3.3 V I/O"
                             % (rp_label(pin), nl.labels[onet], ref, vmax))
                    continue
                rb = parallel(*rbot)
                v = vmax * rb / (rtop + rb)
                d.append("pin %s: divider %s / %s from %s -> %.2f V max (VIH max %.1f V, abs max %.1f V)"
                         % (rp_label(pin), fmt_r(rtop), fmt_r(rb), nl.labels[onet], v, lim_op, lim_abs))
                if v > lim_abs:
                    status = FAIL
                elif v > lim_op:
                    status = WARN if status == PASS else status
            elif k == "led":
                vf_typ, vf_min, _, _, _ = led_params(nl.parts[ref])
                a, kk, _ = nl.diode_ak(ref)
                if nl.net(ref, a) == onet:
                    v = vmax - vf_min
                    d.append("pin %s: LED %s from %s to the pin -> up to %.2f V when the pin is high-Z"
                             % (rp_label(pin), ref, nl.labels[onet], v))
                    if v > lim_op:
                        status = WARN if status == PASS else status
            else:
                status = FAIL
                d.append("pin %s directly bridged to %s by %s" % (rp_label(pin), nl.labels[onet], ref))
    if not d:
        d.append("no resistor / LED / jumper from a GPIO, QSPI, RUN or SWD net to VBUS, VIN, VBAT or the switched 5 V "
                 "(VAUD)")
    d.append("RP2040 I/O level = IOVDD = 3.3 V: VIH max IOVDD + 0.3 V, abs max IOVDD + 0.5 V (Tables 622 / 625); GPIO0-25, "
             "RUN and SWD are fault tolerant, GPIO26-29 (ADC) are not (Table 614)")
    rep.add("M11", "no pull-up above IOVDD into an RP2040 pin (divider / LED analysis vs VIH max IOVDD + 0.3 V, abs max "
            "IOVDD + 0.5 V)", status, "RP_io", d)


def check_rp_pins(nl, rep):
    title = "RP2040 symbol pad numbers / names agree with the datasheet QFN-56 table (57 = the ground pad)"
    rp = rp_chip(nl, rep, "Q01", title, "RP_pins")
    if not rp:
        return
    status = PASS
    p = nl.parts[rp]
    d = ["%s: footprint %s, LCSC %s" % (nl.desc(rp), p.get("footprint") or "?", p.get("lcsc") or "?")]
    pins = p["pins"]
    missing = [q for q in RP_PINS if str(q) not in pins]
    extra = [q for q in pins if not (q.isdigit() and int(q) in RP_PINS)]
    if missing:
        status = FAIL
        d.append("symbol lacks pads %s" % missing)
    for q in extra:
        if nl.net(rp, q) not in (nl.gnd, None):
            status = FAIL
            d.append("pad %s is not in the datasheet table and sits on %s" % (q, nl.label(nl.net(rp, q))))
        else:
            d.append("extra pad %s (thermal / paste pad) on %s" % (q, nl.label(nl.net(rp, q))))
    named = 0
    for q, want in RP_PINS.items():
        got = nl.pin_name(rp, q)
        if not got or got == "~":
            continue
        named += 1
        ok = {rp_norm(want), rp_norm(want.split("/")[0])} | {rp_norm(a) for a in RP_ALIASES.get(want, ())}
        if rp_norm(got) not in ok:
            status = FAIL
            d.append("pad %d is named '%s' in the netlist but the datasheet has %s" % (q, got, want))
    d.append("%d of 57 pads carry a name%s" % (named, "; all agree with Tables 615-621" if status == PASS else ""))
    fp = (p.get("footprint") or "").upper()
    if "QFN-56" in fp and "EP3.2X3.2" not in fp:
        status = WARN if status == PASS else status
        d.append("footprint ePad is not 3.2 x 3.2 mm: the RP2040's pad is smaller than usual (5.1 p.607, Fig.167 p.608)")
    elif "QFN-56" in fp:
        d.append("footprint ePad 3.2 x 3.2 mm = the recommended footprint (Fig.167 p.608)")
    rep.add("Q01", title, status, "RP_pins", d)


def check_rp_gnd(nl, rep):
    title = "RP2040 ground pad (57, the only ground connection) on GND, TESTEN (19) tied to GND"
    rp = rp_chip(nl, rep, "Q02", title, "RP_pins")
    if not rp:
        return
    status = PASS
    g, t = nl.rppin(RP_GND), nl.rppin(RP_TESTEN)
    d = ["GND pad (57) -> %s ; TESTEN (19) -> %s" % (nl.label(g), nl.label(t))]
    if g is None or g != nl.gnd:
        status = FAIL
        d.append("the central pad is the RP2040's single ground connection (1.4.2, Table 621): it must be on GND")
    else:
        d.append("ground pad on GND; it carries all of the chip's ground current (solder paste and vias under it)")
    if t != nl.gnd:
        status = FAIL
        d.append("TESTEN must be tied to GND (1.4.2 'Tie to GND', Table 619 'connect to Gnd'): %s"
                 % ("left open, only the internal pull-down holds it" if t is None else "it is on %s" % nl.label(t)))
    else:
        d.append("TESTEN on GND as required (factory test mode off)")
    rep.add("Q02", title, status, "RP_pins", d)


def check_rp_supply(nl, rep):
    title = ("RP2040 supplies: IOVDD x6, VREG_VIN, USB_VDD, ADC_AVDD on the 3.3 V rail (single 3.3 V scheme), each "
             "inside its Table 634 range")
    rp = rp_chip(nl, rep, "Q03", title, "RP_power")
    if not rp:
        return
    status = PASS
    d = []
    rail = nl.vdd
    io = {q: nl.rppin(q) for q in RP_IOVDD}
    d.append("IOVDD pins %s -> %s" % (list(RP_IOVDD), sorted({nl.label(n) for n in io.values()}, key=str)))
    if None in io.values() or len(set(io.values())) != 1:
        status = FAIL
        d.append("all six IOVDD pins must be on one supply net (Table 621)")
    if rail is None or rail == nl.gnd or rail in (nl.vbus, nl.vaud, nl.vin, nl.vbat, nl.batp):
        rep.add("Q03", title, FAIL, "RP_power", d + ["IOVDD on %s: 1.62-3.63 V required, abs max 3.63 V (Tables 622, "
                                                     "634)" % nl.label(rail)])
        return
    rv = rp_rail(nl, rail)
    if rv is None:
        status = WARN if status == PASS else status
        d.append("rail %s is not the output of a recognised AP2112K-3.3: voltage not verified" % nl.label(rail))
    else:
        d.append("rail %s from %s: 3.3 V +-1.5 %% = %.3f-%.3f V (C51118.pdf p.8)" % (nl.label(rail), nl.desc(rv[3]),
                                                                                   rv[1], rv[2]))
    for name, pin in (("IOVDD", RP_IOVDD[0]), ("VREG_VIN", RP_VREG_VIN), ("USB_VDD", RP_USB_VDD),
                      ("ADC_AVDD", RP_ADC_AVDD)):
        net = nl.rppin(pin)
        lo, hi = RP_RANGE[name]
        if net is None:
            status = FAIL
            d.append("%s (%d) unconnected%s" % (name, pin, {
                "USB_VDD": ": 'USB_VDD should not be left unconnected' (2.9.4)",
                "VREG_VIN": ": it also powers the power-on reset and brown-out detector (2.9.3)"}.get(name, "")))
            continue
        how = "on the rail"
        if net != rail:
            via = nl.through_series(net, kinds=("res", "ind"), max_ohm=1000, depth=1)
            if rail in via:
                how = "fed from the rail through %s (filter, as the Pico's ADC_AVDD)" % via[rail]
            else:
                status = WARN if status == PASS else status
                d.append("%s (%d) on %s, not the 3.3 V rail: level not verified" % (name, pin, nl.label(net)))
                continue
        if rv:
            ok = rv[1] >= lo and rv[2] <= hi
            d.append("%s (%d) %s: %.2f-%.2f V inside %g-%g V (Table 634)%s" % (
                name, pin, how, rv[1], rv[2], lo, hi, "" if ok else " - OUTSIDE"))
            if not ok:
                status = FAIL
            if name == "ADC_AVDD" and rv[1] < RP_ADC_GOOD:
                status = WARN if status == PASS else status
                d.append("ADC_AVDD below 2.97 V: ADC performance compromised (2.9.5)")
        else:
            d.append("%s (%d) %s" % (name, pin, how))
    if rv:
        d.append("IOVDD max %.3f V < abs max 3.63 V (Table 622); USB_VDD >= 3.135 V for the USB PHY; ADC_AVDD >= 2.97 V "
                 "for full ADC performance (2.9.5); one 3.3 V source for all four = the scheme of 2.9.7.1 / Fig.16, any "
                 "power-up order is allowed (2.9.6)" % rv[2])
    rep.add("Q03", title, status, "RP_power", d)


def check_rp_decoupling(nl, rep):
    title = "RP2040 decoupling: 100 nF per IOVDD / USB_VDD / ADC_AVDD / DVDD pin, 1 uF at VREG_VIN and at VREG_VOUT"
    rp = rp_chip(nl, rep, "Q04", title, "RP_decoup")
    if not rp:
        return
    status = PASS
    d = []

    def small(c):
        return c is not None and 47e-9 <= c <= 470e-9

    groups = defaultdict(list)
    for q in list(RP_IOVDD) + [RP_USB_VDD, RP_ADC_AVDD] + list(RP_DVDD):
        n = nl.rppin(q)
        if n is not None:
            groups[n].append(q)
    for net, pins in groups.items():
        caps = nl.cap_list(net)
        n100 = [(r, c) for r, c in caps if small(c)]
        flashes = [f for f in nl.fitted("flash") if nl.net(f, "8") == net]
        need = len(pins) + len(flashes)
        d.append("%s: %d RP2040 supply pin(s) %s%s; 100 nF-class capacitors %d %s" % (
            nl.label(net), len(pins), pins, " + the flash VCC (%s, design guide C5)" % flashes if flashes else "",
            len(n100), [r for r, _ in n100]))
        if not caps:
            status = FAIL
            d.append("no capacitor at all on %s" % nl.label(net))
        elif len(n100) < need:
            status = WARN if status == PASS else status
            d.append("fewer than one 100 nF per pin (2.9.1-2.9.5); the minimal design shares one between pins 48 and 49 "
                     "as a layout compromise (design guide 2.1.2 p.8)")
    for name, q in (("VREG_VIN", RP_VREG_VIN), ("VREG_VOUT", RP_VREG_VOUT)):
        net = nl.rppin(q)
        if net is None:
            d.append("%s (%d) open (judged in Q03 / Q05)" % (name, q))
            continue
        big = [(r, c) for r, c in nl.cap_list(net) if c and c >= 0.9e-6]
        if not big:
            status = FAIL
            d.append("%s (%d) on %s: no >= 1 uF capacitor - 'the regulator must have 1 uF capacitors placed close to its "
                     "input (VREG_VIN) and output (VREG_VOUT)' (2.10.1)" % (name, q, nl.label(net)))
        else:
            d.append("%s (%d) on %s: >= 1 uF present %s (2.10.1; the Pico uses 2.2 uF)" % (
                name, q, nl.label(net), [(r, fmt_c(c)) for r, c in big]))
    d.append("the netlist cannot show placement: each 100 nF next to its pin, the 1 uF parts next to pins 44 and 45 (small "
             "ceramics meet the regulator's ESR limits, design guide 2.1.3)")
    rep.add("Q04", title, status, "RP_decoup", d)


def check_rp_core(nl, rep):
    title = "RP2040 core supply: VREG_VOUT (45) feeds both DVDD pins (23, 50) on a net of their own (1.1 V, <= 100 mA)"
    rp = rp_chip(nl, rep, "Q05", title, "RP_vreg")
    if not rp:
        return
    status = PASS
    vout = nl.rppin(RP_VREG_VOUT)
    dv = [nl.rppin(q) for q in RP_DVDD]
    d = ["VREG_VOUT (45) -> %s ; DVDD (23) -> %s ; DVDD (50) -> %s" % (nl.label(vout), nl.label(dv[0]),
                                                                       nl.label(dv[1]))]
    rails = {n for n in (nl.vdd, nl.vbus, nl.vaud, nl.vin, nl.vbat, nl.batp) if n}
    if any(n in rails for n in dv) or vout in rails:
        status = FAIL
        d.append("DVDD / VREG_VOUT on a supply rail: the core takes 1.05-1.16 V (Table 634)")
    elif None in dv or dv[0] != dv[1] or dv[0] == nl.gnd:
        status = FAIL
        d.append("both DVDD pins must be on one 1.1 V core net (Table 621, 2.9.2)")
    elif vout == dv[0]:
        others = [(r, q) for r, q in nl.non_cap_members(vout, exclude=(rp,)) if nl.kind[r] != "tp"]
        if others:
            status = WARN
            d.append("the 1.1 V net also feeds %s: the regulator gives 100 mA in all (2.10), meant for the core" % others)
        else:
            d.append("VREG_VOUT -> DVDD 23 + 50, nothing but capacitors on the net: the single 3.3 V scheme (2.9.7.1, "
                     "Fig.16); the regulator starts at 1.1 V (2.10), inside 1.05-1.16 V (Table 634), and its only load "
                     "is the core (100 mA max)")
    elif vout is None:
        status = WARN
        d.append("external core supply (VREG_VOUT open, 2.9.7.2): DVDD on %s - its 1.05-1.16 V not verified here"
                 % nl.label(dv[0]))
    else:
        status = FAIL
        d.append("VREG_VOUT on %s but DVDD on %s: the core is not fed by the regulator" % (nl.label(vout),
                                                                                          nl.label(dv[0])))
    rep.add("Q05", title, status, "RP_vreg", d)


def check_rp_crystal(nl, rep):
    title = ("RP2040 12 MHz crystal on XIN / XOUT: load capacitors from CL and stray, damping resistor on XOUT, ESR and "
             "drive level (Hardware design with RP2040 2.3)")
    rp = rp_chip(nl, rep, "Q06", title, "RP_xosc")
    if not rp:
        return
    status = PASS
    xin, xout = nl.rppin(RP_XIN), nl.rppin(RP_XOUT)
    d = ["XIN (20) -> %s ; XOUT (21) -> %s" % (nl.label(xin), nl.label(xout))]
    if xin is None:
        rep.add("Q06", title, FAIL, "RP_xosc", d + ["nothing on XIN: the USB boot ROM needs a 12 MHz crystal or clock "
                                                   "(1.4.2)"])
        return
    xts = [r for r in nl.fitted("xtal") if xin in {nl.net(r, q) for q in nl.pins_of(r)}]
    if not xts:
        st = WARN if xout is None else FAIL
        rep.add("Q06", title, st, "RP_xosc", d + [
            "no crystal on XIN: %s" % ("XIN as a single-ended 12 MHz CMOS clock input with XOUT open is allowed (1.4.2, "
                                       "Table 628 levels) - the clock source is not verified here" if xout is None
                                       else "XOUT is connected but there is no crystal between XIN and XOUT")])
        return
    y = xts[0]
    ynets = {q: nl.net(y, q) for q in nl.pins_of(y)}
    sig = sorted(q for q, n in ynets.items() if n not in (nl.gnd, None))
    xo2 = [ynets[q] for q in sig if ynets[q] != xin]
    if len(sig) != 2 or len(xo2) != 1:
        rep.add("Q06", title, FAIL, "RP_xosc", d + ["%s pins %s: expected one pin on XIN and one on the XOUT side"
                                                   % (y, {q: nl.label(n) for q, n in ynets.items()})])
        return
    xo2 = xo2[0]
    rser = None
    if xo2 != xout:
        rs = nl.resistors_between(xout, xo2) if xout else []
        if len(rs) != 1:
            rep.add("Q06", title, FAIL, "RP_xosc", d + ["%s's second pin is on %s, neither XOUT nor one resistor away "
                                                       "from it" % (y, nl.label(xo2))])
            return
        rser = rs[0]
    lcsc = (nl.parts[y].get("lcsc") or "").upper()
    known = lcsc == "C20625731" or "ABM8-272" in nl.value(y).upper()
    f = re.search(r"(\d+(?:[.,]\d+)?)\s*MHZ", nl.value(y).upper())
    fmhz = float(f.group(1).replace(",", ".")) if f else (12.0 if known else None)
    d.append("%s between XIN and %s%s" % (nl.desc(y), nl.label(xo2), " (behind %s %s from XOUT)" % (
        rser[0], fmt_r(rser[1])) if rser else ""))
    if fmhz is None or abs(fmhz - 12.0) > 1e-3:
        status = FAIL
        d.append("crystal value '%s': the USB boot ROM needs 12 MHz (1.4.2; 1-15 MHz otherwise, 2.16.1)" % nl.value(y))
    if known:
        x = XTAL_ABM8
        d.append("Abracon ABM8-272-T3 (LCSC %s): the crystal recommended in 2.16.1.1 and used on the Pico - CL 10 pF, "
                 "ESR <= 50 Ohm, C0 <= 3 pF, drive <= 200 uW" % (lcsc or "?"))
        if sig != ["1", "3"]:
            status = FAIL
            d.append("crystal on pads %s: the ABM8-272-T3 has it between pads 1 and 3, pads 2 and 4 are GND (page 4 of 9)"
                     % sig)
    else:
        x = None
        status = WARN if status == PASS else status
        d.append("crystal '%s' (LCSC %s) is not the ABM8-272-T3: 2.16.1.1 asks to test any other crystal over "
                 "temperature; CL assumed 10 pF" % (nl.value(y), lcsc or "?"))
    cl = XTAL_ABM8["CL"]
    for q, n in ynets.items():
        if q not in sig and n not in (nl.gnd, None):
            status = FAIL
            d.append("%s pad %s (case) on %s - case pads go to GND or stay open" % (y, q, nl.label(n)))
    # nothing else on the oscillator nets
    allowed = {rp, y} | ({rser[0]} if rser else set())
    for net, nm in ((xin, "XIN"), (xo2, "XOUT side"), (xout, "XOUT")):
        if net is None:
            continue
        extra = [(r, q) for r, q in nl.mems(net) if r not in allowed and nl.kind[r] != "cap"]
        if extra:
            status = FAIL
            d.append("%s net also connects %s - oscillator nets carry only the crystal, its capacitors and the damping "
                     "resistor" % (nm, extra))
    if rser and nl.cap_list(xout):
        status = WARN if status == PASS else status
        d.append("capacitor on XOUT itself (before the damping resistor): not in the reference circuit")
    c_in, c_out = nl.cap_list(xin), nl.cap_list(xo2)
    if len(c_in) != 1 or len(c_out) != 1 or c_in[0][1] is None or c_out[0][1] is None:
        status = FAIL
        d.append("expected one load capacitor from each crystal pin to GND, found XIN %s / XOUT side %s" % (c_in, c_out))
    else:
        c1, c2 = c_in[0][1], c_out[0][1]
        cser = c1 * c2 / (c1 + c2)
        cl_eff = cser + RP_STRAY
        d.append("load: %s %s and %s %s in series = %s + %s stray (PCB + XIN/XOUT, design guide 2.3) = %s for CL %s; "
                 "C = 2 x (CL - stray) = %s" % (c_in[0][0], fmt_c(c1), c_out[0][0], fmt_c(c2), fmt_c(cser),
                                                fmt_c(RP_STRAY), fmt_c(round(cl_eff * 1e13) / 1e13), fmt_c(cl),
                                                fmt_c(2 * (cl - RP_STRAY))))
        if abs(c1 - c2) > 0.05 * max(c1, c2):
            status = WARN if status == PASS else status
            d.append("the two load capacitors differ: the design guide uses two of equal value")
        dev = cl_eff - cl
        if abs(dev) <= 1e-12 + 1e-15:
            d.append("%+.1f pF from CL: the design guide's own 10.5 pF for 10 pF is 'close enough' (2.3 p.9)" % (dev * 1e12))
        elif abs(dev) <= 2e-12:
            status = WARN if status == PASS else status
            d.append("%+.1f pF from CL: pulls the frequency and changes the oscillator margin - not the tuned circuit "
                     "(2.16.1.1: test over temperature)" % (dev * 1e12))
        else:
            status = FAIL
            d.append("%+.1f pF from CL: the crystal is not loaded as specified" % (dev * 1e12))
    if rser is None:
        status = WARN if status == PASS else status
        d.append("no damping resistor between XOUT and the crystal: the design guide's 1 kOhm (R5) with the 50 Ohm ESR "
                 "crystal keeps it from being over-driven at 3.3 V (2.3 p.10; Pico R14)")
    elif rser[1] is None or abs(rser[1] - 1e3) > 0.05e3:
        status = WARN if status == PASS else status
        d.append("damping resistor %s %s: the ABM8-272-T3 circuit is tuned for 1 kOhm at 3.3 V (2.16.1.1; design guide "
                 "2.3: any deviation needs extensive testing)" % (rser[0], fmt_r(rser[1])))
    else:
        d.append("damping resistor %s 1 kOhm on XOUT, as R5 in the minimal design and R14 on the Pico" % rser[0])
    if x:
        vpp = V_VDD * 1.015
        dl = x["ESR"] * (math.pi * x["f"] * (x["C0"] + x["CL"]) * vpp) ** 2 / 2
        d.append("drive level, upper bound with the full IOVDD swing across the crystal: ESR x (pi f (C0 + CL) Vpp)^2 / 2 "
                 "= %.0f uW <= %.0f uW max (the 1 kOhm keeps the real swing lower)" % (dl * 1e6, x["drive_max"] * 1e6))
        if dl > x["drive_max"]:
            status = WARN if status == PASS else status
        d.append("frequency error <= +-%d ppm (tolerance + stability + 1st-year aging, page 2 of 9): inside the 1000 ppm "
                 "the RP2040 clocks are designed for (2.15 p.181)" % x["ppm"])
    d.append("layout: crystal and capacitors close to pins 20/21, short tracks (stray capacitance is part of the load)")
    rep.add("Q06", title, status, "RP_xosc", d)


def check_rp_flash(nl, rep):
    title = ("QSPI flash: each RP2040 QSPI pin on its W25Q128JV pin (/CS, CLK, IO0-IO3), VCC on the 3.3 V rail with "
             "decoupling, nothing else on the bus")
    rp = rp_chip(nl, rep, "Q07", title, "RP_flash")
    if not rp:
        return
    q = {nm: nl.rppin(p) for nm, p in RP_QSPI.items()}
    fls = nl.fitted("flash")
    if not fls:
        rep.add("Q07", title, FAIL, "RP_flash", ["no QSPI flash: the RP2040 has no program memory of its own and boots "
                                                 "from external flash (2.8.1; design guide 2.2)"])
        return
    status = PASS
    f = fls[0]
    d = ["%s, LCSC %s" % (nl.desc(f), nl.parts[f].get("lcsc") or "?")]
    vu = nl.value(f).upper()
    if not ((nl.parts[f].get("lcsc") or "").upper() == "C97521" or "W25Q" in vu):
        status = WARN
        d.append("not a W25Q: pinout taken from the W25Q128JV (the usual 8-pin QSPI pinout) - check its own datasheet")
    for p, want in W25_PINS.items():
        got = nl.pin_name(f, p)
        if got and got != "~":
            ok = {rp_norm(want)} | {rp_norm(a) for a in W25_ALIASES.get(want, ())}
            if rp_norm(got) not in ok:
                status = FAIL
                d.append("flash pin %s named '%s', the W25Q128JV has %s (p.5)" % (p, got, want))
    for p, want in W25_PINS.items():
        net = nl.net(f, p)
        if want == "GND":
            if net != nl.gnd:
                status = FAIL
                d.append("pin 4 GND on %s" % nl.label(net))
        elif want == "VCC":
            rv = rp_rail(nl, net)
            if net is None or net != nl.vdd:
                status = FAIL
                d.append("pin 8 VCC on %s: it must share the RP2040's 3.3 V rail (QSPI levels = IOVDD)" % nl.label(net))
            elif rv is None:
                status = WARN if status == PASS else status
                d.append("VCC rail voltage not verified")
            else:
                d.append("VCC on %s: %.2f-%.2f V inside 3.0-3.6 V (133 MHz) / 2.7-3.6 V (9.2 p.60), abs max 4.6 V"
                         % (nl.label(net), rv[1], rv[2]))
            caps = [(r, c) for r, c in nl.cap_list(net) if c and c <= 470e-9]
            if not caps:
                status = WARN if status == PASS else status
                d.append("no 100 nF-class capacitor on the flash VCC rail (design guide C5)")
        else:
            qn = W25_QSPI[p]
            if net is None or net != q[qn]:
                status = FAIL
                d.append("flash pin %s %s on %s, expected the RP2040 %s (pad %d) net %s" % (
                    p, want, nl.label(net), qn, RP_QSPI[qn], nl.label(q[qn])))
            else:
                d.append("%s (%d) -> flash %s %s" % (qn, RP_QSPI[qn], p, want))
    for qn, net in q.items():
        if net is None:
            continue
        extra = [(r, p) for r, p in nl.mems(net) if r not in (rp, f) and nl.kind[r] != "tp"]
        if qn == "QSPI_SS":
            extra = [(r, p) for r, p in extra if nl.kind[r] != "res"]       # pull-up and BOOT resistor: Q08
        if extra:
            status = FAIL
            d.append("%s also carries %s: the QSPI pins are wired straight to the flash (design guide 2.2)" % (qn, extra))
    m = re.search(r"W25Q(\d+)", vu)
    if m:
        mb = int(m.group(1)) / 8.0
        if mb > 16:
            status = WARN if status == PASS else status
            d.append("%g MB part: the RP2040 supports up to 16 MB (design guide 2.2)" % mb)
        else:
            d.append("%g MB (%s Mbit) <= the 16 MB the RP2040 supports (design guide 2.2); the W25Q answers 03h / 02h / "
                     "05h / 06h / 20h and the boot ROM's XIP exit sequence (design guide 2.6)" % (mb, m.group(1)))
    d.append("layout: short direct QSPI tracks next to the RP2040 (design guide 2.2), 100 nF next to pin 8")
    rep.add("Q07", title, status, "RP_flash", d)


def check_rp_bootsel(nl, rep):
    title = ("RP2040 BOOTSEL strap: QSPI_SS pulled up to the flash VCC (or by the chip alone); BOOT to GND through a "
             "resistor that reads low at boot yet lets QSPI_SS over-drive it")
    rp = rp_chip(nl, rep, "Q08", title, "RP_boot")
    if not rp:
        return
    ss = nl.rppin(RP_QSPI["QSPI_SS"])
    if ss is None:
        rep.add("Q08", title, FAIL, "RP_boot", ["QSPI_SS (56) unconnected: no flash chip select"])
        return
    status = PASS
    d = ["QSPI_SS (56) -> %s" % nl.label(ss)]
    rv = rp_rail(nl, nl.vdd)
    vmax = rv[2] if rv else V_VDD * 1.015
    fls = nl.fitted("flash")
    fvcc = nl.net(fls[0], "8") if fls else None
    ups = [(r, parse_number(nl.value(r), "R"), o) for r, p, o in nl.two_pin_parts_on(ss, ("res",))
           if o in nl.power_nets() and o != nl.gnd]
    downs = [(r, parse_number(nl.value(r), "R")) for r, p, o in nl.two_pin_parts_on(ss, ("res",)) if o == nl.gnd]
    direct = [r for r, p in nl.mems(ss) if nl.kind[r] in ("tact", "jumper")]
    if direct:
        status = FAIL
        d.append("%s straight on QSPI_SS: pressed while the chip drives QSPI_SS high, the pin is shorted to GND - the "
                 "design guide puts 1 kOhm in series (2.2)" % direct)
    for r, v, o in ups:
        if fvcc and o != fvcc:
            status = FAIL
            d.append("pull-up %s to %s, but the flash VCC is %s: /CS must track the flash's VCC (W25Q 4.1)"
                     % (r, nl.label(o), nl.label(fvcc)))
        else:
            d.append("pull-up %s %s to %s (the flash VCC): /CS follows VCC from the first moment of power-up (W25Q 4.1, "
                     "6.5); the minimal design has this 10k as an option (design guide 2.2)" % (r, fmt_r(v), nl.label(o)))
    if not ups:
        d.append("no external pull-up: only the RP2040's own (Table 616), not guaranteed in the first moments of power-up; "
                 "the minimal design and the Pico leave it unfitted with the W25Q (design guide 2.2)")
    if downs:
        status = FAIL
        d.append("resistor %s from QSPI_SS to GND: the boot ROM would see 'CS tied low' at every reset (2.8.1)" % downs)
    rpu = parallel(*([v for _, v, _ in ups] + [RP_RPU[0]]))
    found = False
    for ref, rb, net in rp_boot_paths(nl):
        mem = [(r, p) for r, p in nl.mems(net) if r != ref]
        btns = [r for r, p in mem if nl.kind[r] == "tact"]
        jmps = [r for r, p in mem if nl.kind[r] == "jumper"]
        tps = [r for r, p in mem if nl.kind[r] in ("tp", "conn")]
        other = [(r, p) for r, p in mem if r not in btns + jmps + tps]
        if other or not (btns or jmps or tps):
            status = WARN if status == PASS else status
            d.append("%s %s from QSPI_SS to %s, which carries %s: not a BOOT strap" % (ref, fmt_r(rb), nl.label(net), mem))
            continue
        found = True
        for b in btns:
            if not button_to_gnd(nl, b, net):
                status = FAIL
                d.append("%s on %s does not close to GND" % (b, nl.label(net)))
        if rb is None:
            status = FAIL
            d.append("%s: value '%s' not readable" % (ref, nl.value(ref)))
            continue
        v_low = vmax * rb / (rb + rpu)
        d.append("BOOT %s: QSPI_SS -> %s %s -> %s -> GND; pressed: %.2f V x %s / (%s + %s) = %.2f V (pull-ups %s || "
                 "internal >= %s) <= VIL 0.8 V (Table 625): the boot ROM sees CS tied low and enters USB boot (2.8.1)" % (
                     btns + jmps + tps, ref, fmt_r(rb), nl.label(net), vmax, fmt_r(rb), fmt_r(rb), fmt_r(round(rpu)),
                     v_low, [fmt_r(v) for _, v, _ in ups] or "none", fmt_r(RP_RPU[0])))
        if v_low > RP_VIL:
            status = FAIL
            d.append("  %.2f V is above VIL 0.8 V: BOOTSEL would not be detected - lower %s or raise the pull-up"
                     % (v_low, ref))
        rb_min = RP_VOH_MIN / RP_DRIVE_DEFAULT
        i = RP_VOH_MIN / rb
        d.append("  held while QSPI_SS is driven high: %s takes %.1f mA at VOH 2.62 V, within the default 4 mA drive "
                 "(Tables 614 / 625), so /CS stays >= 2.62 V > the flash's VIH 0.7 VCC = %.2f V (W25Q 9.4): the "
                 "'over-drive' the design guide asks R1 for (2.2)" % (ref, i * 1e3, 0.7 * vmax))
        if rb < rb_min:
            status = FAIL
            d.append("  %s < %s: more than 4 mA, QSPI_SS cannot hold a valid high with the button pressed" % (
                fmt_r(rb), fmt_r(round(rb_min))))
        d.append("  while held the flash /CS sits at %.2f V (selected) but sees no clock: harmless, as on the Pico (R11 1K)"
                 % v_low)
    if not found:
        status = WARN if status == PASS else status
        d.append("no BOOT strap (button, jumper or test point through a resistor): the boot ROM falls back to USB only "
                 "when no valid image is found (2.8.1); a valid but broken image could then be left only via SWD")
    rep.add("Q08", title, status, "RP_boot", d)


def check_rp_run(nl, rep):
    title = ("RP2040 RUN (26): high to run (internal / external pull-up or IOVDD), only a reset button, capacitor or "
             "test point to GND")
    rp = rp_chip(nl, rep, "Q09", title, "RP_run")
    if not rp:
        return
    run = nl.rppin(RP_RUN)
    status = PASS
    d = ["RUN (26) -> %s" % nl.label(run)]
    if run is None:
        d.append("open: the internal pull-up (Table 619; ~50 kOhm on the Pico, 2.1) keeps the chip running - no hardware "
                 "reset")
    elif run == nl.gnd:
        status = FAIL
        d.append("RUN on GND: the chip is held in reset (2.7)")
    elif run == nl.vdd:
        d.append("tied to IOVDD: allowed when no external reset is needed (1.4.2)")
    elif run in nl.power_nets():
        status = FAIL
        d.append("RUN tied to %s: above IOVDD + 0.5 V (Table 622)" % nl.labels[run])
    else:
        up = False
        for r, p in nl.mems(run, exclude=rp):
            k = nl.kind[r]
            if k in ("tp", "conn"):
                d.append("%s: test point / header (an external reset or probe can pull RUN low)" % r)
            elif k == "tact":
                if button_to_gnd(nl, r, run):
                    d.append("%s: push button RUN -> GND = reset (pad pairing in R01)" % r)
                else:
                    status = FAIL
                    d.append("%s on RUN does not close to GND" % r)
            elif k == "res":
                _, o = nl.other_end(r, p)
                v = parse_number(nl.value(r), "R")
                if o == nl.vdd:
                    up = True
                    d.append("%s %s pull-up to IOVDD (on top of the internal one): %.2f mA while the button is held"
                             % (r, fmt_r(v), V_VDD / v * 1e3 if v else 0))
                else:
                    status = FAIL
                    d.append("%s from RUN to %s: RUN must idle high" % (r, nl.label(o)))
            elif k == "cap" and nl.other_end(r, p)[1] == nl.gnd:
                d.append("%s: capacitor to GND delays the release of reset (allowed)" % r)
            else:
                status = WARN if status == PASS else status
                d.append("%s (%s) on RUN: anything driving RUN must only pull it low (open drain)" % (r, k))
        if not up:
            d.append("no external pull-up: the internal one holds RUN high (Table 619)")
    d.append("RUN is a fault-tolerant input (Table 619): a reset line from a probe is safe even with the board off")
    rep.add("Q09", title, status, "RP_run", d)


def check_rp_swd(nl, rep):
    title = "RP2040 SWCLK (24) / SWDIO (25): test points or a header only (internal pull-ups), GND and 3.3 V for the probe"
    rp = rp_chip(nl, rep, "Q10", title, "RP_swd")
    if not rp:
        return
    status = PASS
    d = []
    reached = False
    for pin, nm in ((RP_SWCLK, "SWCLK"), (RP_SWDIO, "SWDIO")):
        net = nl.rppin(pin)
        if net is None:
            d.append("%s (%d) open: allowed (internal pull-up) - no debug access; code still loads over USB (2.8.1)"
                     % (nm, pin))
            continue
        others = nl.mems(net, exclude=rp)
        kinds = sorted({nl.kind[r] for r, _ in others})
        d.append("%s (%d) -> %s : %s" % (nm, pin, nl.label(net), others or "nothing else"))
        if net in nl.power_nets():
            status = FAIL
            d.append("%s shorted to %s" % (nm, nl.labels[net]))
        if any(k not in ("tp", "conn", "res") for k in kinds):
            status = FAIL
            d.append("%s is loaded by %s - only test points / a debug header (and a series R) belong there" % (nm, kinds))
        if others:
            reached = True
    d.append("internal pull-ups on both (Table 618; nominally 60 kOhm, Pico 4.8): no external resistors needed")
    if reached:
        tp_nets = {nl.net(r, p) for r in nl.refs("tp") for p in nl.pins_of(r)}
        for net, nm in ((nl.gnd, "GND"), (nl.vdd, "3.3 V")):
            if net not in tp_nets and not any(nl.kind[r] == "conn" for r, _ in nl.mems(net)):
                status = WARN if status == PASS else status
                d.append("no test point or header on %s for the probe" % nm)
    rep.add("Q10", title, status, "RP_swd", d)


def check_rp_usb(nl, rep):
    title = ("RP2040 USB_DP (47) / USB_DM (46): one 27 Ohm series resistor each to one USB port (hub DPn/DMn or the "
             "receptacle), not swapped, no external pull-up / pull-down")
    rp = rp_chip(nl, rep, "Q11", title, "RP_usb")
    if not rp:
        return
    dp, dn = nl.rppin(RP_USB_DP), nl.rppin(RP_USB_DM)
    d = ["USB_DP (47) -> %s ; USB_DM (46) -> %s" % (nl.label(dp), nl.label(dn))]
    if dp is None or dn is None or dp == dn:
        rep.add("Q11", title, FAIL, "RP_usb", d + ["USB_DP and USB_DM must be two connected, distinct nets"])
        return
    status = PASS
    far = {}
    for net, nm, role in ((dp, "USB_DP", "D+"), (dn, "USB_DM", "D-")):
        rs = nl.two_pin_parts_on(net, ("res",))
        rest = [(r, p) for r, p in nl.mems(net, exclude=rp) if r not in [x[0] for x in rs] and nl.kind[r] != "tp"]
        if rest:
            status = FAIL
            d.append("%s also carries %s: the bus pull-ups / pull-downs are inside (1.4.2), nothing else belongs here"
                     % (nm, rest))
        if len(rs) != 1:
            status = FAIL
            d.append("%s needs exactly one 27 Ohm series resistor ('required', 1.4.2 / Table 620), found %s"
                     % (nm, [r for r, _, _ in rs]))
            continue
        r, _, o = rs[0]
        v = parse_number(nl.value(r), "R")
        if v is None or not (24.3 <= v <= 29.7):
            status = FAIL
            d.append("%s: series resistor %s = %s, not 27 Ohm" % (nm, r, fmt_r(v)))
        else:
            d.append("%s -> %s %s Ohm -> %s" % (nm, r, fmt_r(v), nl.label(o)))
        far[role] = o
    if len(far) == 2:
        hubs = nl.fitted("hub")
        rdp, rdn = receptacle_data_nets(nl)
        if hubs:
            h = hubs[0]
            hp = [CH334P_PINS.get(p, "?") for r, p in nl.mems(far["D+"]) if r == h]
            hn = [CH334P_PINS.get(p, "?") for r, p in nl.mems(far["D-"]) if r == h]
            mp = re.fullmatch(r"D([PM])([1-4U])", hp[0]) if len(hp) == 1 else None
            mn = re.fullmatch(r"D([PM])([1-4U])", hn[0]) if len(hn) == 1 else None
            if not (mp and mn):
                status = FAIL
                d.append("the far side of the resistors meets hub pins %s / %s: expected one downstream DPn / DMn"
                         % (hp, hn))
            elif "U" in (mp.group(2), mn.group(2)) or mp.group(2) != mn.group(2):
                status = FAIL
                d.append("RP2040 on hub pins %s / %s: must be the two lines of one downstream port" % (hp[0], hn[0]))
            elif (mp.group(1), mn.group(1)) != ("P", "M"):
                status = FAIL
                d.append("SWAPPED: USB_DP reaches %s, USB_DM reaches %s" % (hp[0], hn[0]))
            else:
                d.append("hub %s port %s: DP%s = USB_DP, DM%s = USB_DM (full-speed device behind the hub, U03)"
                         % (h, mp.group(2), mp.group(2), mp.group(2)))
        elif rdp and rdn:
            if (far["D+"], far["D-"]) == (rdn, rdp):
                status = FAIL
                d.append("SWAPPED: USB_DP reaches the receptacle D-")
            elif (far["D+"], far["D-"]) != (rdp, rdn):
                status = FAIL
                d.append("the resistors do not reach the receptacle D+ / D- (%s / %s)" % (rdp, rdn))
            else:
                d.append("straight to the receptacle D+ / D- (as the Pico, 4.7)")
        else:
            status = WARN if status == PASS else status
            d.append("no hub and no receptacle: the USB port is not in this netlist")
    d.append("a VBUS-detect GPIO is optional: without one, firmware forces VBUS detect in USB_PWR (4.1.2.10 p.394)")
    d.append("layout: the 27 Ohm parts close to the RP2040, the pair routed as 90 Ohm differential over unbroken ground "
             "(design guide 2.4.1); USB_VDD 3.3 V checked in Q03")
    rep.add("Q11", title, status, "RP_usb", d)


def check_rp_budget(nl, rep):
    title = ("3.3 V rail budget: RP2040 + flash + resistive loads (datasheet maxima) vs the AP2112K-3.3 (600 mA) and its "
             "SOT25 dissipation")
    rp = rp_chip(nl, rep, "Q12", title, "RP_budget")
    if not rp:
        return
    rail = nl.vdd
    rv = rp_rail(nl, rail)
    if rv is None:
        rep.add("Q12", title, WARN, "RP_budget", ["3.3 V rail %s is not made by a recognised AP2112K-3.3: budget not "
                                                  "checked" % nl.label(rail)])
        return
    ldo = rv[3]
    status = PASS
    items = [("RP2040 core regulator, rated maximum (2.10)", RP_VREG_IMAX),
             ("RP2040 IOVDD: every GPIO + QSPI pin sourcing together, IIOVDD_MAX (Table 625)", RP_IIOVDD_MAX),
             ("RP2040 USB_VDD, maximum average (Table 637)", RP_USB_VDD_MAX)]
    for f in nl.fitted("flash"):
        if nl.net(f, "8") == rail:
            items.append(("%s ICC program / erase max (W25Q 9.4)" % f, W25_ICC_MAX))
    unknown = []
    seen = set()
    for r, p in nl.non_cap_members(rail, exclude=(rp, ldo)):
        k = nl.kind[r]
        if k in ("tp", "flash") or r in seen:
            continue
        seen.add(r)
        if k == "hub":
            items.append(("%s CH334 on 3.3 V (V5 = VDD33), the hub's maximum (CH334 datasheet p.28)" % r, CH334_I_MAX))
            continue
        if k == "res":
            o = nl.other_end(r, p)[1]
            v = parse_number(nl.value(r), "R")
            if o in nl.power_nets() and o != nl.gnd:
                continue
            if v:
                items.append(("%s %s to %s, other end grounded" % (r, fmt_r(v), nl.label(o)), V_VDD / v))
            continue
        if k == "esd":
            continue                                    # clamp reference, ~nA
        unknown.append((r, k))
    tot = sum(i for _, i in items)
    d = ["loads on %s (upper bounds, never all at once):" % nl.label(rail)] + \
        ["  %5.1f mA  %s" % (i * 1e3, txt) for txt, i in items]
    if unknown:
        status = WARN
        d.append("other parts on the rail, not budgeted: %s" % unknown)
    vin = nl.net(ldo, "1")
    vin_max = nl.net_voltage_max(vin) or V_VBUS_MAX
    p = (vin_max - V_VDD) * tot
    dt = p * AP2112_THETA_JA
    d.append("total <= %.0f mA vs %s IOUT(MAX) >= 600 mA (p.8): %s" % (tot * 1e3, ldo, "OK" if tot <= AP2112_IOUT else
                                                                         "EXCEEDED"))
    if tot > AP2112_IOUT:
        status = FAIL
    d.append("headroom: VBUS 4.75 V (USB 2.0 low end) - %.2f V = %.2f V >> dropout 400 mV max at 600 mA (p.8)"
             % (rv[2], 4.75 - rv[2]))
    d.append("dissipation at this bound: (%.1f V - 3.3 V) x %.0f mA = %.2f W x 184 C/W = +%.0f C; TJ <= +150 C (p.3) for "
             "ambient up to %.0f C" % (vin_max, tot * 1e3, p, dt, 150 - dt))
    if 150 - dt < 40:
        status = WARN if status == PASS else status
        d.append("the SOT25 could overheat in a warm case: give U3 copper")
    rep.add("Q12", title, status, "RP_budget", d)


# ---------------------------------------------------------------- charger ---
# The charger is a Microchip MCP73831T-2ACI/OT (MCP73831_C424093.pdf).  The TP4054 is still
# recognised (VBAT role, D01 CHRG sink, P04) so the BlueMicro840 reference keeps its power-path checks, but
# the C-series below are MCP73831 checks and SKIP on a TP4054 board.
def mcp_charger(nl, rep, code, title, src):
    """The MCP73831/2 ref, or None after adding a SKIP line for `code`."""
    if nl.charger and nl.chg_model in ("MCP73831", "MCP73832"):
        return nl.charger
    if nl.charger:
        why = "charger is a %s: the MCP73831 checks do not apply (the TP4054 is still used for the VBAT " \
              "role, D01 and P04)" % nl.chg_model
    else:
        why = "no MCP73831 charger in this netlist"
    rep.add(code, title, SKIP, src, [why])
    return None


def chg_pin(nl, ch, role):
    return nl.pin_by_role(ch, CHARGER_ROLE, role)


def chg_net(nl, ch, role):
    p = chg_pin(nl, ch, role)
    return nl.net(ch, p) if p else None


def mcp_ireg_mA(r_ohm):
    """IREG [mA] = 1000 V / RPROG [kOhm] (MCP73831_C424093.pdf p.15)."""
    return 1000.0 / (r_ohm / 1e3)


def check_charger_pins(nl, rep):
    title = "MCP73831: pinout, VDD on VBUS (3.75-6 V, abs max 7 V), VSS on GND, VBAT on the battery net, 4.20 V option"
    ch = mcp_charger(nl, rep, "C01", title, "MCP_pins")
    if not ch:
        return
    status = PASS
    d = []
    n = {role: chg_net(nl, ch, role) for role in ("STAT", "GND", "BAT", "VDD", "PROG")}
    d.append("%s: STAT(1) %s | VSS(2) %s | VBAT(3) %s | VDD(4) %s | PROG(5) %s"
             % (nl.desc(ch), nl.label(n["STAT"]), nl.label(n["GND"]), nl.label(n["BAT"]), nl.label(n["VDD"]),
                nl.label(n["PROG"])))
    for p, role in CHARGER_ROLE.items():
        nm = nl.pin_name(ch, p).upper()
        if p not in nl.parts[ch]["pins"]:
            status = FAIL
            d.append("pin %s (%s) missing from the symbol" % (p, role))
        elif nm and nm not in CHARGER_ALIASES[role]:
            status = FAIL
            d.append("pin %s is named '%s' but SOT-23-5 pin %s is %s (Table 3-1, p.11)" % (p, nm, p, role))
    if n["VDD"] is None or n["VDD"] != nl.vbus:
        status = FAIL
        d.append("VDD must be the USB VBUS net (the charger input); found %s" % nl.label(n["VDD"]))
    else:
        d.append("VDD on VBUS: USB 4.75-%.1f V inside 3.75-6 V (p.3) and above VREG + 0.3 V = 4.5 V "
                 "(recommended, p.11 3.1); abs max 7.0 V" % V_VBUS_MAX)
    if n["GND"] is None or n["GND"] != nl.gnd:
        status = FAIL
        d.append("VSS must be on ground")
    if n["BAT"] is None or n["BAT"] in (nl.gnd, nl.vbus, nl.vin, nl.vdd, nl.vaud):
        status = FAIL
        d.append("VBAT must be the battery net, found %s" % nl.label(n["BAT"]))
    elif nl.batconn:
        d.append("VBAT -> %s -> battery connector %s" % (
            "power switch / bypass jumper" if nl.batp != n["BAT"] else "directly", nl.desc(nl.batconn)))
    else:
        status = WARN if status == PASS else status
        d.append("no 2-pin battery connector reaches VBAT (board without battery?)")
    if n["PROG"] is None:
        status = FAIL
        d.append("PROG unconnected: the charger is disabled (p.13 4.3) - see C03")
    if n["STAT"] is None:
        d.append("STAT unconnected (allowed: status output only)")
    vreg = mcp_vreg(nl.parts[ch])
    if vreg is None:
        status = WARN if status == PASS else status
        d.append("regulation-voltage option (-2/-3/-4/-5) not identifiable from LCSC code, value or note")
    elif abs(vreg - 4.20) > 0.005:
        status = FAIL
        d.append("MCP7383X option VREG = %.2f V: a standard 4.2 V Li-ion/Li-Po cell would be overcharged "
                 "(the rest of the design, P06, assumes 4.2 V)" % vreg)
    else:
        d.append("%s: VREG 4.20 V +-0.75 %% (4.168-4.232 V, p.3); option AC: precondition 10 %%, VPTH 66.5 %%, "
                 "termination 7.5 %%, recharge at 96.5 %% (p.26)"
                 % MCP_LCSC_PART.get((nl.parts[ch].get("lcsc") or "").upper(), "MCP73831-2"))
    rep.add("C01", title, status, "MCP_pins", d)


def check_charger_bypass(nl, rep):
    title = "MCP73831 VDD: bypass >= 4.7 uF and a transient clamp on the hot-pluggable USB input"
    ch = mcp_charger(nl, rep, "C02", title, "MCP_vdd")
    if not ch:
        return
    vdd = chg_net(nl, ch, "VDD")
    caps = nl.cap_list(vdd)
    tot = sum(c for _, c in caps if c)
    need = CHARGER_MODELS[nl.chg_model]["vdd_cap"]
    d = ["capacitors %s-GND: %s = %s" % (nl.label(vdd), [(r, fmt_c(c)) for r, c in caps] or "none",
                                        fmt_c(tot) if caps else "0")]
    status = PASS
    if tot < need * 0.999:
        status = FAIL
        d.append("p.11 3.1: 'Bypass to VSS with a minimum of 4.7 uF' - the VDD net has only %s" % fmt_c(tot))
    else:
        d.append(">= 4.7 uF (p.11 3.1); nominal values: 0603 X5R parts lose capacitance under 5 V bias, keep the "
                 "largest one next to pin 4 (layout)")
    clamps = [(r, p) for r, p in nl.mems(vdd) if nl.kind[r] == "esd" and USBLC6_ROLE.get(p) == "VBUS"]
    if not clamps:
        status = FAIL
        d.append("p.18 6.1.1.2: input over-voltage protection 'must be used' when the source is hot-pluggable "
                 "(USB cables included): no transient clamp (TVS / ESD array VBUS pin) on %s" % nl.label(vdd))
    else:
        d.append("transient clamp: %s pin 5 clamps %s to GND (VBR >= 6 V at 1 mA, usblc6.pdf p.2) = the "
                 "'transzorb from V+ to 0 V' of p.18; an ESD-class clamp, smaller than the SMAJ5.0A of Fig.6-1"
                 % (clamps[0][0], nl.label(vdd)))
    rep.add("C02", title, status, "MCP_vdd", d)


def check_charger_prog(nl, rep):
    title = "MCP73831 PROG: RPROG to GND within 2-67 kOhm -> charge current, jumper options, switch rating, heat"
    ch = mcp_charger(nl, rep, "C03", title, "MCP_prog")
    if not ch:
        return
    prog = chg_net(nl, ch, "PROG")
    d = ["PROG(5) -> %s" % nl.label(prog)]
    status = PASS
    if prog is None:
        rep.add("C03", title, FAIL, "MCP_prog", d + ["PROG floating = charger disabled (p.13 4.3, p.15 5.2.2)"])
        return
    fixed, unknown = [], []
    for ref, pin, onet in nl.two_pin_parts_on(prog, ("res",)):
        if onet == nl.gnd:
            v = parse_number(nl.value(ref), "R")
            (fixed if v else unknown).append((ref, v))
        else:
            status = FAIL
            d.append("%s from PROG to %s - RPROG goes from PROG to VSS (p.15 5.1.2)" % (ref, nl.label(onet)))
    caps = nl.caps_between(prog, nl.gnd)
    if caps:
        status = WARN if status == PASS else status
        d.append("capacitor on PROG %s: not part of the datasheet circuit (p.17 Fig.6-1)" % caps)
    for r, p in nl.mems(prog, exclude=ch):
        if nl.kind[r] in ("res", "jumper", "cap"):
            continue
        if r == nl.module:
            d.append("module pin %s reads PROG (allowed: the pin is an analog voltage)" % p)
        else:
            status = FAIL
            d.append("%s (%s) must not be on PROG" % (r, nl.kind[r]))
    if unknown:
        status = WARN if status == PASS else status
        d.append("resistor(s) with non-numeric value on PROG: %s" % [r for r, _ in unknown])
    if not fixed:
        if not unknown:
            status = FAIL
            d.append("no RPROG to GND: PROG floats and the charger is disabled (p.13 4.3)")
        rep.add("C03", title, status, "MCP_prog", d)
        return
    r_fixed = 1 / sum(1 / v for _, v in fixed)
    options = [("fitted", r_fixed, [r for r, _ in fixed])]
    for ref, pin, onet in nl.two_pin_parts_on(prog, ("jumper",)):
        alt = [(r, parse_number(nl.value(r), "R")) for r, p, o in nl.two_pin_parts_on(onet, ("res",)) if o == nl.gnd]
        alt = [(r, v) for r, v in alt if v]
        if alt:
            options.append(("jumper %s closed" % ref, 1 / (1 / r_fixed + sum(1 / v for _, v in alt)),
                            [r for r, _ in fixed] + [r for r, _ in alt]))
    lo, hi = MCP_RPROG
    imax = 0.0
    for label, r, refs in options:
        i = mcp_ireg_mA(r)
        imax = max(imax, i)
        d.append("%s: RPROG = %s (%s) -> IREG = 1000 V / %.2f kOhm = %.0f mA (+-10 %%: p.3 gives 90-110 mA at 10k, "
                 "450-550 mA at 2k)" % (label, fmt_r(r), "||".join(refs), r / 1e3, i))
        if r > 200e3:
            status = FAIL
            d.append("  RPROG above the 70-200 kOhm shutdown impedance: charger disabled (p.4)")
        elif not (lo * 0.999 <= r <= hi * 1.001):
            status = FAIL
            d.append("  outside the 2-67 kOhm charge-current range (p.4): %.0f mA is not a specified setting" % i)
    for sw in nl.refs("slide"):
        if nl.vbat in {nl.net(sw, p) for p in nl.pins_of(sw)}:
            d.append("charge current flows through power switch %s rated 0.3 A (C221660.pdf p.1): max %.0f mA x 1.1 "
                     "= %.0f mA %s" % (sw, imax, imax * 1.1, "OK" if imax * 1.1 <= 300 else "EXCEEDS the rating"))
            if imax * 1.1 > 300:
                status = FAIL
    vpth_min = MCP_OPT_AC["vpth_min"] * 4.2
    for label, r, refs in options:
        i = mcp_ireg_mA(r) * 1.1 / 1000
        p = (V_VBUS_MAX - vpth_min) * i
        d.append("%s: worst-case dissipation (VDD %.1f V, VBAT at VPTH min %.2f V, IREG +10 %%) = %.2f W -> "
                 "+%.0f C on a minimum-copper SOT-23-5 (230 C/W, p.5; 130 C/W with large copper)"
                 % (label, V_VBUS_MAX, vpth_min, p, p * MCP_THETA_JA))
    d.append("above ~80 C die temperature the charger trims its current itself (thermal regulation, p.14 "
             "Fig.4-2; p.18 6.1.1.3) - expected behaviour at the higher setting, not a fault")
    rep.add("C03", title, status, "MCP_prog", d)


def check_charger_stat(nl, rep):
    title = "MCP73831 STAT tri-state output: LED wiring and current in the L / H / Hi-Z states, no 5 V into a GPIO"
    ch = mcp_charger(nl, rep, "C04", title, "MCP_stat")
    if not ch:
        return
    md = CHARGER_MODELS[nl.chg_model]
    stat = chg_net(nl, ch, "STAT")
    vdd = chg_net(nl, ch, "VDD")
    d = ["STAT(1) -> %s ; output type %s (Table 5-1, p.15)" % (nl.label(stat), md["stat"])]
    status = PASS
    if stat is None:
        rep.add("C04", title, WARN, "MCP_stat", d + ["unused (allowed by p.11 3.3, but no charge indication)"])
        return
    if stat in nl.power_nets():
        rep.add("C04", title, FAIL, "MCP_stat", d + ["STAT is a driven output and must not sit on %s"
                                                    % nl.labels[stat]])
        return
    vdd_nom = nl.net_voltage_nom(vdd) or V_VBUS_NOM
    vdd_max = nl.net_voltage_max(vdd) or V_VBUS_MAX
    gp = [p for r, p in nl.mems(stat) if r == nl.module]
    if gp:
        if md["stat"] == "tri-state":
            status = FAIL
            d.append("module pin %s directly on STAT: in charge complete STAT drives HIGH to VDD = %.1f V "
                     "(VOH = VDD - 0.4 V, p.4) into a 3.3 V I/O (VI/O max VDD + 0.3 V, nrf52840 PS p.612); "
                     "use a divider or the open-drain MCP73832" % (gp, vdd_max))
        else:
            d.append("module pin %s reads the open-drain STAT (pull-up to VDD only)" % gp)
    lit = []
    for ref, pin, onet in nl.two_pin_parts_on(stat, ("res",)):
        r = parse_number(nl.value(ref), "R")
        if r is None:
            status = WARN if status == PASS else status
            d.append("%s on STAT has no numeric value" % ref)
            continue
        if onet in nl.power_nets():
            vo = nl.net_voltage_max(onet) or 0.0
            if onet == nl.gnd:
                i = (vdd_max - md.get("voh_drop", 0.4)) / r * 1e3
                d.append("%s %s pull-down: %.1f mA sourced when STAT is H (max %.0f mA)" % (ref, fmt_r(r), i, md["source_mA"]))
                if md["stat"] != "tri-state" or i > md["source_mA"]:
                    status = FAIL
            else:
                i = (vo - md["vol"]) / r * 1e3
                d.append("%s %s pull-up to %s: %.1f mA sunk when STAT is L (max %.0f mA)" % (ref, fmt_r(r), nl.labels[onet], i, md["sink_mA"]))
                if i > md["sink_mA"]:
                    status = FAIL
            continue
        leds = nl.two_pin_parts_on(onet, ("led",), exclude=ref)
        if not leds:
            status = WARN if status == PASS else status
            d.append("%s from STAT to %s: unknown load" % (ref, nl.label(onet)))
            continue
        for l, lp, lo in leds:
            a, k, assumed = nl.diode_ak(l)
            vf, vfmin, ifmax, src, generic = led_params(nl.parts[l])
            if nl.net(l, k) == onet:            # LED -> R -> STAT: lit while STAT sinks (L = charging)
                sup = nl.net(l, a)
                vs = nl.net_voltage_nom(sup)
                if vs is None:
                    status = FAIL
                    d.append("LED %s anode on %s, which is not a supply" % (l, nl.label(sup)))
                    continue
                i = (vs - vf - md["vol"]) / r * 1e3
                d.append("LED %s (%s): %s -> LED -> %s %s -> STAT: charging (STAT L, VOL %.1f V typ) -> %.2f mA "
                         "(STAT sinks <= %.0f mA, LED IF max %.0f mA)"
                         % (l, nl.value(l), nl.labels[sup], ref, fmt_r(r), md["vol"], i, md["sink_mA"], ifmax))
                if i <= 0 or i > md["sink_mA"] or i > ifmax:
                    status = FAIL
                    d.append("  current outside the STAT sink / LED limits")
                if md["stat"] == "tri-state":
                    vmax_s = nl.net_voltage_max(sup) or vs
                    across = vmax_s - (vdd_max - 1.0)      # VOH min = VDD - 1 V
                    if sup == vdd:
                        d.append("  charge complete (STAT H = VDD - 0.4 V typ, >= VDD - 1 V): at most 1 V across "
                                 "LED + resistor < VF min %.1f V -> off" % vfmin)
                    elif across >= vfmin:
                        status = FAIL
                        d.append("  charge complete: STAT H only reaches VDD - 1 V; %s can still drive %.1f V "
                                 "across the LED -> it would not turn off" % (nl.labels[sup], across))
                    else:
                        d.append("  charge complete: STAT H above the LED anode -> reverse biased, off")
                lit.append(l)
            elif nl.net(l, a) == onet:          # STAT -> R -> LED -> GND: lit while STAT sources (H)
                if md["stat"] != "tri-state":
                    status = FAIL
                    d.append("LED %s anode faces an open-drain STAT: it can never light" % l)
                    continue
                cat = nl.net(l, k)
                if cat != nl.gnd:
                    status = FAIL
                    d.append("LED %s cathode on %s, expected GND" % (l, nl.label(cat)))
                    continue
                i = (vdd_nom - md.get("voh_drop", 0.4) - vf) / r * 1e3
                d.append("LED %s: STAT -> %s %s -> LED -> GND: lit on charge complete (STAT H) at %.2f mA "
                         "(source <= %.0f mA, LED IF max %.0f mA)" % (l, ref, fmt_r(r), i, md["source_mA"], ifmax))
                if i <= 0 or i > md["source_mA"] or i > ifmax:
                    status = FAIL
                lit.append(l)
    direct = nl.two_pin_parts_on(stat, ("led",))
    if direct:
        status = FAIL
        d.append("LED %s directly on STAT without a series resistor" % [l for l, _, _ in direct])
    if lit:
        d.append("shutdown (USB absent / VDD < UVLO / PROG open) and no battery: STAT Hi-Z (leakage <= 1 uA) -> "
                 "LED off; the no-battery state needs the battery detection to work, see C06")
    rep.add("C04", title, status, "MCP_stat", d)


def check_charger_outcap(nl, rep):
    title = "MCP73831 VBAT capacitor >= 4.7 uF (loop stability with the battery disconnected)"
    ch = mcp_charger(nl, rep, "C05", title, "MCP_vbat")
    if not ch:
        return
    bat = chg_net(nl, ch, "BAT")
    caps = nl.cap_list(bat)
    tot = sum(c for _, c in caps if c)
    need = CHARGER_MODELS[nl.chg_model]["vbat_cap"]
    d = ["capacitors on %s: %s" % (nl.label(bat), [(r, fmt_c(c)) for r, c in caps] or "none")]
    if tot < need * 0.999:
        status = FAIL
        d.append("p.11 3.2: 'Bypass to VSS with a minimum of 4.7 uF to ensure loop stability when the battery is "
                 "disconnected' - only %s here" % fmt_c(tot))
    else:
        status = PASS
        d.append("%s >= 4.7 uF; any capacitor type / ESR is fine (p.18 6.1.1.4) - no series resistor needed "
                 "(unlike the TP4054)" % fmt_c(tot))
    rep.add("C05", title, status, "MCP_vbat", d)


def check_charger_detect(nl, rep):
    title = "MCP73831 battery detection: > 7 MOhm on VBAT with the cell disconnected (STAT Hi-Z, LED off)"
    ch = mcp_charger(nl, rep, "C06", title, "MCP_det")
    if not ch:
        return
    bat = chg_net(nl, ch, "BAT")
    rails = {n for n in nl.power_nets() if n not in (bat, nl.batp)}
    z, used = nl.resistance_to_rails(bat, rails)
    d = ["cell disconnected (connector empty, or power switch open while on USB): VBAT = %s" % nl.label(bat)]
    others = []
    for r, p in nl.mems(bat):
        k = nl.kind[r]
        if r == ch or k in ("cap", "res", "conn", "slide", "jumper", "tp"):
            continue
        others.append((r, p, k))
    for r, p, k in others:
        if k == "pmos":
            d.append("%s drain on VBAT: off while USB is present; its body diode (VBAT -> VIN) stays reverse "
                     "biased as long as VIN (VBUS - Schottky, ~4.6 V) is above the 4.3 V no-battery level" % r)
        else:
            d.append("%s.%s (%s) also on VBAT: not counted (non-linear / high impedance)" % (r, p, k))
    vreg = mcp_vreg(nl.parts[ch]) or 4.20
    vnobat = vreg + 0.1
    if z is None:
        d.append("no resistive path from VBAT to any rail: impedance >> 7 MOhm -> 'No Battery Present' is "
                 "detected, STAT Hi-Z, LED off (p.13 4.2, Table 5-1)")
        rep.add("C06", title, PASS, "MCP_det", d)
        return
    d.append("resistive load on VBAT: %s through %s" % (fmt_r(z), used))
    if z >= MCP_ZNOBAT:
        d.append(">= 7 MOhm: even the minimum detection current (0.6 uA) lifts VBAT above VREG + 100 mV -> "
                 "no battery detected, STAT Hi-Z (p.13 4.2)")
        rep.add("C06", title, PASS, "MCP_det", d)
        return
    v_min = MCP_IDET_MIN * z
    i_need = vnobat / z
    cvbat = nl.cap_total(bat)
    tau = z * cvbat if cvbat else None
    vrth = MCP_OPT_AC["vrth"] * vreg
    d.append("p.13 4.2: 'the impedance seen by the VBAT pin before the battery is connected must be greater than "
             "7 MOhm'; here %s: the minimum detection current gives 0.6 uA x %s = %.2f V, below VNO_BAT = VREG + "
             "100 mV = %.2f V, so any part whose detection current is below %.2f uA (datasheet: 0.6 min, 6 typ) "
             "takes the empty VBAT for a discharged cell" % (fmt_r(z), fmt_r(z), v_min, vnobat, i_need * 1e6))
    if tau:
        t_lo = tau * math.log(vreg / vrth)
        t_hi = tau * math.log((vreg - v_min) / (vrth - v_min)) if vrth > v_min else t_lo
        d.append("then, instead of 'No Battery Present' (STAT Hi-Z, Table 5-1), it charges the %s on VBAT (STAT L: "
                 "LED on for ~tTERM 0.4-3.2 ms), terminates (STAT H), the %s load pulls VBAT below VRTH = %.1f %% x "
                 "%.2f V = %.2f V in ~%.1f-%.1f s (tau %s x %s = %.0f s) and starts again: the charge LED can flicker "
                 "periodically on a board without battery or with the power switch off on USB"
                 % (fmt_c(cvbat), fmt_r(z), MCP_OPT_AC["vrth"] * 100, vreg, vrth, t_lo, t_hi, fmt_r(z), fmt_c(cvbat), tau))
    d.append("harmless for the parts and for charging a connected cell; but the 'STAT and LED stay off without a "
             "battery' behaviour is not guaranteed. Options: switch the divider (MOSFET from a GPIO), move it to BAT+ "
             "(drains the cell when off) or raise it above 7 MOhm (conflicts with P06's 800 kOhm SAADC source limit)")
    rep.add("C06", title, FAIL, "MCP_det", d)


# -------------------------------------------------------------------- LDO ---
def check_ldo(nl, rep):
    ldos = nl.refs("ldo")
    if not ldos:
        rep.add("L01", "AP2112K pin wiring", SKIP, "AP_pins", [])
        rep.add("L02", "AP2112K input/output capacitors", SKIP, "AP_pins", [])
        rep.add("L03", "AP2112K input voltage / enable level", SKIP, "AP_limits", [])
        return
    s1 = s2 = s3 = PASS
    d1, d2, d3 = [], [], []
    for ldo in ldos:
        vin, gnd, en, nc, vout = (nl.net(ldo, p) for p in ("1", "2", "3", "4", "5"))
        d1.append("%s: VIN(1) %s | GND(2) %s | EN(3) %s | NC(4) %s | VOUT(5) %s"
                  % (nl.desc(ldo), nl.label(vin), nl.label(gnd), nl.label(en), nl.label(nc), nl.label(vout)))
        for p, role in AP2112_ROLE.items():
            nm = nl.pin_name(ldo, p).upper()
            if nm and nm != role:
                s1 = FAIL
                d1.append("%s pin %s named '%s' but SOT25 pin %s is %s" % (ldo, p, nm, p, role))
        if gnd != nl.gnd:
            s1 = FAIL
            d1.append("%s GND not on ground" % ldo)
        if vin is None or vout is None or vin == vout or vin == nl.gnd or vout == nl.gnd:
            s1 = FAIL
            d1.append("%s VIN/VOUT wiring wrong" % ldo)
        if nc is not None and nl.mems(nc, exclude=ldo):
            s1 = WARN if s1 == PASS else s1
            d1.append("%s NC pin connected to %s (datasheet: No Connection)" % (ldo, nl.label(nc)))
        if en is None:
            s1 = FAIL
            d1.append("%s EN floating: internal 3 MOhm pull-down keeps the regulator OFF" % ldo)
        elif en == vin:
            d1.append("%s EN tied to VIN: always on (VIH >= 1.5 V satisfied for VIN >= 2.5 V)" % ldo)
        elif en == nl.gnd:
            s1 = FAIL
            d1.append("%s EN tied to GND: regulator permanently off" % ldo)
        elif nl.mcu and nl.mcu in [r for r, _ in nl.mems(en)]:
            d1.append("%s EN driven by %s pin %s (GPIO high >= 1.5 V enables)" % (ldo, nl.mcu_word, [p for r, p in nl.mems(en) if r == nl.mcu]))
        else:
            s1 = WARN if s1 == PASS else s1
            d1.append("%s EN on %s" % (ldo, nl.label(en)))
        # capacitors
        cin = nl.caps_between(vin, nl.gnd) if vin else []
        cout = nl.caps_between(vout, nl.gnd) if vout else []
        tin = sum(c for _, c in cin if c)
        tout = sum(c for _, c in cout if c)
        d2.append("%s: CIN %s = %s ; COUT %s = %s" % (ldo, [r for r, _ in cin] or "-", fmt_c(tin) if cin else "none",
                                                    [r for r, _ in cout] or "-", fmt_c(tout) if cout else "none"))
        if tin < 1e-6:
            s2 = FAIL
            d2.append("%s: input capacitor >= 1 uF required (p.1/p.2)" % ldo)
        if tout < 1e-6:
            s2 = FAIL
            d2.append("%s: output capacitor >= 1 uF required for stability (p.1 'stable with 1.0 uF', p.2 COUT)%s"
                      % (ldo, " - the BlueMicro840 reference leaves its second LDO output (Vout header pin) without a capacitor"
                         if vout != nl.vdd else ""))
        # input voltage: from USB through the Schottky, or from the battery
        if vin == nl.vbus and vin is not None and nl.vbat is None:
            # USB only (wired variant): no battery, the regulator hangs straight on VBUS
            d3.append("%s: VIN = VBUS, max %.1f V (USB-C tolerance) <= 6.0 V recommended / 6.5 V abs max; min 4.75 V (USB "
                      "2.0) leaves %.2f V of headroom over 3.3 V >> the dropout (250 mV typ at 600 mA, p.8); no battery"
                      % (ldo, V_VBUS_MAX, 4.75 - V_VDD))
        elif vin == nl.vin or vin == nl.vbus:
            hi = V_VBUS_MAX - (0.3 if vin == nl.vin else 0.0)
            d3.append("%s: VIN max ~%.1f V (USB 5.5 V%s) <= 6.0 V recommended / 6.5 V abs max; min from battery ~3.0 V "
                      ">= 2.5 V (at VBAT < 3.55 V the 3.3 V output drops out gracefully)"
                      % (ldo, hi, " minus Schottky" if vin == nl.vin else ""))
            if hi > 6.0:
                s3 = FAIL
        elif vin == nl.vbat:
            d3.append("%s: VIN = VBAT (<= 4.2 V)" % ldo)
        else:
            s3 = WARN if s3 == PASS else s3
            d3.append("%s: VIN net %s not a known rail; voltage not verified" % (ldo, nl.label(vin)))
    rep.add("L01", "AP2112K-3.3: VIN/GND/EN/NC/VOUT wiring, EN level", s1, "AP_pins", d1)
    rep.add("L02", "AP2112K-3.3: input and output capacitors >= 1 uF", s2, "AP_pins", d2)
    rep.add("L03", "AP2112K-3.3: input voltage within 2.5-6.0 V, output feeds the %s" % ("RP2040" if nl.rp else "module"),
            s3, "AP_limits", d3)


# ------------------------------------------------------------- power path ---
def check_schottky(nl, rep):
    ds = [r for r in nl.refs("schottky") if not nl.dnp(r)]
    if not ds:
        rep.add("P01", "Schottky VBUS -> VIN", SKIP, "B58_pins", ["no B5819W / 1N5819 found"])
        return
    if nl.vin is None and nl.vbat is None:
        # no power path (USB-only board): the VBUS -> VIN rule does not apply; each Schottky is judged by its role
        status = SKIP
        d = ["no power path in this netlist (no VIN node behind a diode, no battery): the VBUS -> VIN rule does not apply"]
        amp_en = {amp_net(nl, a, "EN") for a in nl.fitted("hpamp")} - {None}
        rails = set(nl.power_nets())
        for ref in ds:
            a, k, assumed = nl.diode_ak(ref)
            an, kn = nl.net(ref, a), nl.net(ref, k)
            line = "%s: anode(%s) -> %s ; cathode(%s) -> %s" % (nl.desc(ref), a, nl.label(an), k, nl.label(kn))
            if {an, kn} & amp_en:
                d.append(line + " - the amplifier-EN discharge diode, judged in A14")
            elif an in rails and kn in rails:
                status = WARN
                d.append(line + " - between two power rails with no power path: role unknown")
            else:
                d.append(line + " - signal use, not in a power path")
        rep.add("P01", "B5819W Schottky: power-path diode VBUS -> VIN when there is a power path, otherwise judged by its "
                "role", status, "B58_pins", d)
        return
    status = PASS
    d = []
    found = False
    for ref in ds:
        a, k, assumed = nl.diode_ak(ref)
        an, kn = nl.net(ref, a), nl.net(ref, k)
        d.append("%s: anode(%s) -> %s ; cathode(%s) -> %s%s" % (nl.desc(ref), a, nl.label(an), k, nl.label(kn),
                                                             " [pin polarity assumed: SOD-123 pin1 = cathode]" if assumed else ""))
        if an == nl.vbus and kn == nl.vin:
            found = True
            d.append("correct: USB feeds VIN through the diode; the battery (on VIN when on battery) cannot push "
                     "current back into VBUS (VRRM 40 V >> 4.2 V); IO 1 A >> board current")
        elif an == nl.vin and kn == nl.vbus:
            status = FAIL
            d.append("REVERSED: the diode would let the battery feed VBUS and block USB power")
        elif not ({an, kn} & set(nl.power_nets())):
            # a Schottky used as a small-signal diode (e.g. the amplifier-enable discharge diode): not part of
            # the power path; its own function is checked where it is used (A14)
            d.append("signal use: neither pin on a power rail (not in the power path; see A14)")
        else:
            status = WARN if status == PASS else status
            d.append("on a power rail but not in the VBUS->VIN position")
    if not found:
        status = FAIL
        d.append("no Schottky from VBUS (anode) to VIN (cathode)")
    rep.add("P01", "B5819W Schottky: anode on VBUS, cathode on VIN (USB feeds VIN, no back-feed into VBUS)", status, "B58_pins", d)


def check_pmos(nl, rep):
    qs = [r for r in nl.refs("pmos") if not nl.dnp(r)]
    if not qs:
        rep.add("P02", "P-MOSFET battery switch", SKIP, "SI_pins", ["no SI2301 found"])
        return
    status = PASS
    d = []
    found = False
    for ref in qs:
        roles = {}
        for p, role in SOT23_PMOS_ROLE.items():
            nm = nl.pin_name(ref, p).upper()
            if nm and nm != role:
                status = FAIL
                d.append("%s pin %s named '%s' but SOT-23 pin %s is the %s" % (ref, p, nm, p, role))
            roles[role] = nl.net(ref, p)
        g, s, dr = roles["G"], roles["S"], roles["D"]
        vu = nl.value(ref).upper()
        if "SI2301" not in vu and (nl.parts[ref].get("lcsc") or "").upper() != "C10487":
            d.append("%s: pinout G/S/D = 1/2/3 assumed from the Si2301 datasheet (same SOT-23 convention)" % ref)
        d.append("%s: G(1) -> %s ; S(2) -> %s ; D(3) -> %s" % (nl.desc(ref), nl.label(g), nl.label(s), nl.label(dr)))
        if g == nl.vbus and s == nl.vin and dr == nl.vbat:
            found = True
            d.append("correct: USB present -> VGS = VBUS - VIN ~ +0.4 V -> channel off, body diode (D->S) reverse "
                     "biased since VIN (~4.6 V) > VBAT (<= 4.2 V): USB cannot reach the battery except through the charger")
            d.append("USB absent -> gate pulled to 0 V, VGS = -VBAT (-3.0..-4.2 V, |VGS| <= 8 V) -> channel on, "
                     "RDS(on) 0.11-0.14 Ohm; body diode D->S also conducts battery -> VIN at start-up")
            pulls = nl.resistors_between(g, nl.gnd)
            if not pulls:
                status = FAIL
                d.append("gate net has no pull-down resistor to GND: with USB unplugged the gate would float "
                         "(the BlueMicro840 uses 100k)")
            else:
                d.append("gate pull-down: %s" % [(r, fmt_r(v)) for r, v in pulls])
        elif g == nl.vbus and s == nl.vbat and dr == nl.vin:
            status = FAIL
            d.append("SOURCE/DRAIN SWAPPED: the body diode (D->S) would conduct from VIN into the battery whenever "
                     "USB is present (unregulated charging) and the channel could not block it")
        else:
            status = WARN if status == PASS else status
            d.append("not in the VBUS-gate / VIN-source / VBAT-drain position")
    if not found:
        status = FAIL
    rep.add("P02", "SI2301 P-MOSFET: gate on VBUS, source on VIN, drain on VBAT, gate pull-down", status, "SI_pins", d)


def check_power_nets_distinct(nl, rep):
    pn = nl.power_nets()
    d = ["%s = %s" % (role, net) for net, role in pn.items()]
    status = PASS
    roles = list(pn.values())
    if len(set(roles)) != len(roles):
        status = FAIL
    # two different roles on the same net?
    byrole = defaultdict(list)
    for net, role in ((nl.gnd, "GND"), (nl.vbus, "VBUS"), (nl.vdd, "VDD"), (nl.vin, "VIN"), (nl.vbat, "VBAT"), (nl.batp, "BAT+")):
        if net:
            byrole[net].append(role)
    for net, rs in byrole.items():
        if len(rs) > 1 and set(rs) != {"VBAT", "BAT+"}:
            status = FAIL
            d.append("net %s carries %s - power rails shorted" % (net, rs))
        elif set(rs) == {"VBAT", "BAT+"}:
            d.append("BAT+ = VBAT: no power switch between the cell and the board")
    # hard bridges between rails (low-value resistors, inductors, closed jumpers)
    nets = list(pn)
    for i, a in enumerate(nets):
        for b in nets[i + 1:]:
            for ref, pin, onet in nl.two_pin_parts_on(a, ("res", "ind", "jumper", "tp")):
                if onet == b:
                    k = nl.kind[ref]
                    v = parse_number(nl.value(ref), "R") if k == "res" else None
                    if k == "jumper":
                        d.append("solder jumper %s between %s and %s (open by default)" % (ref, pn[a], pn[b]))
                        if {pn[a], pn[b]} != {"VBAT", "BAT+"}:
                            status = FAIL
                    elif k == "res" and v is not None and v >= 1000:
                        d.append("%s %s between %s and %s (bleeder / divider, fine)" % (ref, fmt_r(v), pn[a], pn[b]))
                    else:
                        status = FAIL
                        d.append("%s bridges %s and %s" % (nl.desc(ref), pn[a], pn[b]))
    rep.add("P03", "power rails GND/VBUS/VIN/VBAT/VDD are distinct nets, no hard bridge between them", status, "NETLIST", d)


def check_backfeed(nl, rep):
    """P04: directed conduction graph - USB must reach the battery only through the charger,
    the battery must never reach VBUS."""
    if not (nl.vbus and nl.vbat):
        rep.add("P04", "back-feed paths", SKIP, "SI_pins", [])
        return
    edges = defaultdict(list)   # net -> [(net, via)]

    def add(a, b, via):
        if a and b and a != b:
            edges[a].append((b, via))

    for ref, p in nl.parts.items():
        if nl.dnp(ref):
            continue
        k = nl.kind[ref]
        pins = nl.pins_of(ref)
        if k in ("schottky", "mdiode", "led"):
            a, kk, _ = nl.diode_ak(ref)
            add(nl.net(ref, a), nl.net(ref, kk), "%s A->K" % ref)
        elif k == "pmos":
            s, dr = nl.net(ref, "2"), nl.net(ref, "3")
            add(dr, s, "%s body diode D->S" % ref)
            if nl.net(ref, "1") != nl.vbus:
                add(s, dr, "%s channel (gate not on VBUS, may be on)" % ref)
                add(dr, s, "%s channel" % ref)
        elif k in ("ind", "tp", "slide"):
            if k == "slide":
                c = nl.net(ref, "2")
                for p2 in pins:
                    if p2 != "2":
                        add(c, nl.net(ref, p2), "%s (closed)" % ref)
                        add(nl.net(ref, p2), c, "%s (closed)" % ref)
            elif len(pins) == 2:
                add(nl.net(ref, pins[0]), nl.net(ref, pins[1]), ref)
                add(nl.net(ref, pins[1]), nl.net(ref, pins[0]), ref)
        elif k == "res" and len(pins) == 2:
            v = parse_number(nl.value(ref), "R")
            if v is not None and v < 100:
                add(nl.net(ref, pins[0]), nl.net(ref, pins[1]), ref)
                add(nl.net(ref, pins[1]), nl.net(ref, pins[0]), ref)
        elif k == "ldo":
            add(nl.net(ref, "1"), nl.net(ref, "5"), "%s LDO" % ref)
        elif k == "loadsw":
            # TPS22919: N-channel switch, conducts IN -> VOUT when ON; no reverse-current blocking is specified
            # (TPS22919_C2149796.pdf p.12-14), so VOUT -> IN is treated as possible too
            add(nl.net(ref, "1"), nl.net(ref, "6"), "%s load switch (ON)" % ref)
            add(nl.net(ref, "6"), nl.net(ref, "1"), "%s load switch (reverse)" % ref)
        elif k == "charger":
            pass  # VDD -> BAT is the intended charge path; BAT -> VDD blocked internally (see chg_txt)

    def path(src, dst, forbid_via=None):
        prev = {src: None}
        q = deque([src])
        while q:
            n = q.popleft()
            if n == dst:
                out = []
                while prev[n]:
                    pn, via = prev[n]
                    out.append("%s -(%s)-> %s" % (pn, via, n))
                    n = pn
                return list(reversed(out))
            for m, via in edges.get(n, []):
                if m not in prev:
                    prev[m] = (n, via)
                    q.append(m)
        return None

    d = []
    status = PASS
    model = nl.chg_model or "charger"
    chg_txt = {"TP4054": "TP4054 BAT->VCC blocked internally (C32574.pdf p.2)",
               "MCP73831": "MCP73831 reverse-blocking, < 2 uA from VBAT in UVLO (MCP73831_C424093.pdf p.13 4.1, "
                           "p.18 6.1.1.5)",
               "MCP73832": "MCP73832 reverse-blocking (MCP73831_C424093.pdf p.18 6.1.1.5)"}.get(model, "charger")
    p1 = path(nl.vbus, nl.vbat)
    if p1:
        status = FAIL
        d.append("USB present: VBUS reaches the battery outside the charger: " + " ; ".join(p1))
    else:
        d.append("USB present: no conduction path VBUS -> VBAT except the %s (VDD->BAT, regulated)" % model)
    for src in dict.fromkeys(n for n in (nl.vbat, nl.batp) if n):  # in this order, not a set's
        p2 = path(src, nl.vbus)
        if p2:
            status = FAIL
            d.append("battery only: %s reaches VBUS: " % nl.labels[src] + " ; ".join(p2))
        else:
            d.append("battery only: no conduction path %s -> VBUS (Schottky blocks, %s)" % (nl.labels[src], chg_txt))
    p3 = path(nl.vbus, nl.gnd)
    if p3:
        status = FAIL
        d.append("VBUS shorted to GND: " + " ; ".join(p3))
    rep.add("P04", "power path: USB cannot back-feed the battery, battery cannot back-feed VBUS", status, "SI_pins", d)


def check_battery(nl, rep):
    d = []
    status = PASS
    if nl.batconn is None:
        rep.add("P05", "battery connector / power switch", SKIP, "JST", ["no 2-pin battery connector found"])
        return
    j = nl.batconn
    d.append("battery connector %s: + -> %s ; - -> %s" % (nl.desc(j), nl.label(nl.batp), "GND"))
    names = {p: nl.pin_name(j, p) for p in nl.pins_of(j)}
    plus = [p for p, n in names.items() if nl.net(j, p) == nl.batp]
    if plus and plus[0] != "1" and names[plus[0]] not in ("+", "Pin_1", "1"):
        status = WARN
        d.append("the positive pin is %s; verify it is pin 1 ('Circuit No.1' on a JST footprint) and matches the cell lead order" % plus)
    else:
        d.append("positive on pin 1 ('Circuit No.1' on the JST footprint); the lead order of the cell itself must still be "
                 "checked with a meter before plugging it in")
    mp = [p for p in nl.pins_of(j) if p.upper().startswith("MP")]
    if mp:
        d.append("mounting pads %s -> %s (mechanical only)" % (mp, [nl.label(nl.net(j, p)) for p in mp]))
    # power switch between BAT+ and VBAT
    sws = nl.refs("slide")
    if nl.batp == nl.vbat:
        d.append("no power switch (cell directly on VBAT) - as on the BlueMicro840")
    else:
        if not sws:
            status = FAIL
            d.append("BAT+ (%s) and VBAT (%s) differ but no switch connects them" % (nl.batp, nl.vbat))
        for sw in sws:
            n1, n2, n3 = (nl.net(sw, p) for p in ("1", "2", "3"))
            d.append("%s: 1 -> %s ; 2(common) -> %s ; 3 -> %s" % (nl.desc(sw), nl.label(n1), nl.label(n2), nl.label(n3)))
            if n2 not in (nl.batp, nl.vbat):
                status = FAIL
                d.append("the common terminal 2 must be one of BAT+/VBAT, otherwise the switch never conducts")
            else:
                other = nl.vbat if n2 == nl.batp else nl.batp
                throws = [p for p, n in (("1", n1), ("3", n3)) if n == other]
                unused = [p for p, n in (("1", n1), ("3", n3)) if n not in (other, None)]
                if len(throws) != 1:
                    status = FAIL
                    d.append("exactly one throw (1 or 3) must go to %s" % nl.label(other))
                if unused:
                    status = FAIL
                    d.append("the unused throw must stay unconnected, found on %s" % [nl.label(nl.net(sw, p)) for p in unused])
                d.append("contacts rated 6 VDC / 0.3 A: battery discharge current (tens of mA) and charge current flow through it")
        for jp in nl.refs("jumper"):
            nets = {nl.net(jp, p) for p in nl.pins_of(jp)}
            if nets == {nl.batp, nl.vbat}:
                d.append("%s bypasses the switch (open by default)" % nl.desc(jp))
    rep.add("P05", "battery connector polarity, power switch uses its common terminal, bypass jumper", status, "SLIDE", d)


def check_divider(nl, rep):
    if not (nl.module and nl.vbat):
        rep.add("P06", "battery voltage divider", SKIP, "PS_saadc", [])
        return
    found = None
    for pin in sorted(E73_AIN | E73_GPIO):
        net = nl.modpin(pin)
        if net is None or net in nl.power_nets():
            continue
        top = [(r, v) for r, v in nl.resistors_between(net, nl.vbat)]
        bot = [(r, v) for r, v in nl.resistors_between(net, nl.gnd)]
        if top and bot:
            found = (pin, net, top, bot)
            break
    if not found:
        rep.add("P06", "battery voltage divider into an AIN pin", WARN, "PS_saadc",
                ["no VBAT - R - AIN - R - GND divider found (battery level not measurable)"])
        return
    pin, net, top, bot = found
    status = PASS
    d = ["module pin %d %s <- %s" % (pin, E73_PINS[pin][0], nl.label(net))]
    if pin not in E73_AIN:
        status = FAIL
        d.append("pin %d is not an analog input (AIN0-AIN7 only)" % pin)
    rt = 1 / sum(1 / v for _, v in top) if all(v for _, v in top) else None
    rb = 1 / sum(1 / v for _, v in bot) if all(v for _, v in bot) else None
    if rt is None or rb is None:
        rep.add("P06", "battery voltage divider into an AIN pin", FAIL, "PS_saadc", d + ["resistor values unreadable"])
        return
    ratio = rb / (rt + rb)
    vmax = V_VBAT_MAX * ratio
    rsrc = rt * rb / (rt + rb)
    d.append("Rtop %s (%s), Rbottom %s (%s): ratio %.4f (firmware: VBAT = Vadc * %.4f), at 4.2 V -> %.3f V"
             % (fmt_r(rt), [r for r, _ in top], fmt_r(rb), [r for r, _ in bot], ratio, 1 / ratio, vmax))
    if vmax > V_VDD:
        status = FAIL
        d.append("exceeds VDD (%.1f V): the SAADC input must stay <= VDD (gain 1/6, 0.6 V ref -> 3.6 V full scale)" % V_VDD)
    else:
        d.append("<= VDD 3.3 V and <= 3.6 V full scale with gain 1/6 and the 0.6 V internal reference")
    caps = nl.caps_between(net, nl.gnd)
    cext = sum(c for _, c in caps if c)
    lsb = SAADC_FS_1_6 / 4096.0
    tacq = [t for rmax, t in SAADC_TACQ if rsrc <= rmax]
    if tacq:
        d.append("source resistance %s -> acquisition time >= %d us (Table 95, resistive source); filter cap %s"
                 % (fmt_r(rsrc), tacq[0], [(r, fmt_c(c)) for r, c in caps] or "none"))
    else:
        # Above 800 kOhm Table 95 has no row: its model (Fig.147) is a resistive source charging the sample
        # capacitor.  A reservoir capacitor at the pin supplies that charge instead; the error is then charge
        # sharing, bounded with the largest CSAMPLE (p.397) - the method of Nordic's battery-measurement note.
        dv = vmax * SAADC_CSAMPLE / (SAADC_CSAMPLE + cext) if cext else None
        c_need = SAADC_CSAMPLE * (vmax / lsb - 1)
        if dv is None or dv > lsb:
            status = FAIL
            d.append("source resistance %s > 800 kOhm: Table 95 (p.378) has no acquisition time for it, and %s - a "
                     "reservoir capacitor >= %.1f nF to GND at the pin would let one sample move it by <= 1 LSB"
                     % (fmt_r(rsrc), "there is no capacitor at the pin" if not cext else
                        "the %s at the pin lets one 2.5 pF sample pull it by %.2f mV = %.1f LSB12"
                        % (fmt_c(cext), dv * 1e3, dv / lsb), c_need * 1e9))
        else:
            tau = rsrc * cext
            d.append("source resistance %s > 800 kOhm, above Table 95 (resistive source), but the %s reservoir at the "
                     "pin supplies the sample charge (PS Fig.147 sample network, CSAMPLE <= 2.5 pF p.397): one sample "
                     "pulls the pin by at most %.2f mV = %.2f LSB12 at %.2f V (1 LSB = %.3f mV in the 3.6 V range; "
                     "needs >= %.1f nF; Nordic's note sizes it CSAMPLE x 2^12 = %.2f nF for a full-scale input)"
                     % (fmt_r(rsrc), fmt_c(cext), dv * 1e3, dv / lsb, vmax, lsb * 1e3, c_need * 1e9,
                        SAADC_CSAMPLE * 4096 * 1e9))
            d.append("firmware conditions (not visible in the netlist): sample this pin no faster than every ~10 x "
                     "tau = 10 x %s x %s = %.2f s so the reservoir recharges (the averaged input resistance "
                     "1/(f CSAMPLE) then stays >> %s; the PS 'RINPUT > 1 MOhm' is that figure at 200 ksps); keep "
                     "RESP/RESN at Bypass (160 kOhm ladder, p.398); any TACQ works; first reading valid ~5 tau = "
                     "%.2f s after the cell is switched on"
                     % (fmt_r(rsrc), fmt_c(cext), 10 * tau, fmt_r(rsrc), 5 * tau))
            d.append("DC accuracy: the PS gives no leakage figure for an analog pin; at %s every 10 nA of pin/PCB "
                     "leakage shifts the reading by %.0f mV at the pin (%.0f mV on VBAT) - compare with a meter on "
                     "the first board and keep the node free of flux residue"
                     % (fmt_r(rsrc), rsrc * 10e-9 * 1e3, rsrc * 10e-9 / ratio * 1e3))
    d.append("divider drain from the cell: %.1f uA" % (V_VBAT_MAX / (rt + rb) * 1e6))
    extra = [(r, p) for r, p in nl.mems(net) if r != nl.module and nl.kind[r] not in ("res", "cap")]
    if extra:
        status = FAIL
        d.append("other loads on the ADC node: %s" % extra)
    rep.add("P06", "battery voltage divider: ratio, AIN pin, input <= VDD, source impedance, cap", status, "PS_saadc", d)


# --------------------------------------------------------------------- USB ---
def check_usbc(nl, rep):
    us = nl.refs("usbc")
    if not us:
        rep.add("U01", "USB-C receptacle", SKIP, "USBC", ["no USB-C receptacle"])
        return
    u = us[0]
    status = PASS
    d = ["%s%s" % (nl.desc(u), " - marked DNP in this netlist, pads checked anyway" if nl.dnp(u) else "")]
    pins = nl.parts[u]["pins"]
    groups = defaultdict(list)
    for p in pins:
        groups[USBC_ROLE.get(p, "SHIELD")].append(p)
    vbus_nets = {nl.net(u, p) for p in groups["VBUS"]}
    gnd_nets = {nl.net(u, p) for p in groups["GND"]}
    d.append("VBUS pads %s -> %s ; GND pads %s -> %s" % (groups["VBUS"], [nl.label(n) for n in vbus_nets],
                                                        groups["GND"], [nl.label(n) for n in gnd_nets]))
    if not groups["VBUS"] or vbus_nets != {nl.vbus}:
        status = FAIL
        d.append("all VBUS pads must be on the VBUS net")
    if not groups["GND"] or gnd_nets != {nl.gnd}:
        status = FAIL
        d.append("all GND pads must be on ground")
    for role in ("D+", "D-"):
        nets = {nl.net(u, p) for p in groups[role]}
        if len(nets) != 1 or None in nets:
            status = FAIL
            d.append("%s pads %s must be on one net (both orientations of the plug), found %s" % (role, groups[role], nets))
    dpn = {nl.net(u, p) for p in groups["D+"]}
    dnn = {nl.net(u, p) for p in groups["D-"]}
    if dpn & dnn:
        status = FAIL
        d.append("D+ and D- shorted")
    for role in ("CC1", "CC2"):
        for p in groups[role]:
            net = nl.net(u, p)
            rs = nl.resistors_between(net, nl.gnd) if net else []
            others = [(r, q) for r, q in nl.mems(net, exclude=u)] if net else []
            if len(rs) == 1 and 4.59e3 <= (rs[0][1] or 0) <= 5.61e3 and len(others) == 1:
                d.append("%s (%s): Rd %s %s to GND (USB-C sink, 5.1k +-10 %%)" % (role, p, rs[0][0], fmt_r(rs[0][1])))
            else:
                status = FAIL
                d.append("%s (%s): needs exactly one 5.1k pull-down to GND, found %s / other %s" % (role, p, rs, others))
    for p in groups["SBU"]:
        if nl.net(u, p) is not None and nl.mems(nl.net(u, p), exclude=u):
            status = FAIL
            d.append("SBU pad %s connected to %s - must stay open" % (p, nl.label(nl.net(u, p))))
    if groups["SBU"]:
        d.append("SBU pads %s unconnected" % groups["SBU"])
    sh = groups["SHIELD"]
    if sh:
        shn = {nl.net(u, p) for p in sh}
        if shn == {nl.gnd}:
            d.append("shield pads %s -> GND" % sh)
        elif shn <= {None} or all(not nl.mems(n, exclude=u) for n in shn if n):
            status = WARN if status == PASS else status
            d.append("shield pads %s floating (the BlueMicro840 leaves them open; tie to GND for ESD/EMI)" % sh)
        else:
            status = FAIL
            d.append("shield pads on %s" % [nl.label(n) for n in shn])
    else:
        d.append("no shield pad in the symbol")
    rep.add("U01", "USB-C receptacle: VBUS/GND/D+/D- pads, 5.1k on CC1 and CC2, SBU open, shield", status, "USBC", d)


# ------------------------------------------------- USB hub, audio, jack ---
def pin_of(table, name):
    for p, n in table.items():
        if n == name:
            return p
    return None


def ic_net(nl, ref, table, name):
    p = pin_of(table, name)
    return nl.net(ref, p) if p else None


def usb_role(nl, ref, pin):
    """'D+' / 'D-' for a USB data pin of a known part (module, codec, hub, receptacle), else None."""
    k = nl.kind[ref]
    if k == "module":
        return {str(E73_DP): "D+", str(E73_DN): "D-"}.get(str(pin))
    if k == "codec":
        return {"41": "D+", "42": "D-"}.get(str(pin))
    if k == "rp2040":
        return {str(RP_USB_DP): "D+", str(RP_USB_DM): "D-"}.get(str(pin))
    if k == "usbc":
        return USBC_ROLE.get(str(pin)) if USBC_ROLE.get(str(pin)) in ("D+", "D-") else None
    if k == "hub":
        n = CH334P_PINS.get(str(pin), "")
        if re.fullmatch(r"DP[1-4U]", n):
            return "D+"
        if re.fullmatch(r"DM[1-4U]", n):
            return "D-"
    return None


def receptacle_data_nets(nl):
    """(D+ net, D- net) of the USB-C receptacle, or (None, None)."""
    u = nl.first("usbc")
    if not u:
        return None, None
    out = []
    for role in ("D+", "D-"):
        nets = {nl.net(u, p) for p, r in USBC_ROLE.items() if r == role and p in nl.parts[u]["pins"]}
        out.append(nets.pop() if len(nets) == 1 else None)
    return tuple(out)


def follow_usb_line(nl, net, hub):
    """From a hub downstream data net: devices reached directly or through ONE series resistor, plus the
    series resistors, the shunt capacitors to GND and anything else found on the way."""
    devs, series, caps, other = [], [], [], []

    def scan(n, came_from):
        for r, p in nl.mems(n):
            if r in (hub, came_from):
                continue
            k = nl.kind[r]
            if k in ("module", "codec", "rp2040") and usb_role(nl, r, p):
                devs.append((r, p, came_from))
            elif k == "cap" and len(nl.pins_of(r)) == 2 and nl.other_end(r, p)[1] == nl.gnd:
                caps.append((r, parse_number(nl.value(r), "F")))
            elif k == "res" and len(nl.pins_of(r)) == 2 and came_from is None:
                o, onet = nl.other_end(r, p)
                series.append((r, parse_number(nl.value(r), "R")))
                if onet is not None:
                    scan(onet, r)
            else:
                other.append((r, p))
    scan(net, None)
    return devs, series, caps, other


def check_module_usb_data(nl, rep):
    if not nl.module:
        rep.add("M04", "E73 D+/D- USB data lines", SKIP, "PS_usb", [])
        return
    dp, dn = nl.modpin(E73_DP), nl.modpin(E73_DN)
    d = ["D+ (pin 31) -> %s ; D- (pin 29) -> %s" % (nl.label(dp), nl.label(dn))]
    hubs = nl.fitted("hub")
    if dp is None or dn is None or dp == dn:
        rep.add("M04", "E73 D+/D- USB data lines", FAIL, "PS_usb", d + ["D+ and D- must be two distinct nets"])
        return
    status = PASS
    if not hubs:
        # no hub: the module talks to the receptacle directly (BlueMicro840 topology)
        u = nl.first("usbc")
        if u:
            dp_pads = [p for p, r in USBC_ROLE.items() if r == "D+" and p in nl.parts[u]["pins"]]
            dn_pads = [p for p, r in USBC_ROLE.items() if r == "D-" and p in nl.parts[u]["pins"]]
            for pads, net, nm in ((dp_pads, dp, "D+"), (dn_pads, dn, "D-")):
                wrong = [p for p in pads if nl.net(u, p) != net]
                if wrong:
                    status = FAIL
                    d.append("USB-C %s pads %s are not on the module %s net (%s) -> data lines swapped or open"
                             % (nm, wrong, nm, net))
                else:
                    d.append("USB-C %s pads %s on %s" % (nm, pads, net))
        else:
            status = WARN
            d.append("no USB-C receptacle in the netlist")
        for net, nm in ((dp, "D+"), (dn, "D-")):
            extra = [(r, p) for r, p in nl.mems(net, exclude=nl.module) if nl.kind[r] not in ("usbc", "esd", "conn")]
            if extra:
                status = FAIL
                d.append("%s net also connects %s - only the receptacle and an ESD array are allowed" % (nm, extra))
            esd = [(r, p) for r, p in nl.mems(net) if nl.kind[r] == "esd"]
            if esd:
                d.append("%s protected by %s" % (nm, sorted(set(r for r, _ in esd))))
        rep.add("M04", "E73 D+/D- paired with the USB-C D+/D- pads, no other load", status, "PS_usb", d)
        return
    h = hubs[0]
    hp = [(p, CH334P_PINS.get(p, "?")) for r, p in nl.mems(dp) if r == h]
    hn = [(p, CH334P_PINS.get(p, "?")) for r, p in nl.mems(dn) if r == h]
    if len(hp) != 1 or len(hn) != 1:
        status = FAIL
        d.append("each module data line must meet exactly one %s pin; D+ meets %s, D- meets %s" % (h, hp, hn))
    else:
        (pp, pname), (pn, nname) = hp[0], hn[0]
        mp, mn = re.fullmatch(r"D([PM])([1-4U])", pname), re.fullmatch(r"D([PM])([1-4U])", nname)
        if not (mp and mn):
            status = FAIL
            d.append("module D+/D- on hub pins %s(%s) / %s(%s), which are not USB data pins" % (pp, pname, pn, nname))
        elif "U" in (mp.group(2), mn.group(2)):
            status = FAIL
            d.append("module on the hub UPSTREAM pins %s / %s: the upstream port belongs to the host side "
                     "(CH334 p.4 Table 1-3)" % (pname, nname))
        elif mp.group(2) != mn.group(2):
            status = FAIL
            d.append("module D+ on %s and D- on %s: two different downstream ports" % (pname, nname))
        elif (mp.group(1), mn.group(1)) != ("P", "M"):
            status = FAIL
            d.append("SWAPPED: module D+ on %s(pin %s), D- on %s(pin %s) - D+ must meet DP%s, D- DM%s"
                     % (pname, pp, nname, pn, mp.group(2), mp.group(2)))
        else:
            d.append("hub %s downstream port %s: DP%s (pin %s) = module D+, DM%s (pin %s) = module D-"
                     % (h, mp.group(2), mp.group(2), pp, mp.group(2), pn))
    for net, nm in ((dp, "D+"), (dn, "D-")):
        extra = [(r, p) for r, p in nl.mems(net) if r not in (nl.module, h)]
        tps = [(r, p) for r, p in extra if nl.kind[r] == "tp"]
        extra = [x for x in extra if x not in tps]
        if extra:
            status = FAIL
            d.append("%s net also connects %s: the Nordic reference circuit wires D+/D- straight (PS 7.3 Fig.210 "
                     "p.585) and the hub port has its pull-downs inside (CH334 p.1)" % (nm, extra))
        if tps:
            d.append("%s test point %s (stub; keep it short)" % (nm, tps))
    d.append("the module is a full-speed device on a hub port: no series resistor, no external pull-up or ESD "
             "array on this side (the ESD array sits at the receptacle, U02)")
    rep.add("M04", "E73 D+/D- on one USB-hub downstream port (DPn/DMn, not swapped), wired straight, nothing else",
            status, SRC["PS_usb"] + "; " + SRC["CH_usb"], d)


def check_esd(nl, rep):
    es = [r for r in nl.refs("esd") if not nl.dnp(r)]
    if not es:
        rep.add("U02", "USBLC6-2SC6 ESD array", SKIP, "USBLC6",
                ["no ESD array (the BlueMicro840 reference has none; Lira adds one)"])
        return
    status = PASS
    d = []
    # the array protects the lines where ESD enters: the receptacle's D+/D- (= the module's D+/D- when the module
    # is wired straight to the receptacle; = the hub's upstream lines when there is a hub)
    rdp, rdn = receptacle_data_nets(nl)
    if rdp and rdn:
        dp, dn, where = rdp, rdn, "receptacle"
    elif nl.module:
        dp, dn, where = nl.modpin(E73_DP), nl.modpin(E73_DN), "module"
    else:
        dp = dn = None
        where = "?"
    for e in es:
        n = {p: nl.net(e, p) for p in USBLC6_ROLE}
        d.append("%s: 1 %s | 2 %s | 3 %s | 4 %s | 5 %s | 6 %s" % ((nl.desc(e),) + tuple(nl.label(n[p]) for p in "123456")))
        for p, role in USBLC6_ROLE.items():
            nm = nl.pin_name(e, p).upper().replace(" ", "")
            if nm and nm != role.replace("IO", "I/O") and nm != role:
                status = FAIL
                d.append("pin %s named '%s', datasheet %s" % (p, nm, role))
        if n["1"] != n["6"] or n["1"] is None:
            status = FAIL
            d.append("pins 1 and 6 are the same line (I/O1) and must be on one net")
        if n["3"] != n["4"] or n["3"] is None:
            status = FAIL
            d.append("pins 3 and 4 are the same line (I/O2) and must be on one net")
        if n["1"] == n["3"]:
            status = FAIL
            d.append("I/O1 and I/O2 shorted")
        if dp and {n["1"], n["3"]} != {dp, dn}:
            status = FAIL
            d.append("I/O lines must be the %s D+ and D- nets (%s, %s): the array belongs at the connector "
                     "(p.5-6)" % (where, dp, dn))
        elif dp:
            d.append("I/O1/I/O2 on the %s D+/D- nets (%s, %s)%s" % (
                where, dp, dn, " = the hub upstream lines (U03)" if nl.fitted("hub") else ""))
        if n["2"] != nl.gnd:
            status = FAIL
            d.append("pin 2 must be GND")
        if n["5"] == nl.vbus:
            d.append("pin 5 on VBUS: rail-to-rail clamp referenced to 5 V (VBR 6 V min, leakage 150 nA at 5.25 V)")
        elif n["5"] == nl.vdd:
            d.append("pin 5 on VDD 3.3 V (also a valid reference)")
        else:
            status = FAIL
            d.append("pin 5 (VBUS) must be on VBUS or VDD, found %s" % nl.label(n["5"]))
        d.append("layout: place next to the receptacle with short tracks (p.5-6); 100 nF on VBUS suggested (p.9)")
    rep.add("U02", "USBLC6-2SC6 at the receptacle: I/O1 = pins 1+6, I/O2 = pins 3+4 on the connector D+/D-, "
            "pin 2 GND, pin 5 VBUS", status, "USBLC6", d)


def check_usb_topology(nl, rep):
    title = ("USB through the hub: receptacle -> ESD -> hub upstream DPU/DMU; each used downstream port a D+/D- "
             "pair to one device; only datasheet-allowed series parts")
    hubs = nl.fitted("hub")
    if not hubs:
        rep.add("U03", title, SKIP, "CH_usb", ["no USB hub: the module is wired to the receptacle directly (M04)"])
        return
    h = hubs[0]
    status = PASS
    d = []
    up_p, up_m = ic_net(nl, h, CH334P_PINS, "DPU"), ic_net(nl, h, CH334P_PINS, "DMU")
    rdp, rdn = receptacle_data_nets(nl)
    d.append("%s upstream: DPU(12) -> %s ; DMU(11) -> %s" % (nl.desc(h), nl.label(up_p), nl.label(up_m)))
    if rdp is None or rdn is None:
        status = FAIL
        d.append("no USB-C receptacle D+/D- nets (or A6/B6, A7/B7 split): the upstream port has no host side")
    elif (up_p, up_m) == (rdn, rdp):
        status = FAIL
        d.append("SWAPPED: DPU on the receptacle D- and DMU on D+")
    elif (up_p, up_m) != (rdp, rdn):
        status = FAIL
        d.append("DPU/DMU must be the receptacle D+/D- nets (%s / %s)" % (rdp, rdn))
    else:
        d.append("receptacle A6/B6 -> DPU, A7/B7 -> DMU; 1.5 kOhm upstream pull-up inside the hub (CH334 p.1)")
    for net, nm in ((up_p, "DPU"), (up_m, "DMU")):
        if net is None:
            continue
        extra = [(r, p) for r, p in nl.mems(net) if r != h and nl.kind[r] not in ("usbc", "esd", "tp")]
        if extra:
            status = FAIL
            d.append("%s net also carries %s: only the receptacle, the ESD array and the hub belong there" % (nm, extra))
        if not any(nl.kind[r] == "esd" for r, _ in nl.mems(net)):
            status = WARN if status == PASS else status
            d.append("%s has no ESD array: CH334 p.29 6.5 advises ESD protection on every USB signal" % nm)
    seen_dev = defaultdict(list)
    for k in "1234":
        pp, pm = pin_of(CH334P_PINS, "DP" + k), pin_of(CH334P_PINS, "DM" + k)
        np_, nm_ = nl.net(h, pp), nl.net(h, pm)
        if np_ is None and nm_ is None:
            d.append("port %s (DP%s pin %s / DM%s pin %s): unused, left open (host pull-downs inside, CH334 p.1)"
                     % (k, k, pp, k, pm))
            continue
        if np_ is None or nm_ is None:
            status = FAIL
            d.append("port %s half connected: DP%s -> %s, DM%s -> %s" % (k, k, nl.label(np_), k, nl.label(nm_)))
            continue
        res = {}
        for line, net in (("DP", np_), ("DM", nm_)):
            res[line] = follow_usb_line(nl, net, h)
        devs = {line: res[line][0] for line in res}
        if len(devs["DP"]) != 1 or len(devs["DM"]) != 1 or devs["DP"][0][0] != devs["DM"][0][0]:
            status = FAIL
            d.append("port %s: DP%s reaches %s, DM%s reaches %s - expected the two lines of ONE device"
                     % (k, k, [(r, p) for r, p, _ in devs["DP"]], k, [(r, p) for r, p, _ in devs["DM"]]))
            continue
        dev = devs["DP"][0][0]
        rp, rm = usb_role(nl, dev, devs["DP"][0][1]), usb_role(nl, dev, devs["DM"][0][1])
        seen_dev[dev].append(k)
        kind = nl.kind[dev]
        line_txt = "port %s -> %s %s" % (k, kind, nl.desc(dev))
        if (rp, rm) != ("D+", "D-"):
            status = FAIL
            d.append("%s: SWAPPED - DP%s meets the device %s pin, DM%s its %s pin" % (line_txt, k, rp, k, rm))
            continue
        problems, notes = [], []
        for line in ("DP", "DM"):
            _, series, caps, other = res[line]
            if other:
                problems.append("%s%s also meets %s" % (line, k, other))
            if kind == "module":
                if series or caps:
                    problems.append("%s%s: series %s / shunt %s - the nRF52840 lines are wired straight "
                                    "(PS 7.3 Fig.210)" % (line, k, series, caps))
            elif kind == "rp2040":
                # RP2040 datasheet 1.4.2 / Table 620: a 27 Ohm series termination resistor is required on each pin
                if len(series) != 1:
                    problems.append("%s%s: %s - the RP2040 needs exactly one 27 Ohm series resistor per line" % (
                        line, k, "no series resistor" if not series else "%d resistors in series" % len(series)))
                for r, v in series:
                    if v is None or not (24.3 <= v <= 29.7):
                        problems.append("%s%s: series resistor %s = %s, not 27 Ohm" % (line, k, r, fmt_r(v)))
                    else:
                        notes.append("%s%s via %s %s Ohm" % (line, k, r, fmt_r(v)))
                if caps:
                    problems.append("%s%s: shunt %s - none in the RP2040 documents" % (line, k, caps))
            elif kind == "codec":
                if len(series) != 1:
                    if not series:
                        notes.append("%s%s: no series resistor (C-Media app note 3.5 / demo board: 22-39 Ohm for PHY "
                                     "impedance matching)" % (line, k))
                    else:
                        problems.append("%s%s: %d resistors in series" % (line, k, len(series)))
                for r, v in series:
                    if v is None or not (15.0 <= v <= 47.0):
                        problems.append("%s%s: series resistor %s = %s outside the 22-39 Ohm of the C-Media "
                                        "documents" % (line, k, r, fmt_r(v)))
                    else:
                        notes.append("%s%s via %s %s Ohm" % (line, k, r, fmt_r(v)))
                for r, c in caps:
                    if c is None or c > 101e-12:
                        problems.append("%s%s: %s %s to GND - the demo board allows at most 100 pF (C1/C2)"
                                        % (line, k, r, fmt_c(c)))
                    else:
                        notes.append("%s%s: %s %s to GND (as demo board C1/C2)" % (line, k, r, fmt_c(c)))
        if problems:
            status = FAIL
            d.append("%s: %s" % (line_txt, "; ".join(problems)))
        else:
            d.append("%s: D+ <- DP%s, D- <- DM%s%s%s" % (
                line_txt, k, k, (" ; " + "; ".join(notes)) if notes else "",
                " (C-Media demo board R4/R66 22 Ohm, app note 3.5 39 Ohm)" if kind == "codec" else
                " (straight, as PS 7.3 Fig.210)" if kind == "module" else
                " (27 Ohm series termination, RP2040 datasheet 1.4.2 / Table 620)" if kind == "rp2040" else ""))
        if notes and any("no series resistor" in x for x in notes):
            status = WARN if status == PASS else status
    for dev, ports in seen_dev.items():
        if len(ports) > 1:
            status = FAIL
            d.append("%s is on several ports %s" % (dev, ports))
    if nl.module and nl.module not in seen_dev:
        status = FAIL
        d.append("the module is not on any downstream port")
    if nl.rp and nl.rp not in seen_dev:
        status = FAIL
        d.append("the RP2040 is not on any downstream port")
    rep.add("U03", title, status, SRC["CH_usb"] + "; " + SRC["RP_usb"] if nl.rp else "CH_usb", d)


# ---------------------------------------------------------------- CH334P hub --
def check_hub_power(nl, rep):
    title = ("CH334P: pinout, GND pad, V5 on VBUS (4.5-5.25 V, abs max 5.5 V) with >= 1 uF, VDD33 0.1 uF + 10 uF "
             "(or >= 1 uF), no load on the internal LDO")
    hubs = nl.fitted("hub")
    if not hubs:
        rep.add("H01", title, SKIP, "CH_power", ["no CH334/CH335 hub"])
        return
    status = PASS
    d = []
    for h in hubs:
        mism = nl.name_mismatches(h, CH334P_PINS, {"RESET#/CDP": ("RESET#", "RESET", "RST#", "RESET#CDP")})
        if mism:
            status = FAIL
            d += ["%s %s (CH334_C5373042-p2-pinout.png)" % (h, m) for m in mism]
        eps = {p: nl.net(h, p) for p in nl.extra_pins(h, CH334P_PINS)}
        if not eps:
            status = FAIL
            d.append("%s: no exposed-pad pin in the symbol - on the CH334P the pad (pin 0) is the ONLY ground" % h)
        elif any(n != nl.gnd for n in eps.values()):
            status = FAIL
            d.append("%s exposed pad %s must be GND (pin 0 = GND, the only ground of the QFN-16)" % (h, eps))
        else:
            d.append("%s exposed pad %s -> GND (the CH334P's only ground pin)" % (h, list(eps)))
        v5, v33 = ic_net(nl, h, CH334P_PINS, "V5"), ic_net(nl, h, CH334P_PINS, "VDD33")
        d.append("%s: V5(15) -> %s ; VDD33(16) -> %s" % (nl.desc(h), nl.label(v5), nl.label(v33)))
        if v5 is None or v33 is None:
            status = FAIL
            d.append("V5 and VDD33 must both be connected")
            continue
        five = v5 in (nl.vbus, nl.vaud) and v5 is not None
        if five and v33 not in nl.power_nets():
            d.append("internal LDO in use: V5 from %s (USB 2.0 VBUS 4.75-5.25 V inside 4.5-5.25 V, p.19 4.2; "
                     "a USB-C source may give up to %.1f V = the V5 absolute maximum of 5.5 V, p.19 4.1)"
                     % (nl.labels.get(v5, v5), V_VBUS_MAX))
        elif v5 == v33 and v5 == nl.vdd and v5 is not None:
            d.append("V5 = VDD33 = the 3.3 V rail: LDO bypassed (3.15-3.5 V, p.19; p.28 6.4)")
        elif five:
            status = FAIL
            d.append("V5 on 5 V but VDD33 tied to the %s rail: the LDO output would fight that rail (VDD33 is either "
                     "the LDO output or, with V5 also on 3.3 V, the 3.3 V input - p.4 Table 1-3)" % nl.labels[v33])
        else:
            status = FAIL
            d.append("V5 must be the USB 5 V (bus-powered, p.26 6.1) or, together with VDD33, a 3.3 V rail (p.28 6.4)")
        c5 = nl.cap_total(v5)
        d.append("V5 capacitance %s (%s)" % (fmt_c(c5), [r for r, _ in nl.cap_list(v5)]))
        if c5 < 1e-6 * 0.999:
            status = FAIL
            d.append("V5 needs 1 uF or more (p.4 Table 1-3)")
        if v33 != v5:
            caps = nl.cap_list(v33)
            c33 = sum(c for _, c in caps if c)
            has_big = any(c and c >= 9.9e-6 for _, c in caps)
            has_small = any(c and c <= 0.11e-6 for _, c in caps)
            d.append("VDD33 capacitors %s = %s" % ([(r, fmt_c(c)) for r, c in caps], fmt_c(c33)))
            if c33 < 1e-6 * 0.999:
                status = FAIL
                d.append("VDD33 needs 0.1 uF + 10 uF, or at least 1 uF (p.4 Table 1-3)")
            elif has_big and has_small:
                d.append("0.1 uF + 10 uF as in p.4 / p.26 6.1 (10 uF or more also helps against hot-plug dips, p.26)")
            else:
                d.append(">= 1 uF: the minimum option of p.4")
            load = nl.non_cap_members(v33, exclude=(h,))
            load = [x for x in load if nl.kind[x[0]] != "tp"]
            if load and five:
                status = WARN if status == PASS else status
                d.append("VDD33 also feeds %s: the internal LDO supplies at most 20 mA to outside loads (p.19 4.2)" % load)
        if nl.vbat is None:
            d.append("V5 straight from VBUS (as p.26 6.1); p.28 6.4's embedded-hub option (V5 = VDD33 = the on-board "
                     "3.3 V) would put the hub on the 3.3 V regulator instead - either is allowed")
        else:
            d.append("V5 straight from VBUS (as p.26 6.1); p.28 6.4 suggests the on-board 3.3 V for embedded hubs, but "
                     "here that rail is battery-backed and the hub would then draw its 0.12-0.4 mA sleep current from the "
                     "cell: the VBUS supply is the better choice")
    rep.add("H01", title, status, "CH_power", d)


def check_hub_crystal(nl, rep):
    title = "CH334P clock: 12 MHz crystal between XI and XO, no external load capacitors (~16 pF inside), case to GND"
    hubs = nl.fitted("hub")
    if not hubs:
        rep.add("H02", title, SKIP, "CH_xtal", ["no CH334/CH335 hub"])
        return
    status = PASS
    d = []
    for h in hubs:
        xi, xo = ic_net(nl, h, CH334P_PINS, "XI"), ic_net(nl, h, CH334P_PINS, "XO")
        d.append("%s: XI(2) -> %s ; XO(1) -> %s" % (nl.desc(h), nl.label(xi), nl.label(xo)))
        if xo is None and xi == nl.gnd:
            status = WARN
            d.append("crystal-free wiring (XO open, XI to GND): works only on parts ordered with that option (p.27 6.2)")
            continue
        if xi is None or xo is None or xi == xo:
            status = FAIL
            d.append("XI/XO need a 12 MHz crystal between them (p.4 Table 1-3) or the crystal-free wiring (p.27)")
            continue
        xts = [r for r in nl.fitted("xtal") if {xi, xo} <= {nl.net(r, p) for p in nl.pins_of(r)}]
        if len(xts) != 1:
            status = FAIL
            d.append("expected one crystal between XI and XO, found %s" % xts)
            continue
        y = xts[0]
        f = re.search(r"(\d+(?:[.,]\d+)?)\s*MHZ", nl.value(y).upper())
        fmhz = float(f.group(1).replace(",", ".")) if f else None
        want = 24.0 if "CH334X" in nl.value(h).upper() else 12.0
        if fmhz is None or abs(fmhz - want) > 0.001:
            status = FAIL
            d.append("%s value '%s': the %s needs a %g MHz crystal (p.4)" % (y, nl.value(y), nl.value(h), want))
        else:
            d.append("%s %s between XI and XO" % (nl.desc(y), nl.value(y)))
        for p in nl.pins_of(y):
            n = nl.net(y, p)
            if n not in (xi, xo, nl.gnd, None):
                status = FAIL
                d.append("%s pin %s (case) on %s - case pads go to GND or stay open" % (y, p, nl.label(n)))
        for net, nm in ((xi, "XI"), (xo, "XO")):
            caps = nl.cap_list(net)
            if caps:
                status = WARN if status == PASS else status
                d.append("%s has external load capacitors %s: XI/XO already have ~16 pF inside, p.26 6.1 advises "
                         "none" % (nm, caps))
            extra = [(r, p) for r, p in nl.mems(net) if r not in (h, y) and nl.kind[r] != "cap"]
            if extra:
                status = FAIL
                d.append("%s also connects %s - oscillator pins carry only the crystal" % (nm, extra))
        d.append("no load capacitors (p.26: ~16 pF built in) -> load ~ 16 pF / 2 + 2-3 pF stray = 10-11 pF; the "
                 "crystal's CL is not in the datasheet set (PARTS.txt: generic 20 pF): with typical C1 5 fF / C0 2 pF "
                 "a 20 pF crystal runs ~ +50..+100 ppm fast - inside the +-500 ppm USB high-speed budget; a 10-12 pF "
                 "crystal would centre it")
    rep.add("H02", title, status, "CH_xtal", d)


def check_hub_cfg(nl, rep):
    title = "CH334P RESET#/CDP and PGANG left open (or legally driven), unused downstream ports open"
    hubs = nl.fitted("hub")
    if not hubs:
        rep.add("H03", title, SKIP, "CH_cfg", ["no CH334/CH335 hub"])
        return
    status = PASS
    d = []
    for h in hubs:
        rst = ic_net(nl, h, CH334P_PINS, "RESET#/CDP")
        pg = ic_net(nl, h, CH334P_PINS, "PGANG")
        if rst is None:
            d.append("%s RESET#/CDP(13) open: internal power-on reset and ~25 kOhm pull-up, CDP off, low-power sleep "
                     "allowed (p.4 'leave fully floating'; p.11 Table 3-2)" % h)
        elif rst == nl.gnd:
            status = FAIL
            d.append("RESET#/CDP tied to GND: the hub is held in reset (p.11 Table 3-2)")
        elif rst in nl.power_nets():
            status = WARN if status == PASS else status
            d.append("RESET#/CDP tied to %s: CDP charging mode on and low-power sleep off (p.11 Table 3-2); p.4 "
                     "asks to leave it floating" % nl.labels[rst])
        else:
            others = nl.mems(rst, exclude=h)
            gp = [p for r, p in others if r == nl.mcu]
            dio = [r for r, p in others if nl.kind[r] in ("schottky", "mdiode")]
            if gp:
                status = WARN if status == PASS else status
                d.append("RESET#/CDP driven straight by %s pin %s: a high level at power-up turns CDP on and "
                         "sleep off (p.11); Fig.3-2-2 puts a Schottky in series" % (nl.mcu_word, gp))
            elif dio:
                d.append("RESET#/CDP driven through %s (p.11 Fig.3-2-2)" % dio)
            else:
                status = WARN if status == PASS else status
                d.append("RESET#/CDP on %s with %s: p.4 asks to leave it floating unless a reset is needed"
                         % (nl.label(rst), others))
        if pg is None:
            d.append("PGANG(14) open: internal pull-up (default configuration); it turns into a status output after "
                     "reset (p.5)")
        elif pg in nl.power_nets():
            status = FAIL
            d.append("PGANG tied to %s: it becomes an output after reset (p.5), a hard tie fights it; use a resistor"
                     % nl.labels[pg])
        else:
            pulls = nl.resistors_between(pg, nl.gnd)
            if pulls and len(nl.mems(pg, exclude=h)) == len(pulls):
                d.append("PGANG pulled down by %s: individual over-current mode (p.5)" % pulls)
            else:
                status = WARN if status == PASS else status
                d.append("PGANG on %s with %s" % (nl.label(pg), nl.mems(pg, exclude=h)))
        for k in "1234":
            nets = [ic_net(nl, h, CH334P_PINS, "DP" + k), ic_net(nl, h, CH334P_PINS, "DM" + k)]
            if nets == [None, None]:
                d.append("port %s unused: DP%s/DM%s open (pull-downs inside, p.1)" % (k, k, k))
    rep.add("H03", title, status, "CH_cfg", d)


# ---------------------------------------------------------------- CM108B codec --
def cm_level(nl, c, name):
    """Logic level of a CM108B jumper input: ('L'|'H'|'?'|'5V', how) using the internal pulls of p.7-8."""
    net = ic_net(nl, c, CM108B_PINS, name)
    pull = CM108B_JUMPERS.get(name)
    if net is None:
        return ("H" if pull == "PU" else "L"), "open (internal pull-%s)" % ("up" if pull == "PU" else "down")
    reg33 = ic_net(nl, c, CM108B_PINS, "DREG33")
    if net == nl.gnd:
        return "L", "tied to GND"
    if net in (reg33, nl.vdd):
        return "H", "tied to %s" % nl.label(net)
    if net in (nl.vbus, nl.vaud, nl.vin, nl.vbat, nl.batp):
        return "5V", "tied to %s" % nl.labels[net]
    ups = [(r, o) for r, p, o in nl.two_pin_parts_on(net, ("res",)) if o in (reg33, nl.vdd)]
    hi5 = [(r, o) for r, p, o in nl.two_pin_parts_on(net, ("res",)) if o in (nl.vbus, nl.vaud, nl.vin, nl.vbat)]
    downs = [(r, o) for r, p, o in nl.two_pin_parts_on(net, ("res",)) if o == nl.gnd]
    if hi5:
        return "5V", "pulled to %s by %s" % (nl.labels[hi5[0][1]], hi5[0][0])
    if ups and not downs:
        return "H", "pulled up by %s" % ups[0][0]
    if downs and not ups:
        return "L", "pulled down by %s" % downs[0][0]
    return "?", "on %s" % nl.label(net)


def mic_used(nl, c):
    micin = ic_net(nl, c, CM108B_PINS, "MICIN")
    return micin is not None and bool(nl.mems(micin, exclude=c))


def check_codec_supply(nl, rep):
    title = "CM108B supply: AVDD/DVDD on a 4.5-5.5 V rail (through ferrite beads), DVSS/AVSS on GND, decoupling"
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A01", title, SKIP, "CM_power", ["no CM108B"])
        return
    status = PASS
    d = []
    for c in cs:
        mism = nl.name_mismatches(c, CM108B_PINS, {"ADSCLK": ("ADSCLS",)})
        if mism:
            status = FAIL
            d += ["%s %s (p.6-8)" % (c, m) for m in mism]
        for p in ("14", "36", "24", "33"):
            if nl.net(c, p) != nl.gnd:
                status = FAIL
                d.append("%s pin %s (%s) must be on GND, found %s" % (c, p, CM108B_PINS[p], nl.label(nl.net(c, p))))
        avdd = {nl.net(c, "29"), nl.net(c, "34")}
        dvdd = nl.net(c, "35")
        if len(avdd) != 1 or None in avdd:
            status = FAIL
            d.append("AVDD pins 29 and 34 must both be on one supply net, found %s" % [nl.label(n) for n in avdd])
            continue
        avdd = avdd.pop()
        for net, nm in ((avdd, "AVDD"), (dvdd, "DVDD")):
            reach = nl.through_series(net, kinds=("ind",), depth=1) if net else {}
            rails = [(n, via) for n, via in reach.items() if n in (nl.vbus, nl.vaud) and n is not None]
            if not rails:
                status = FAIL
                d.append("%s on %s: not supplied from a 4.5-5.5 V rail (p.20 8.2; DVdd = AVdd = 5 V, p.4)"
                         % (nm, nl.label(net)))
                continue
            rail, via = rails[0]
            d.append("%s %s <- %s%s: %s 4.75-5.25 V (USB 2.0) through the load switch, inside 4.5-5.5 V (p.20), "
                     "abs max 6 V" % (nm, nl.label(net), nl.labels.get(rail, rail),
                                      (" via bead %s" % via) if via else " directly", nl.labels.get(rail, rail)))
            caps = nl.cap_list(net)
            tot = sum(x for _, x in caps if x)
            if not caps:
                status = FAIL
                d.append("%s has no decoupling capacitor at the pin side%s" % (nm, " of the bead" if via else ""))
                continue
            small = [r for r, x in caps if x and x <= 0.11e-6]
            if nm == "DVDD":
                d.append("DVDD capacitors %s = %s (demo board: 4.7 uF + 0.1 uF)" % ([(r, fmt_c(x)) for r, x in caps], fmt_c(tot)))
                if tot < 4.7e-6 * 0.999 or not small:
                    status = WARN if status == PASS else status
                    d.append("DVDD: less than the demo board's 4.7 uF + 0.1 uF (C4/C6)")
            else:
                d.append("AVDD capacitors %s (demo board: 0.1 uF C7)" % [(r, fmt_c(x)) for r, x in caps])
                if not small:
                    status = WARN if status == PASS else status
                    d.append("AVDD: no 0.1 uF-class ceramic at the pins (demo board C7)")
        d.append("current 37.25 mA typ (p.20); ambient 0-70 C only (p.20)")
    rep.add("A01", title, status, "CM_power", d)


def check_codec_regs(nl, rep):
    title = ("CM108B regulator/reference pins: DREG18 1 uF, DREG33 0.1 uF, AREG36 10 uF, VREF 10 uF, LOBS 10 uF, "
             "no external load")
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A02", title, SKIP, "CM_power", ["no CM108B"])
        return
    status = PASS
    d = []
    spec = [("DREG18", 1e-6, "app note p.8 3.4 (1 uF), demo C17", False),
            ("DREG33", 0.1e-6, "app note p.8 3.4 (0.1 uF), demo C18; may feed up to 40 mA (p.7)", True),
            ("AREG36", 10e-6, "app note p.25 (10 uF to AGND), demo C3", False),
            ("VREF", 10e-6, "p.7 'connect a decoupling capacitor', demo C14 10 uF", False),
            ("LOBS", 10e-6, "demo board C10 10 uF", False)]
    for c in cs:
        dvdd = nl.net(c, "35")
        for name, ref_c, why, may_load in spec:
            net = ic_net(nl, c, CM108B_PINS, name)
            if net is None:
                if name == "LOBS":
                    status = WARN if status == PASS else status
                    d.append("LOBS open: the demo board decouples it with 10 uF (C10)")
                else:
                    status = FAIL
                    d.append("%s unconnected: needs its capacitor (%s)" % (name, why))
                continue
            caps = nl.cap_list(net)
            tot = sum(x for _, x in caps if x)
            to_dvdd = nl.caps_between(net, dvdd) if dvdd else []
            others = [(r, p) for r, p in nl.mems(net) if r != c and not (
                nl.kind[r] == "cap" and nl.other_end(r, p)[1] in (nl.gnd, dvdd))]
            line = "%s(%s) -> %s: %s to GND%s" % (name, pin_of(CM108B_PINS, name), nl.label(net),
                                                  [(r, fmt_c(x)) for r, x in caps] or "none",
                                                  "; %s to DVDD (demo C23/C24 'close to IC')"
                                                  % [(r, fmt_c(x)) for r, x in to_dvdd] if to_dvdd else "")
            d.append(line)
            if net in nl.power_nets():
                status = FAIL
                d.append("  %s is a regulator/reference output and must not sit on %s" % (name, nl.labels[net]))
                continue
            if not caps:
                status = FAIL
                d.append("  no capacitor to GND (%s)" % why)
            elif tot < 0.5 * ref_c:
                status = WARN if status == PASS else status
                d.append("  %s is well below the reference value %s (%s)" % (fmt_c(tot), fmt_c(ref_c), why))
            if others:
                if may_load:
                    d.append("  also feeds %s (DREG33 drives up to 40 mA, p.7)" % others)
                elif name == "LOBS":
                    pass        # judged by A05 (cap-less headphone return or not)
                else:
                    status = FAIL
                    d.append("  %s also connects %s: internal regulator/reference, decoupling only" % (name, others))
    rep.add("A02", title, status, "CM_power", d)


def check_codec_cfg(nl, rep):
    title = "CM108B jumper pins: TEST low, MODE (headset) and ADSEL (internal ADC) low when the mic is used, <= 3.3 V"
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A03", title, SKIP, "CM_cfg", ["no CM108B"])
        return
    status = PASS
    d = []
    for c in cs:
        lv = {nm: cm_level(nl, c, nm) for nm in CM108B_JUMPERS}
        d.append("%s: %s" % (c, ", ".join("%s=%s (%s)" % (nm, l, how) for nm, (l, how) in lv.items())))
        for nm, (l, how) in lv.items():
            if l == "5V":
                status = FAIL
                d.append("%s %s: jumper pins are 3.3 V inputs ('H: push up to 3.3V', p.7-8)" % (nm, how))
            elif l == "?":
                status = WARN if status == PASS else status
                d.append("%s level not determinable (%s)" % (nm, how))
        if lv["TEST"][0] == "H":
            status = FAIL
            d.append("TEST high = test mode (p.8): must be low for normal operation")
        if mic_used(nl, c):
            if lv["MODE"][0] != "L":
                status = FAIL
                d.append("MICIN is wired but MODE is high = speaker mode, playback only: no recording function is "
                         "declared to the host (p.7, p.15 7.2.1)")
            if lv["ADSEL"][0] != "L":
                status = FAIL
                d.append("ADSEL high selects the external I2S ADC: MICIN would be ignored (p.8)")
        mode = {"L": "headset (playback + recording)", "H": "speaker (playback only)"}.get(lv["MODE"][0], "?")
        pw = {("L", "H"): "100 mA bus-powered", ("L", "L"): "500 mA bus-powered",
              ("H", "H"): "100 mA self-powered", ("H", "L"): "500 mA bus-powered"}.get((lv["MODE"][0], lv["PWRSEL"][0]), "?")
        d.append("result: %s, %s (p.15 table), mixer %s (MSEL %s)" % (
            mode, pw, "enabled, muted by default" if lv["MSEL"][0] == "H" else "disabled", lv["MSEL"][0]))
        for p, nm in CM108B_PINS.items():
            if nm in ("SPDIFO", "DW", "SK", "CS", "LEDO", "LEDR", "ADSCLK", "ADLRCK", "ADMCLK", "SDOUT", "DAMCLK",
                      "DALRCK", "DASCLK", "PDSW", "GPIO1", "GPIO3", "GPIO4", "MUTER", "MUTEP", "VOLUP", "VOLDN",
                      "SDIN", "DR", "NC"):
                n = nl.net(c, p)
                if n is not None and n in nl.power_nets():
                    status = FAIL
                    d.append("pin %s %s tied to %s" % (p, nm, nl.labels[n]))
    rep.add("A03", title, status, "CM_cfg", d)


def check_codec_usb(nl, rep):
    title = "CM108B USBDP/USBDM: one 22-39 Ohm series resistor each to a USB port, no external D+ pull-up"
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A04", title, SKIP, "CM_usb", ["no CM108B"])
        return
    status = PASS
    d = []
    for c in cs:
        for p, role in (("41", "D+"), ("42", "D-")):
            net = nl.net(c, p)
            d.append("%s %s (%s) -> %s" % (c, CM108B_PINS[p], p, nl.label(net)))
            if net is None:
                status = FAIL
                d.append("  unconnected: the codec cannot enumerate")
                continue
            if net in nl.power_nets():
                status = FAIL
                d.append("  data pin on %s" % nl.labels[net])
                continue
            ports, series = [], []
            for r, pin in nl.mems(net, exclude=c):
                rl = usb_role(nl, r, pin)
                if rl:
                    ports.append((r, pin, rl, None))
                    continue
                if nl.kind[r] == "res" and len(nl.pins_of(r)) == 2:
                    o, onet = nl.other_end(r, pin)
                    v = parse_number(nl.value(r), "R")
                    if onet in nl.power_nets() or onet == ic_net(nl, c, CM108B_PINS, "DREG33"):
                        status = FAIL
                        d.append("  %s %s from %s to %s: the D+ pull-up is inside the PHY (app note p.9 3.5, p.23 "
                                 "5.3) - an external one breaks the USB termination" % (r, fmt_r(v), CM108B_PINS[p], nl.label(onet)))
                        continue
                    far = [(r2, p2, usb_role(nl, r2, p2)) for r2, p2 in nl.mems(onet, exclude=r) if usb_role(nl, r2, p2)]
                    if far:
                        ports.append((far[0][0], far[0][1], far[0][2], (r, v)))
                        series.append((r, v))
                    else:
                        status = WARN if status == PASS else status
                        d.append("  %s leads to %s (no USB port pin there)" % (r, nl.label(onet)))
                elif nl.kind[r] == "cap" and nl.other_end(r, pin)[1] == nl.gnd:
                    v = parse_number(nl.value(r), "F")
                    if v is None or v > 101e-12:
                        status = FAIL
                        d.append("  %s %s to GND on the line (demo board: <= 100 pF)" % (r, fmt_c(v)))
                else:
                    status = FAIL
                    d.append("  %s.%s (%s) on the data line" % (r, pin, nl.kind[r]))
            if len(ports) != 1:
                status = FAIL
                d.append("  expected exactly one USB port pin (hub DPn/DMn or receptacle), found %s" % ports)
                continue
            r2, p2, rl, ser = ports[0]
            if rl != role:
                status = FAIL
                d.append("  SWAPPED: codec %s meets the %s line of %s (pin %s)" % (role, rl, r2, p2))
            if ser is None:
                status = WARN if status == PASS else status
                d.append("  no series resistor (app note 3.5: for PHY impedance matching; demo board 22 Ohm)")
            elif ser[1] is None or not (15.0 <= ser[1] <= 47.0):
                status = FAIL
                d.append("  series %s %s outside the 22-39 Ohm of the C-Media documents" % (ser[0], fmt_r(ser[1])))
            else:
                d.append("  %s %s Ohm in series to %s pin %s (%s): as demo board R4/R66 (22 Ohm) / app note (39 Ohm)"
                         % (ser[0], fmt_r(ser[1]), r2, p2, CH334P_PINS.get(p2, p2) if nl.kind[r2] == "hub" else rl))
        d.append("no external pull-up: the CM108B PHY has it inside (app note p.9 3.5 and p.23 5.3)")
    rep.add("A04", title, status, "CM_usb", d)


def check_codec_lineout(nl, rep):
    title = "CM108B LOL/LOR AC-coupled into the amplifier (LOL -> INL-, LOR -> INR-); LOBS only decoupled"
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A05", title, SKIP, "CM_audio", ["no CM108B"])
        return
    status = PASS
    d = []
    amps = nl.fitted("hpamp")
    for c in cs:
        for nm, want in (("LOL", "INL-"), ("LOR", "INR-")):
            net = ic_net(nl, c, CM108B_PINS, nm)
            if net is None:
                d.append("%s unconnected (no playback on this channel)" % nm)
                status = WARN if status == PASS else status
                continue
            mem = nl.mems(net, exclude=c)
            caps = [(r, p) for r, p in mem if nl.kind[r] == "cap" and nl.other_end(r, p)[1] not in (nl.gnd, None)]
            gcaps = [(r, p) for r, p in mem if nl.kind[r] == "cap" and nl.other_end(r, p)[1] == nl.gnd]
            direct_amp = [(r, p) for r, p in mem if nl.kind[r] == "hpamp"]
            others = [x for x in mem if x not in caps and x not in gcaps]
            if direct_amp:
                status = FAIL
                d.append("%s DC-coupled to %s: the line out sits at the 1.75 V LOBS bias (p.7), above the TPA6132A2 "
                         "common-mode range -0.5..1.5 V (TPA p.5) - an input capacitor is required (TPA p.15)"
                         % (nm, direct_amp))
                continue
            if others:
                status = FAIL
                d.append("%s also drives %s" % (nm, others))
            if len(caps) != 1:
                status = FAIL
                d.append("%s: expected one series coupling capacitor, found %s" % (nm, caps))
                continue
            cref, cp = caps[0]
            far = nl.other_end(cref, cp)[1]
            hits = [(r, p) for r, p in nl.mems(far, exclude=cref) if nl.kind[r] == "hpamp"]
            if amps:
                if not hits:
                    status = FAIL
                    d.append("%s -> %s %s -> %s: does not reach the amplifier" % (nm, cref, nl.value(cref), nl.label(far)))
                    continue
                a, ap = hits[0]
                got = TPA6132_PINS.get(ap, "?")
                if got != want:
                    status = FAIL
                    d.append("%s -> %s -> %s %s (pin %s): channel or polarity wrong, expected %s (single-ended input "
                             "into the inverting pin, TPA p.3)" % (nm, cref, a, got, ap, want))
                else:
                    d.append("%s -> %s %s (series) -> %s %s (pin %s)%s" % (
                        nm, cref, nl.value(cref), a, got, ap,
                        " ; plus %s to GND" % gcaps if gcaps else ""))
            else:
                d.append("%s -> %s %s -> %s (no amplifier: the codec drives the jack itself; demo board uses 100 uF "
                         "+ 39 Ohm)" % (nm, cref, nl.value(cref), nl.label(far)))
        lobs = ic_net(nl, c, CM108B_PINS, "LOBS")
        if lobs is not None:
            jack_hit = [(r, p) for r, p in nl.mems(lobs) if nl.kind[r] == "jack"]
            reach = nl.through_series(lobs, kinds=("ind", "res"), max_ohm=100, depth=1,
                                      no_enter=set(nl.power_nets()))
            jack_far = [(r, p) for n in reach for r, p in nl.mems(n) if nl.kind[r] == "jack"]
            non_cap = [(r, p) for r, p in nl.mems(lobs) if r != c and not (
                nl.kind[r] == "cap" and nl.other_end(r, p)[1] == nl.gnd)]
            if (jack_hit or jack_far) and amps:
                status = FAIL
                d.append("LOBS reaches the jack %s: cap-less return (app note 3.2) is only for the codec driving the "
                         "headphones; with the DirectPath TPA6132A2 the jack ground must be GND (TPA p.18 10.3)"
                         % (jack_hit or jack_far))
            elif non_cap:
                status = WARN if status == PASS else status
                d.append("LOBS also connects %s" % non_cap)
            else:
                d.append("LOBS only decoupled to GND (%s): normal, not cap-less, output mode"
                         % [(r, fmt_c(x)) for r, x in nl.cap_list(lobs)])
    rep.add("A05", title, status, "CM_audio", d)


def check_codec_mic(nl, rep):
    title = "CM108B microphone: MICIN AC-coupled from the mic contact, VBIAS through resistors, bias current"
    cs = nl.fitted("codec")
    if not cs:
        rep.add("A06", title, SKIP, "CM_audio", ["no CM108B"])
        return
    status = PASS
    d = []
    for c in cs:
        micin, vbias = ic_net(nl, c, CM108B_PINS, "MICIN"), ic_net(nl, c, CM108B_PINS, "VBIAS")
        if micin is None and vbias is None:
            d.append("%s: MICIN and VBIAS unused (no recording)" % c)
            continue
        if micin is None or vbias is None:
            status = FAIL
            d.append("%s: MICIN -> %s, VBIAS -> %s: an electret needs both" % (c, nl.label(micin), nl.label(vbias)))
            continue
        mem = nl.mems(micin, exclude=c)
        caps = [(r, p) for r, p in mem if nl.kind[r] == "cap" and nl.other_end(r, p)[1] not in (nl.gnd, None)]
        dc = [(r, p) for r, p in mem if (r, p) not in caps and not (
            nl.kind[r] == "cap" and nl.other_end(r, p)[1] == nl.gnd)]
        if dc or len(caps) != 1:
            status = FAIL
            d.append("MICIN must be fed through one series capacitor (app note p.23 5.4; demo C12 1 uF): series caps "
                     "%s, other connections %s" % (caps, dc))
            continue
        cref, cp = caps[0]
        cval = parse_number(nl.value(cref), "F")
        node = nl.other_end(cref, cp)[1]
        series_r = 0.0
        path = [cref]
        jack = [(r, p) for r, p in nl.mems(node) if nl.kind[r] == "jack"]
        if not jack:
            rs = [(r, o) for r, p, o in nl.two_pin_parts_on(node, ("res",)) if o is not None]
            hop = [(r, o) for r, o in rs if any(nl.kind[x] == "jack" for x, _ in nl.mems(o))]
            if hop:
                r, node = hop[0]
                series_r = parse_number(nl.value(r), "R") or 0.0
                path.append(r)
                jack = [(x, p) for x, p in nl.mems(node) if nl.kind[x] == "jack"]
        if not jack:
            status = FAIL
            d.append("MICIN -> %s does not reach a jack contact (through at most one series resistor)" % path)
            continue
        fc = 1 / (2 * math.pi * (series_r + 10e3) * cval) if cval else None
        d.append("MICIN <- %s%s <- mic node %s (jack %s): high-pass with the 10 kOhm input (p.7) %s" % (
            " <- ".join("%s %s" % (x, nl.value(x)) for x in path), "", node, jack,
            "%.1f Hz" % fc if fc else "?"))
        rails = {node, nl.gnd} | set(nl.power_nets())
        z, used = nl.resistance_to_rails(vbias, rails)
        to_mic = [r for r in used]
        if z is None or not any(node in {nl.net(r, p) for p in nl.pins_of(r)} for r in used):
            status = FAIL
            d.append("VBIAS does not reach the mic node %s through resistors: the electret gets no bias" % node)
            continue
        d.append("VBIAS (3 V) -> %s -> mic node: %s from VBIAS to the mic node / GND; filter %s"
                 % (to_mic, fmt_r(z), [(r, fmt_c(x)) for n in {nl.net(r, p) for r in used for p in nl.pins_of(r)}
                                       if n not in (vbias, node) for r, x in nl.cap_list(n)]))
        i_short = 3.0 / z * 1e3
        demo_r = 2.2e3 + 8.2e3
        d.append("mic contact shorted to GND (a 3-pole plug bridges ring 2 and sleeve): VBIAS sources %.2f mA "
                 "(demo board 2k2 + 8k2: %.2f mA)" % (i_short, 3.0 / demo_r * 1e3))
        if z < 0.5 * demo_r:
            status = WARN if status == PASS else status
            d.append("VBIAS has only 'a small driving capability' (p.7) and no current rating: this bias network "
                     "draws %.1fx the demo board's current, continuously whenever plain headphones are plugged in. "
                     "Phone (CTIA) headsets do want ~2.2 kOhm; verify VBIAS (3 V level, recording noise) on the bench "
                     "with both plug types" % (i_short / (3.0 / demo_r * 1e3)))
    rep.add("A06", title, status, "CM_audio", d)


# ---------------------------------------------------------------- TPA6132A2 amp --
def amp_net(nl, a, name):
    return ic_net(nl, a, TPA6132_PINS, name)


def jack_contacts(nl, j):
    """{contact: net} for a PJ-320D-4A, or None if a pin cannot be mapped to the drawing."""
    out = {}
    for p in nl.pins_of(j):
        key = p if p in JACK_CONTACT else (nl.pin_name(j, p) or "").upper()
        key = {"R1": "R1", "R2": "R2", "S": "S", "T": "T"}.get(key, key)
        if key not in JACK_CONTACT:
            return None
        out[JACK_CONTACT[key]] = nl.net(j, p)
    return out


def check_amp_power(nl, rep):
    title = "TPA6132A2: pinout, PGND / pad / SGND grounding, SGND = jack ground, VDD 2.3-5.5 V with >= 2.2 uF"
    amps = nl.fitted("hpamp")
    if not amps:
        rep.add("A11", title, SKIP, "TPA_pins", ["no TPA6132A2"])
        return
    status = PASS
    d = []
    for a in amps:
        mism = nl.name_mismatches(a, TPA6132_PINS, {"G0": ("GAIN0",), "G1": ("GAIN1",)})
        if mism:
            status = FAIL
            d += ["%s %s (p.3)" % (a, m) for m in mism]
        pg, sg, vdd = amp_net(nl, a, "PGND"), amp_net(nl, a, "SGND"), amp_net(nl, a, "VDD")
        eps = {p: nl.net(a, p) for p in nl.extra_pins(a, TPA6132_PINS)}
        d.append("%s: PGND(10) %s | SGND(15) %s | VDD(14) %s | pad %s" % (
            nl.desc(a), nl.label(pg), nl.label(sg), nl.label(vdd), {p: nl.label(n) for p, n in eps.items()}))
        if pg != nl.gnd:
            status = FAIL
            d.append("PGND must be ground (p.3)")
        bad_ep = {p: n for p, n in eps.items() if n not in (None, pg)}
        if bad_ep:
            status = FAIL
            d.append("thermal pad on %s: GND (same as PGND) or floating only, never a supply (p.18 10.1)" % bad_ep)
        jacks = nl.fitted("jack")
        jg = None
        if jacks:
            cts = jack_contacts(nl, jacks[0])
            jg = cts.get("ring2") if cts else None
        if sg is None or sg not in (nl.gnd,):
            status = FAIL
            d.append("SGND on %s: it is the amplifier reference and goes to the jack ground (p.3, p.18 10.3)" % nl.label(sg))
        elif jacks and jg != sg:
            status = FAIL
            d.append("SGND (%s) is not the jack's ground contact net (%s): p.18 10.3 'SGND must be connected to the "
                     "headphone ground connector pin'" % (nl.label(sg), nl.label(jg)))
        else:
            d.append("SGND on the same net as the jack ground contact (%s); route it to the jack pin (p.18 10.3)"
                     % (jacks[0] if jacks else "no jack in netlist"))
        vmax = nl.net_voltage_max(vdd)
        if vdd is None or vmax is None:
            status = FAIL
            d.append("VDD not on a known supply rail")
        elif vmax > 5.5 + 1e-6:
            status = FAIL
            d.append("VDD up to %.1f V > 5.5 V (p.4)" % vmax)
        else:
            d.append("VDD on %s (max %.1f V): inside 2.3-5.5 V, abs max 6 V (p.4)" % (nl.labels[vdd], vmax))
        caps = nl.cap_list(vdd)
        tot = sum(x for _, x in caps if x)
        big = [r for r, x in caps if x and x >= 2.2e-6 * 0.999]
        d.append("VDD capacitors %s = %s" % ([(r, fmt_c(x)) for r, x in caps], fmt_c(tot)))
        if not big:
            status = FAIL
            d.append("p.17 9.1: 'Place a 2.2 uF capacitor within 5 mm of the VDD pin' - none of >= 2.2 uF on VDD")
        else:
            d.append("%s >= 2.2 uF: keep it within 5 mm of pin 14 (layout, p.17)" % big)
    rep.add("A11", title, status, "TPA_pins", d)


def check_amp_cp(nl, rep):
    title = "TPA6132A2 charge pump: 1 uF CPP-CPN, HPVSS cap >= flying cap, HPVDD only to a 2.2 uF cap (never VDD)"
    amps = nl.fitted("hpamp")
    if not amps:
        rep.add("A12", title, SKIP, "TPA_cp", ["no TPA6132A2"])
        return
    status = PASS
    d = []
    for a in amps:
        hpvdd, hpvss = amp_net(nl, a, "HPVDD"), amp_net(nl, a, "HPVSS")
        cpp, cpn = amp_net(nl, a, "CPP"), amp_net(nl, a, "CPN")
        fly = nl.caps_between(cpp, cpn) if cpp and cpn else []
        d.append("%s: CPP(11) %s, CPN(9) %s, flying %s" % (a, nl.label(cpp), nl.label(cpn),
                                                           [(r, fmt_c(x)) for r, x in fly]))
        cf = None
        if len(fly) != 1 or cpp == cpn:
            status = FAIL
            d.append("exactly one capacitor between CPP and CPN (p.3)")
        else:
            cf = fly[0][1]
            if cf is None or not (0.47e-6 * 0.999 <= cf <= 2.2e-6 * 1.001):
                status = FAIL
                d.append("flying capacitor %s outside 0.47-2.2 uF (p.15 8.2.1.2.2)" % fmt_c(cf))
        for net, nm in ((cpp, "CPP"), (cpn, "CPN")):
            extra = [(r, p) for r, p in nl.mems(net) if r != a and r not in [x for x, _ in fly]]
            if extra:
                status = FAIL
                d.append("%s also connects %s" % (nm, extra))
        vss_caps = nl.cap_list(hpvss)
        cv = sum(x for _, x in vss_caps if x)
        extra = [(r, p) for r, p in nl.non_cap_members(hpvss, exclude=(a,))]
        d.append("HPVSS(8) %s: %s" % (nl.label(hpvss), [(r, fmt_c(x)) for r, x in vss_caps]))
        if hpvss is None or not vss_caps or extra or hpvss in nl.power_nets():
            status = FAIL
            d.append("HPVSS needs its capacitor to GND and nothing else (p.3) - extra %s" % extra)
        elif cf and cv < cf * 0.999:
            status = FAIL
            d.append("HPVSS capacitor %s smaller than the flying capacitor %s (p.15: 'at least equal')" % (fmt_c(cv), fmt_c(cf)))
        elif cv < 0.47e-6 * 0.999:
            status = FAIL
            d.append("HPVSS capacitor %s below 0.47 uF (p.15)" % fmt_c(cv))
        vdd_caps = nl.cap_list(hpvdd)
        extra = nl.non_cap_members(hpvdd, exclude=(a,))
        d.append("HPVDD(12) %s: %s" % (nl.label(hpvdd), [(r, fmt_c(x)) for r, x in vdd_caps]))
        if hpvdd is None or hpvdd in nl.power_nets() or extra:
            status = FAIL
            d.append("HPVDD is generated inside: 'DO NOT connect HPVDD directly to VDD or an external supply' (p.17 "
                     "WARNING, abs max 1.9 V p.4) - here %s %s" % (nl.label(hpvdd), extra))
        elif not vdd_caps:
            status = FAIL
            d.append("HPVDD needs its 2.2 uF capacitor (p.3, p.17)")
        else:
            ch = sum(x for _, x in vdd_caps if x)
            if not (1.0e-6 <= ch <= 4.7e-6):
                status = WARN if status == PASS else status
                d.append("HPVDD capacitor %s, datasheet asks for 2.2 uF" % fmt_c(ch))
            else:
                d.append("HPVDD only to %s (2.2 uF asked, p.17), HPVSS %s >= flying %s (p.15)" % (fmt_c(ch), fmt_c(cv), fmt_c(cf)))
    rep.add("A12", title, status, "TPA_cp", d)


def amp_gain_states(nl, a):
    """[(state label, G0 level, G1 level, notes)] for every jumper combination; level 0/1/None (undefined)."""
    vdd = amp_net(nl, a, "VDD")
    vdd_max = nl.net_voltage_max(vdd) or 5.5
    out_notes = []

    def analyse(name):
        net = amp_net(nl, a, name)
        if net is None:
            return [("open", None, "%s floating" % name)]
        if net == nl.gnd:
            return [("", 0, "%s on GND" % name)]
        if net in nl.power_nets():
            v = nl.net_voltage_max(net)
            return [("", 1 if v and v >= 1.3 else None, "%s on %s" % (name, nl.labels[net]))]
        ups = [(r, o, parse_number(nl.value(r), "R")) for r, p, o in nl.two_pin_parts_on(net, ("res",))
               if o in nl.power_nets() and o != nl.gnd]
        downs = [(r, parse_number(nl.value(r), "R")) for r, p, o in nl.two_pin_parts_on(net, ("res",)) if o == nl.gnd]
        jmp = [(r, o) for r, p, o in nl.two_pin_parts_on(net, ("jumper",))]
        gp = [p for r, p in nl.mems(net) if r == nl.mcu]
        states = []
        if gp:
            states.append(("firmware", None, "%s driven by %s pin %s (firmware sets the gain)" % (name, nl.mcu_word, gp)))
            return states
        base = None
        txt = ""
        if ups and not downs:
            r, o, v = ups[0]
            vh = (nl.net_voltage_nom(o) or 0) - (v or 0) * 1e-6
            base = 1 if vh >= 1.3 else None
            txt = "%s pulled up to %s by %s %s: >= %.2f V with the 1 uA input current (VIH 1.3 V)" % (
                name, nl.labels[o], r, fmt_r(v), vh)
            if o != vdd and (nl.net_voltage_max(o) or 0) > 0.3:
                out_notes.append("%s pull-up rail %s differs from the amplifier VDD %s: with VDD off the pin exceeds "
                                 "VDD + 0.3 V (abs max p.4)" % (name, nl.labels[o], nl.label(vdd)))
        elif downs and not ups:
            base = 0
            txt = "%s pulled down by %s" % (name, downs[0][0])
        elif ups and downs:
            r, o, v = ups[0]
            rd = downs[0][1]
            vh = (nl.net_voltage_nom(o) or 0) * rd / (rd + v) if v and rd else 0
            base = 1 if vh >= 1.3 else (0 if vh <= 0.5 else None)
            txt = "%s divider %s/%s -> %.2f V" % (name, fmt_r(v), fmt_r(rd), vh)
        else:
            txt = "%s on %s without a defined level" % (name, nl.label(net))
        states.append(("", base, txt))
        for j, o in jmp:
            if o == nl.gnd:
                states.append(("%s closed" % j, 0, "%s closed: %s shorted to GND" % (j, name)))
            elif o in nl.power_nets() and (nl.net_voltage_max(o) or 0) >= 1.3:
                states.append(("%s closed" % j, 1, "%s closed: %s to %s" % (j, name, nl.labels[o])))
        return states

    g0, g1 = analyse("G0"), analyse("G1")
    combos = []
    for l0, v0, t0 in g0:
        for l1, v1, t1 in g1:
            label = " + ".join(x for x in (l0, l1) if x) or "default (jumpers open)"
            combos.append((label, v0, v1, [t0, t1]))
    return combos, out_notes


def check_amp_inputs(nl, rep):
    title = "TPA6132A2 single-ended inputs: INL+/INR+ grounded, INL-/INR- through series capacitors, low-frequency corner"
    amps = nl.fitted("hpamp")
    if not amps:
        rep.add("A13", title, SKIP, "TPA_in", ["no TPA6132A2"])
        return
    status = PASS
    d = []
    for a in amps:
        combos, _ = amp_gain_states(nl, a)
        gains = sorted({TPA_GAIN.get((v0, v1)) for _, v0, v1, _ in combos if v0 is not None and v1 is not None} - {None},
                       key=float)
        for plus, minus in (("INL+", "INL-"), ("INR+", "INR-")):
            pn, mn = amp_net(nl, a, plus), amp_net(nl, a, minus)
            if pn == nl.gnd:
                d.append("%s on GND: single-ended input (p.1, p.3)" % plus)
            elif pn is None:
                status = FAIL
                d.append("%s floating: ground it for single-ended use (p.3)" % plus)
                continue
            else:
                d.append("%s on %s: differential use (needs a matched source on %s)" % (plus, nl.label(pn), minus))
            if mn is None:
                status = FAIL
                d.append("%s unconnected" % minus)
                continue
            mem = nl.mems(mn, exclude=a)
            caps = [(r, p) for r, p in mem if nl.kind[r] == "cap" and nl.other_end(r, p)[1] not in (nl.gnd, None)]
            dc = [(r, p) for r, p in mem if (r, p) not in caps]
            if dc or len(caps) != 1:
                status = FAIL
                d.append("%s must be fed through one series capacitor (Fig.27 p.16, p.15 8.2.1.2.1: the input caps block "
                         "the source's DC); found caps %s, other %s" % (minus, caps, dc))
                continue
            cref, cp = caps[0]
            cval = parse_number(nl.value(cref), "F")
            src = nl.other_end(cref, cp)[1]
            fcs = ["%s dB: RIN %s -> %.1f Hz" % (g, fmt_r(TPA_RIN[g]), 1 / (2 * math.pi * TPA_RIN[g] * cval))
                   for g in gains] if cval else []
            d.append("%s <- %s %s <- %s ; corner 1/(2 pi RIN C): %s" % (minus, cref, nl.value(cref), nl.label(src), fcs))
            if cval and any(1 / (2 * math.pi * TPA_RIN[g] * cval) > 20.0 for g in gains):
                status = WARN if status == PASS else status
                d.append("  corner above 20 Hz at some gain (TI's design example targets 20 Hz, p.15)")
        d.append("input capacitors also keep the turn-on pop inaudible (p.12 7.3.2)")
    rep.add("A13", title, status, "TPA_in", d)


def check_amp_ctl(nl, rep):
    title = ("TPA6132A2 EN/G0/G1: defined levels (VIH >= 1.3 V, VIL <= 0.6 V, <= VDD + 0.3 V), gain per jumper state, "
             "EN delayed after the audio supply and dropped before it")
    amps = nl.fitted("hpamp")
    if not amps:
        rep.add("A14", title, SKIP, "TPA_ctl", ["no TPA6132A2"])
        return
    status = PASS
    d = []
    rail_en = False
    for a in amps:
        combos, notes = amp_gain_states(nl, a)
        for label, v0, v1, txt in combos:
            g = TPA_GAIN.get((v0, v1))
            if g is None:
                if "firmware" in label:
                    d.append("%s: %s" % (label, "; ".join(txt)))
                    continue
                status = FAIL
                d.append("%s: G0/G1 level undefined (%s) - must be <= 0.5 V or >= 1.3 V (p.13)" % (label, "; ".join(txt)))
            else:
                d.append("%s: G0=%d G1=%d -> gain %s dB (p.13 7.4.1) [%s]" % (label, v0, v1, g, "; ".join(txt)))
        for n in notes:
            status = WARN if status == PASS else status
            d.append(n)
        vdd = amp_net(nl, a, "VDD")
        en = amp_net(nl, a, "EN")
        if en is None:
            status = FAIL
            d.append("EN floating: connect to logic low/high (p.3)")
            continue
        if en == vdd:
            status = WARN if status == PASS else status
            d.append("EN tied to VDD: on as soon as the rail is up, no sequencing against the audio source (p.12)")
            continue
        if en == nl.gnd:
            status = FAIL
            d.append("EN tied to GND: amplifier permanently off")
            continue
        mem = nl.mems(en, exclude=a)
        gp = [p for r, p in mem if r == nl.mcu]
        rs = [(r, o, parse_number(nl.value(r), "R")) for r, p, o in nl.two_pin_parts_on(en, ("res",))]
        cs_ = [(r, parse_number(nl.value(r), "F")) for r, p, o in nl.two_pin_parts_on(en, ("cap",)) if o == nl.gnd]
        ds = [r for r, p in mem if nl.kind[r] in ("schottky", "mdiode")]
        if gp:
            status = WARN if status == PASS else status
            d.append("EN driven straight by %s pin %s: firmware alone must keep it low until the source has "
                     "settled and drop it first on power-down (p.12)" % (nl.mcu_word, gp))
            continue
        ctrl = [(r, o, v) for r, o, v in rs if o not in (nl.gnd, None)]
        if len(ctrl) != 1:
            status = WARN if status == PASS else status
            d.append("EN on %s with %s: cannot identify the control signal" % (nl.label(en), mem))
            continue
        rref, cnet, rv = ctrl[0]
        cgp = [p for r, p in nl.mems(cnet) if r == nl.mcu]
        sw = [r for r, p in nl.mems(cnet) if nl.kind[r] == "loadsw" and p == "3"]
        ctot = sum(x for _, x in cs_ if x)
        if cnet is not None and cnet in (nl.vbus, nl.vaud, nl.vdd):
            # wired variant: EN follows a supply rail (VBUS) through an RC, no firmware involved
            st, lines = amp_en_from_rail(nl, a, rref, cnet, rv, cs_, ds, sw)
            d += lines
            rail_en = True
            status = FAIL if FAIL in (status, st) else (WARN if WARN in (status, st) else status)
            continue
        if not cgp:
            status = WARN if status == PASS else status
            d.append("EN control net %s is not driven by a %s GPIO" % (nl.label(cnet), nl.mcu_word))
            continue
        vgpio = V_VDD
        v_inf = vgpio - (rv or 0) * 1e-6         # 1 uA EN input current (p.5)
        d.append("EN <- %s %s <- %s (%s pin %s%s); %s to GND = %s" % (
            rref, fmt_r(rv), nl.label(cnet), nl.mcu_word, cgp, ", also the %s ON pin" % sw if sw else "",
            [(r, fmt_c(x)) for r, x in cs_], fmt_c(ctot)))
        if v_inf < 1.3:
            status = FAIL
            d.append("steady EN level %.2f V < VIH 1.3 V (1 uA input current through %s)" % (v_inf, fmt_r(rv)))
        else:
            d.append("steady EN level >= %.2f V with the 1 uA input current: above VIH 1.3 V (p.4)" % v_inf)
        tau = (rv or 0) * ctot
        if tau > 0:
            t_lo = -tau * math.log(1 - 0.6 / vgpio)
            t_hi = -tau * math.log(1 - 1.3 / v_inf) if v_inf > 1.3 else float("inf")
            d.append("turn-on: tau = %s x %s = %.0f ms -> EN passes the 0.6-1.3 V threshold %.0f-%.0f ms after the "
                     "control rises; the load switch output is up after ~2 ms (TPS22919 p.5): the source gets "
                     ">= %.0f ms to settle (p.12; the CM108B output settling time is not specified - check for a "
                     "turn-on pop)" % (fmt_r(rv), fmt_c(ctot), tau * 1e3, t_lo * 1e3, t_hi * 1e3, t_lo * 1e3))
        if not ds:
            if sw and tau > 0.01:
                status = FAIL
                d.append("turn-off: no discharge diode, EN falls with tau %.0f ms while the same control switches the "
                         "audio supply off in microseconds - the amplifier would stay enabled after its source died "
                         "(p.12: deactivate the TPA6132A2 before the audio source)" % (tau * 1e3))
            continue
        dref = ds[0]
        da, dk, _ = nl.diode_ak(dref)
        if nl.net(dref, da) == en and nl.net(dref, dk) == cnet:
            d.append("turn-off: %s (anode EN, cathode %s) dumps the EN capacitor into the GPIO when it goes low"
                     % (dref, nl.label(cnet)))
        elif nl.net(dref, dk) == en and nl.net(dref, da) == cnet:
            status = FAIL
            d.append("%s reversed (anode on the control, cathode on EN): EN jumps high together with the supply (no "
                     "turn-on delay) and decays slowly on turn-off - both against p.12" % dref)
            continue
        else:
            status = WARN if status == PASS else status
            d.append("%s on EN goes to %s / %s" % (dref, nl.label(nl.net(dref, da)), nl.label(nl.net(dref, dk))))
            continue
        if sw:
            s = sw[0]
            vout = nl.net(s, "6")
            qod = nl.net(s, "5")
            cl = rail_capacitance(nl, vout)
            if qod == vout:
                rdis = TPS_RQOD
            else:
                rq = nl.resistors_between(qod, vout) if qod else []
                rdis = TPS_RQOD + rq[0][1] if rq and rq[0][1] else None
            # what discharges the rail once the switch is open: the loads themselves (CM108B 37.25 mA typ,
            # CM108B p.20; TPA6132A2 2.1 mA typ, TPA p.5) plus the QOD path (V / RDIS)
            on_rail = {vout} | {o for _, _, o in nl.two_pin_parts_on(vout, ("ind",)) if o}
            codecs = sorted({r for n in on_rail for r, p in nl.mems(n) if nl.kind[r] == "codec"})
            amps_r = sorted({r for n in on_rail for r, p in nl.mems(n) if nl.kind[r] == "hpamp"})
            i_load = 37.25e-3 * len(codecs) + 2.1e-3 * len(amps_r)
            i_qod = V_VBUS_NOM / rdis if rdis else 0.0
            if codecs and cl > 0:
                t_rail = cl * (V_VBUS_NOM - 4.5) / (i_load + i_qod)
                t_qod_only = rdis * cl * math.log(V_VBUS_NOM / 4.5) if rdis else float("inf")
                # EN discharge through the diode into the GPIO: output low ~ R = 0.4 V / IOL(min) (PS p.156:
                # standard drive 1 mA, high drive 6 mA); Schottky drop ~0.2 V at these currents
                vfd = 0.2
                ln_en = math.log((vgpio - vfd) / (0.6 - vfd))
                t_en_sd = 0.4 / 1e-3 * ctot * ln_en
                t_en_hd = 0.4 / 6e-3 * ctot * ln_en
                d.append("power-down order: ~6 us after the control falls the switch is open (TPS22919 p.5); the %s on "
                         "the rail then feeds %s (37 mA typ, CM108B p.20) + %s (2.1 mA, TPA p.5) + QOD (%s: %.1f mA), so "
                         "it drops below the CM108B's 4.5 V minimum in ~%.2f ms (QOD alone, without the loads: %s); "
                         "EN falls below VIL 0.6 V after ~%.2f ms with a standard-drive GPIO (IOL >= 1 mA at 0.4 V, "
                         "PS p.156) or ~%.2f ms with high drive (>= 6 mA)" % (
                             fmt_c(cl), codecs, amps_r, fmt_r(rdis) if rdis else "open", i_qod * 1e3, t_rail * 1e3,
                             "%.2f ms" % (t_qod_only * 1e3) if rdis else "never", t_en_sd * 1e3, t_en_hd * 1e3))
                if t_en_sd > t_rail:
                    status = WARN if status == PASS else status
                    why = ("the codec's own current, not the QOD resistor, sets the rail's fall"
                           if i_load > i_qod else "the QOD discharge empties the rail")
                    fix = ("configure the GPIO as high drive (H0H1) - EN then falls in ~%.2f ms, before the rail - or "
                           "drive EN from its own GPIO" % (t_en_hd * 1e3)) if t_en_hd < t_rail else \
                          "even high drive is not fast enough: drive EN from its own GPIO and drop it first"
                    d.append("  with standard drive the amplifier is disabled AFTER its source (the CM108B) has lost "
                             "power: p.12 asks for the opposite order. Here %s; %s. Bench-check for a switch-off pop"
                             % (why, fix))
        if vdd != cnet and vdd in nl.power_nets():
            status = WARN if status == PASS else status
            d.append("EN high (up to %.1f V from the GPIO) while the amplifier VDD (%s) is off - USB unplugged with "
                     "the sound card on, or during the rail's fall - exceeds VDD + 0.3 V (abs max p.4); %s limits the "
                     "steady current to %.1f uA but %s dumps its charge into the EN clamp: firmware must drop %s as "
                     "soon as VBUS goes away" % (vgpio, nl.labels.get(vdd, vdd), rref, vgpio / (rv or 1) * 1e6,
                                                 fmt_c(ctot), nl.label(cnet)))
    rep.add("A14", title, status, SRC["TPA_ctl"] + "; " + SRC["TPA_ctl_rail"] if rail_en else "TPA_ctl", d)


def amp_en_from_rail(nl, a, rref, cnet, rv, cs_, ds, sw):
    """A14 for an amplifier EN that follows a supply rail through an RC (wired board: VBUS - 1M - EN, 470 nF to GND,
    Schottky EN -> VBUS).  Returns (status, lines)."""
    st = PASS
    d = []
    ctot = sum(x for _, x in cs_ if x)
    en = amp_net(nl, a, "EN")
    vdd = amp_net(nl, a, "VDD")
    vnom = nl.net_voltage_nom(cnet) or V_VBUS_NOM
    vmin = 4.75 if cnet in (nl.vbus, nl.vaud) else vnom
    v_inf = vmin - (rv or 0) * 1e-6                       # 1 uA EN input current (p.5)
    # does the amplifier supply follow the same rail? (directly, or through a load switch that the rail keeps on)
    # (a closed TPS22919 has no reverse blocking: its output follows the input down, p.12-14)
    follow_sw = [s for s in nl.fitted("loadsw") if nl.net(s, "1") == cnet and nl.net(s, "6") == vdd]
    follows = vdd == cnet or bool(follow_sw)
    on_rail_sw = [s for s in follow_sw if nl.net(s, "3") == cnet]
    d.append("EN <- %s %s <- %s (the supply rail itself, no firmware%s); %s to GND = %s" % (
        rref, fmt_r(rv), nl.label(cnet), ", also the %s ON pin" % sw if sw else "", [(r, fmt_c(x)) for r, x in cs_],
        fmt_c(ctot)))
    if v_inf < 1.3:
        st = FAIL
        d.append("steady EN %.2f V < VIH 1.3 V (rail at %.2f V, 1 uA through %s)" % (v_inf, vmin, fmt_r(rv)))
    else:
        d.append("steady EN >= %.2f V with the rail at its %.2f V minimum and the 1 uA input current: above VIH 1.3 V "
                 "(p.4-5)" % (v_inf, vmin))
    tau = (rv or 0) * ctot
    if tau > 0:
        t_lo = -tau * math.log(1 - 0.6 / vnom)
        t_hi = -tau * math.log(1 - 1.3 / v_inf) if v_inf > 1.3 else float("inf")
        d.append("turn-on: tau = %s x %s = %.0f ms -> EN passes 0.6-1.3 V %.0f-%.0f ms after the cable is plugged; the "
                 "switched rail is up after ~2 ms (TPS22919 p.5): the amplifier starts after its supply and the codec "
                 "(p.12 order kept; the CM108B output settling time is not specified - listen for a plug-in pop)" % (
                     fmt_r(rv), fmt_c(ctot), tau * 1e3, t_lo * 1e3, t_hi * 1e3))
        if t_lo < 5e-3:
            st = WARN if st == PASS else st
            d.append("EN rises almost with the rail: no real delay after the source is powered (p.12)")
    else:
        st = WARN if st == PASS else st
        d.append("no capacitor on EN: the amplifier turns on together with its source (p.12 asks for after)")
    dio_ok = False
    if not ds:
        if tau > 0.01:
            st = WARN if st == PASS else st
            d.append("no discharge diode: after an unplug EN keeps its charge for ~%.0f ms, so a quick re-plug starts "
                     "the amplifier without delay and EN can stay above the falling VDD + 0.3 V (p.4)" % (tau * 1e3))
    else:
        dref = ds[0]
        da, dk, _ = nl.diode_ak(dref)
        if nl.net(dref, da) == en and nl.net(dref, dk) == cnet:
            dio_ok = True
            d.append("turn-off: %s (anode EN, cathode %s) drags EN down with the rail, one diode drop above it, and "
                     "empties %s at every unplug: the delay starts from 0 V again at the next plug-in; reverse voltage "
                     "<= ~1 V << VRRM 40 V (C8598.pdf p.1)" % (dref, nl.label(cnet), fmt_c(ctot)))
        elif nl.net(dref, dk) == en and nl.net(dref, da) == cnet:
            st = FAIL
            d.append("%s reversed (anode on %s, cathode on EN): EN jumps up with the rail - no turn-on delay"
                     % (dref, nl.label(cnet)))
        else:
            st = WARN if st == PASS else st
            d.append("%s on EN goes to %s / %s" % (dref, nl.label(nl.net(dref, da)), nl.label(nl.net(dref, dk))))
    if follows:
        d.append("EN vs VDD + 0.3 V (abs max p.4): VDD %s is the same rail%s; steady EN <= the rail, at power-up EN "
                 "lags far behind VDD, at power-down EN sits one Schottky drop above the falling rail (B5819W: only "
                 "VF 0.6 V at 1 A is specified, p.1; at the milliamps that discharge %s it is a few tenths of a volt) - at the "
                 "0.3 V edge for a moment, with at most %.1f uJ left in %s once EN is below VIH" % (
                     nl.label(vdd), " through %s (ON = %s, so it stays closed while the rail falls)" % (
                         on_rail_sw, nl.label(cnet)) if on_rail_sw else " through %s while it is on" % follow_sw
                     if follow_sw else "", fmt_c(ctot), 0.5 * ctot * 1.3 ** 2 * 1e6,
                     fmt_c(ctot)) if dio_ok else "EN vs VDD: see the turn-off line")
        on_rail = {vdd} | {o for _, _, o in nl.two_pin_parts_on(vdd, ("ind",)) if o}
        codecs = sorted({r for n in on_rail for r, p in nl.mems(n) if nl.kind[r] == "codec"})
        if codecs:
            c_rail = nl.cap_total(cnet) + (rail_capacitance(nl, vdd) if vdd != cnet else 0.0)
            i_load = 37.25e-3 * len(codecs) + 2.1e-3
            t_win = c_rail * (4.5 - 2.3) / i_load
            st = WARN if st == PASS else st
            d.append("power-down order NOT kept (p.12: 'deactivate the TPA6132A2 before deactivating the audio input "
                     "source'): on unplug EN stays above VIH 1.3 V until the rail is down to ~1 V, while %s drops "
                     "below its 4.5 V minimum (CM108B p.20) as soon as the rail does. From 4.5 V to the amplifier's own "
                     "2.3 V minimum (p.4) the amplifier is enabled and powered while its source browns out - ~%.1f ms "
                     "with %s on the rail and only the codec + amplifier draining it (less with the hub and the 3.3 V "
                     "regulator also loading VBUS). The TPA6132A2 lists no undervoltage lockout. Firmware cannot help: "
                     "EN is not under its control and nothing senses VBUS (without VBUS detection the RP2040 cannot "
                     "tell an unplug from a suspend, RP2040 datasheet 4.1.2.8.4). A fix needs EN to fall while VBUS is "
                     "still above 4.5 V (e.g. a ~4.6 V VBUS supervisor driving EN); otherwise bench-check for a pop when the "
                     "cable is pulled with headphones in" % (codecs, t_win * 1e3, fmt_c(c_rail)))
    return st, d


# ---------------------------------------------------------------- TPS22919 switch --
def rail_capacitance(nl, net):
    """Capacitance to GND on `net` plus behind ferrite beads hanging off it (first level)."""
    if net is None:
        return 0.0
    tot = nl.cap_total(net)
    for ref, pin, onet in nl.two_pin_parts_on(net, ("ind",)):
        if onet is not None:
            tot += nl.cap_total(onet)
    return tot


def check_loadsw_power(nl, rep):
    title = "TPS22919: pinout, IN on VBUS (1.6-5.5 V), GND, NC open, 1 uF input capacitor, load and inrush"
    sws = nl.fitted("loadsw")
    if not sws:
        rep.add("S01", title, SKIP, "TPS_pins", ["no TPS22919"])
        return
    status = PASS
    d = []
    for s in sws:
        mism = nl.name_mismatches(s, TPS22919_PINS, {"VOUT": ("OUT",), "NC": ("N/C",)})
        if mism:
            status = FAIL
            d += ["%s %s (p.3)" % (s, m) for m in mism]
        vin, g, nc, vout = nl.net(s, "1"), nl.net(s, "2"), nl.net(s, "4"), nl.net(s, "6")
        d.append("%s: IN(1) %s | GND(2) %s | ON(3) %s | NC(4) %s | QOD(5) %s | VOUT(6) %s" % (
            nl.desc(s), nl.label(vin), nl.label(g), nl.label(nl.net(s, "3")), nl.label(nc), nl.label(nl.net(s, "5")),
            nl.label(vout)))
        if g != nl.gnd:
            status = FAIL
            d.append("GND pin not on ground")
        vmax = nl.net_voltage_max(vin)
        if vin is None or vmax is None:
            status = FAIL
            d.append("IN must be on a supply rail")
        elif vmax > 5.5 + 1e-6:
            status = FAIL
            d.append("IN up to %.1f V > 5.5 V (p.4)" % vmax)
        else:
            d.append("IN on %s (<= %.1f V): inside 1.6-5.5 V, abs max 6 V (p.4)" % (nl.labels[vin], vmax))
        if nc is not None and nl.mems(nc, exclude=s):
            status = FAIL
            d.append("NC connected to %s: p.3 'No connect pin, leave floating'" % nl.label(nc))
        if vout is None or vout == vin or vout in (nl.gnd,):
            status = FAIL
            d.append("VOUT must be a separate switched net")
            continue
        cin = nl.cap_total(vin)
        if cin < 1e-6 * 0.999:
            status = WARN if status == PASS else status
            d.append("input capacitance %s < 1 uF (p.17 10)" % fmt_c(cin))
        else:
            d.append("input capacitance %s >= 1 uF (p.17 10)" % fmt_c(cin))
        cl = rail_capacitance(nl, vout)
        loads = sorted({r for r, p in nl.mems(vout) if nl.kind[r] in ("codec", "hpamp")} |
                       {r for ref, pin, onet in nl.two_pin_parts_on(vout, ("ind",)) for r, p in nl.mems(onet)
                        if nl.kind[r] in ("codec", "hpamp")})
        d.append("load capacitance %s (incl. behind beads); turn-on slew 3.2 mV/us at 5 V (p.5) -> inrush ~%.0f mA; "
                 "loads %s (CM108B 37 mA typ, TPA6132A2 2.2 mA + headphone current) << 1.5 A (p.4)"
                 % (fmt_c(cl), TPS_SR * cl * 1e3, loads))
    rep.add("S01", title, status, "TPS_pins", d)


def check_loadsw_on(nl, rep):
    title = "TPS22919 ON (sound-card enable): module GPIO with a pull-down to GND, never floating"
    sws = nl.fitted("loadsw")
    if not sws:
        rep.add("S02", title, SKIP, "TPS_on", ["no TPS22919"])
        return
    status = PASS
    d = []
    tied_in = False
    for s in sws:
        on = nl.net(s, "3")
        d.append("%s ON(3) -> %s" % (s, nl.label(on)))
        if on is None:
            status = FAIL
            d.append("ON floating: 'Do not leave floating' (p.3)")
            continue
        if on == nl.gnd:
            status = WARN if status == PASS else status
            d.append("ON tied to GND: switch permanently off")
            continue
        if on == nl.net(s, "1") and on in nl.power_nets():
            # wired variant: ON tied to the switch's own IN (VBUS) - on whenever the cable is in
            tied_in = True
            vmax = nl.net_voltage_max(on) or V_VBUS_MAX
            vout = nl.net(s, "6")
            cl = rail_capacitance(nl, vout)
            d.append("ON tied to its own IN (%s): on whenever %s is present; %.1f V max <= VIH range 1-5.5 V and abs "
                     "max 6 V (p.4), never floating (p.3); the smart pull-down plays no part (p.13 8.3.1), so no "
                     "pull-down resistor is needed" % (nl.labels[on], nl.labels[on], vmax))
            d.append("role: soft start only - %s on %s charged at 3.2 mV/us (~%.0f mA, tON ~2 ms at 5 V, p.5) "
                     "after the cable has made contact, instead of being hard-wired to %s (%s directly on it)" % (
                         fmt_c(cl), nl.label(vout), TPS_SR * cl * 1e3, nl.labels[on], fmt_c(nl.cap_total(on))))
            d.append("on unplug the switch stays closed until %s falls below VIH (~1 V): with no reverse-current "
                     "blocking specified (p.12-14) the %s back-feed %s and everything discharges together - harmless; "
                     "the QOD path (S03) only acts once ON < VIL 0.35 V, i.e. at the very end" % (
                         nl.labels[on], fmt_c(cl), nl.labels[on]))
            others = [(x, p) for x, p in nl.mems(on) if nl.kind[x] in ("res",) and
                      nl.other_end(x, p)[1] not in nl.power_nets()]
            if others:
                d.append("the same rail also drives %s (amplifier EN network, judged in A14: the unplug order is the "
                         "real risk there, not the switch)" % sorted({x for x, _ in others}))
            continue
        if on in nl.power_nets():
            status = WARN if status == PASS else status
            d.append("ON tied to %s: switch always on (not switchable)" % nl.labels[on])
            continue
        gp = [int(p) for r, p in nl.mems(on) if r == nl.mcu]
        pulls = nl.resistors_between(on, nl.gnd)
        if not gp:
            status = WARN if status == PASS else status
            d.append("ON not driven by a %s GPIO: %s" % (nl.mcu_word, nl.mems(on, exclude=s)))
        else:
            pin = gp[0]
            d.append("driven by %s pin %d %s: 3.3 V high >= VIH 1 V, abs max 6 V (p.4)" % (nl.mcu_word, pin,
                                                                                         nl.mcu_pin_label(pin)))
            if nl.module and pin in (E73_P1_04, E73_P1_10):
                status = WARN if status == PASS else status
                d.append("pin %s is a bootloader LED pin (board.h): the bootloader toggles it and would switch the "
                         "audio supply" % E73_PINS[pin][0])
        if not pulls:
            status = FAIL
            d.append("no pull-down to GND: the GPIO is high-Z from reset until firmware runs; the TPS22919's own "
                     "530 kOhm smart pull-down is disconnected once ON has been driven high (p.13 Table 1) and does "
                     "not exist without VIN - after an MCU reset ON would float (p.3: 'do not leave floating')")
        else:
            r, v = pulls[0]
            ileak = 100e-9
            d.append("pull-down %s %s: ON = %.0f mV with 100 nA leakage (VIL 0.35 V, p.4); %.0f uA from the GPIO "
                     "when high" % (r, fmt_r(v), (v or 0) * ileak * 1e3, V_VDD / (v or 1) * 1e6))
            if v and v * ileak > 0.35:
                status = FAIL
            others = [(x, p) for x, p in nl.mems(on) if x not in (s, nl.mcu, r)]
            if others:
                d.append("the enable also feeds %s (amplifier EN network, A14)" % sorted({x for x, _ in others}))
                dio = [x for x, p in others if nl.kind[x] in ("schottky", "mdiode")]
                caps_en = []
                for x in dio:
                    a_, k_, _ = nl.diode_ak(x)
                    if nl.net(x, k_) == on:
                        caps_en = nl.cap_list(nl.net(x, a_))
                if caps_en and v:
                    c = sum(cc for _, cc in caps_en if cc)
                    d.append("if the GPIO goes high-Z while on (MCU reset), %s back-feeds ON from the EN capacitor %s: "
                             "the switch opens only ~%.0f ms later (%s x %s)" % (dio, fmt_c(c), v * c * 1e3,
                                                                                    fmt_r(v), fmt_c(c)))
    if tied_in:
        title = "TPS22919 ON (sound-card enable): a GPIO with a pull-down, or tied to its own IN (always on: soft start " \
                "only); never floating"
    rep.add("S02", title, status, "TPS_on_rail" if tied_in else "TPS_on", d)


def check_loadsw_qod(nl, rep):
    title = "TPS22919 QOD: tied to VOUT (24 Ohm discharge), through a resistor to VOUT, or open"
    sws = nl.fitted("loadsw")
    if not sws:
        rep.add("S03", title, SKIP, "TPS_qod", ["no TPS22919"])
        return
    status = PASS
    d = []
    for s in sws:
        qod, vout = nl.net(s, "5"), nl.net(s, "6")
        cl = rail_capacitance(nl, vout)
        if qod is None:
            d.append("%s QOD open: no output discharge, VOUT floats when off (Table 2, p.14)" % s)
            continue
        if qod == vout:
            rdis = TPS_RQOD
            d.append("%s QOD tied to VOUT: discharge through the internal %g Ohm (p.3 option 2, p.5)" % (s, TPS_RQOD))
        else:
            rq = nl.resistors_between(qod, vout)
            others = [(r, p) for r, p in nl.mems(qod) if r != s and r not in [x for x, _ in rq]]
            if len(rq) == 1 and rq[0][1] and not others:
                rdis = TPS_RQOD + rq[0][1]
                d.append("%s QOD through %s %s to VOUT: RDIS = %s (p.13 eq.1)" % (s, rq[0][0], fmt_r(rq[0][1]), fmt_r(rdis)))
            else:
                status = FAIL
                d.append("%s QOD on %s (%s): only VOUT, a resistor to VOUT, or open are allowed (p.3)"
                         % (s, nl.label(qod), nl.mems(qod, exclude=s)))
                continue
        tf = 2.2 * rdis * cl
        d.append("tFALL ~ 2.2 x %s x %s = %.2f ms without load (p.13 eq.2); peak discharge current %.0f mA" % (
            fmt_r(rdis), fmt_c(cl), tf * 1e3, V_VBUS_MAX / rdis * 1e3))
    rep.add("S03", title, status, "TPS_qod", d)


# ---------------------------------------------------------------- 3.5 mm jack --
def check_jack(nl, rep):
    title = ("PJ-320D-4A contacts (from the drawing) wired as a CTIA headset jack: tip = left, ring 1 = right, "
             "ring 2 = ground, sleeve = microphone")
    jacks = nl.fitted("jack")
    if not jacks:
        rep.add("J01", title, SKIP, "JACK", ["no 3.5 mm jack"])
        return
    status = PASS
    d = []
    amps = nl.fitted("hpamp")
    codecs = nl.fitted("codec")
    for j in jacks:
        cts = jack_contacts(nl, j)
        if cts is None:
            status = FAIL
            d.append("%s pins %s cannot be mapped to the drawing's 1-4 / S-T-R1-R2" % (j, nl.pins_of(j)))
            continue
        d.append("%s: %s" % (nl.desc(j), ", ".join("%s(%s) -> %s" % (k, JACK_CTIA[k], nl.label(v))
                                                       for k, v in sorted(cts.items()))))
        if set(cts) != {"tip", "ring1", "ring2", "sleeve"}:
            status = FAIL
            d.append("a 4-pole jack needs tip, ring 1, ring 2 and sleeve")
            continue

        def reaches(net, target_kind, names):
            hits = []
            for n, via in nl.through_series(net, kinds=("ind", "res"), max_ohm=100, depth=2,
                                            no_enter=set(nl.power_nets())).items():
                for r, p in nl.mems(n):
                    if nl.kind[r] == target_kind:
                        nm = (TPA6132_PINS if target_kind == "hpamp" else CM108B_PINS).get(p)
                        if nm in names:
                            hits.append((r, nm, via))
            return hits

        for contact, want in (("tip", "OUTL"), ("ring1", "OUTR")):
            net = cts[contact]
            if amps:
                hits = reaches(net, "hpamp", ("OUTL", "OUTR"))
                names = {h[1] for h in hits}
                if names != {want}:
                    status = FAIL
                    d.append("%s (%s) reaches %s, expected the amplifier %s (CTIA %s; TPA p.3)"
                             % (contact, nl.label(net), [(h[0], h[1]) for h in hits] or "no amplifier output",
                                want, JACK_CTIA[contact]))
                else:
                    d.append("%s <- %s %s via %s" % (contact, hits[0][0], want, hits[0][2] or "direct"))
            else:
                d.append("%s on %s (no amplifier in the netlist)" % (contact, nl.label(net)))
        g = cts["ring2"]
        if g != nl.gnd:
            status = FAIL
            d.append("ring 2 must be ground in a CTIA jack (found %s)%s" % (
                nl.label(g), " - sleeve on GND = OMTP wiring" if cts["sleeve"] == nl.gnd else ""))
        else:
            d.append("ring 2 on GND (= TPA6132A2 SGND net, checked in A11)")
        mic = cts["sleeve"]
        if mic in nl.power_nets():
            status = FAIL
            d.append("sleeve on %s: in a CTIA headset the sleeve is the microphone" % nl.labels[mic])
        elif codecs:
            c = codecs[0]
            micin = ic_net(nl, c, CM108B_PINS, "MICIN")
            hit = False
            for n, via in nl.through_series(mic, kinds=("res", "cap"), depth=2,
                                            no_enter=set(nl.power_nets())).items():
                if n == micin:
                    hit = True
                    d.append("sleeve -> %s -> CM108B MICIN (bias and coupling checked in A06)" % via)
            if not hit:
                status = FAIL
                d.append("sleeve (%s) does not reach the CM108B MICIN through series R/C" % nl.label(mic))
            outs = reaches(mic, "hpamp", ("OUTL", "OUTR")) if amps else []
            if outs:
                status = FAIL
                d.append("sleeve also reaches amplifier outputs %s" % outs)
        d.append("rating 0.5 A / 30 V DC (drawing): far above headphone currents")
    rep.add("J01", title, status, "JACK", d)


# -------------------------------------------------------------------- LEDs ---
def check_leds(nl, rep):
    leds = [r for r in nl.refs("led") if not nl.dnp(r)]
    if not leds:
        rep.add("D01", "LEDs", SKIP, "LED_red", [])
        return
    status = PASS
    d = []
    pn = nl.power_nets()

    def resolve(net, exclude):
        """Follow at most one series resistor. Returns (kind, far_net, R)."""
        if net is None:
            return ("open", None, None)
        if net in pn:
            return ("gnd" if net == nl.gnd else "supply", net, None)
        if nl.module and nl.module in [r for r, _ in nl.mems(net)]:
            return ("gpio", net, None)
        if nl.rp and any(r == nl.rp and int(p) in RP_GPIO for r, p in nl.mems(net)):
            return ("gpio", net, None)
        if nl.charger and (nl.charger, nl.pin_by_role(nl.charger, CHARGER_ROLE, "STAT")) in nl.mems(net):
            return ("stat", net, None)
        rs = nl.two_pin_parts_on(net, ("res",), exclude=exclude)
        if len(rs) == 1:
            ref, pin, onet = rs[0]
            k, far, _ = resolve(onet, ref)
            return (k, far, parse_number(nl.value(ref), "R"))
        return ("other", net, None)

    for l in leds:
        a, k, assumed = nl.diode_ak(l)
        vf, vfmin, ifmax, src, generic = led_params(nl.parts[l])
        an, kn = nl.net(l, a), nl.net(l, k)
        ka, fa, ra = resolve(an, l)
        kk, fk, rk = resolve(kn, l)
        line = "%s: anode(%s) %s -> [%s%s] ; cathode(%s) %s -> [%s%s]" % (
            nl.desc(l), a, nl.label(an), ka, " via %s" % fmt_r(ra) if ra else "",
            k, nl.label(kn), kk, " via %s" % fmt_r(rk) if rk else "")
        if assumed:
            line += " [polarity assumed: pin 1 = cathode, pin 2 = anode]"
        d.append(line)
        if generic:
            d.append("  Vf for '%s' assumed %.2f V (no datasheet in the set)" % (nl.value(l), vf))
        r = ra or rk
        # charger status pin: open-drain (TP4054 CHRG) can only sink; the MCP73831 STAT is tri-state and can also
        # source (lit on charge complete) - limits per model (CHARGER_MODELS: TP_chrg / MCP_stat sources)
        md = CHARGER_MODELS.get(nl.chg_model or "", {})
        tri = md.get("stat") == "tri-state"
        ok = (ka in ("supply", "gpio") or (ka == "stat" and tri)) and kk in ("gnd", "stat", "gpio")
        if (ka, kk) in (("gpio", "gpio"), ("stat", "stat")):
            ok = False
        if not ok:
            status = FAIL
            d.append("  polarity/wiring wrong: current must flow from a supply or GPIO (anode) to GND/STAT/GPIO (cathode)"
                     "%s" % (" (an open-drain %s STAT cannot source)" % nl.chg_model if ka == "stat" else ""))
            continue
        if r is None:
            status = FAIL
            d.append("  no series resistor: LED current unlimited")
            continue
        if ka == "stat":
            vdd_c = nl.net(nl.charger, nl.pin_by_role(nl.charger, CHARGER_ROLE, "VDD"))
            vhi = (nl.net_voltage_nom(vdd_c) or V_VBUS_NOM) - md.get("voh_drop", 0.4)
        else:
            vhi = nl.net_voltage_nom(fa) if ka == "supply" else V_VDD
        vlo = md.get("vol", 0.3) if kk == "stat" else 0.0
        i = (vhi - vf - vlo) / r * 1000
        d.append("  I ~ %.1f mA (%.1f V - Vf %.2f V%s) / %s ; LED IF max %.0f mA" % (
            i, vhi, vf, " - %.1f V %s %s low" % (vlo, nl.chg_model, nl.pin_name(nl.charger, nl.pin_by_role(
                nl.charger, CHARGER_ROLE, "STAT")) or "status pin") if kk == "stat" else "", fmt_r(r), ifmax))
        if i > ifmax:
            status = FAIL
            d.append("  exceeds the LED maximum forward current")
        if (ka == "gpio" or kk == "gpio") and nl.rp:
            # RP2040 drive strength 2/4/8/12 mA, default 4 mA; VOH >= 2.62 V at the selected current (Tables 614, 625)
            if i > 12.0:
                status = FAIL
                d.append("  above the 12 mA strongest drive setting (Table 614)")
            elif i > 4.0:
                status = WARN if status == PASS else status
                d.append("  above the default 4 mA drive: firmware must select 8 or 12 mA (Table 614), or the LED is dimmer")
            else:
                d.append("  within the default 4 mA drive (VOH >= 2.62 V at 4 mA, Table 625); counts toward the 50 mA "
                         "all-pin limit (IIOVDD_MAX)")
        elif ka == "gpio" or kk == "gpio":
            if i > 4.0:
                status = FAIL
                d.append("  exceeds the GPIO standard-drive capability (IOH/IOL max 4 mA): needs high drive (<= 15 mA)")
            elif i > 1.0:
                d.append("  above the guaranteed standard-drive minimum (1 mA): the LED may be slightly dimmer than computed "
                         "unless the pin is configured high-drive (H0H1)")
        if kk == "stat" and i > md.get("sink_mA", 10.0):
            status = FAIL
            d.append("  the %s STAT/CHRG pin sinks %.0f mA max" % (nl.chg_model, md.get("sink_mA", 10.0)))
        if ka == "stat" and i > md.get("source_mA", 0.0):
            status = FAIL
            d.append("  the %s STAT pin sources %.0f mA max" % (nl.chg_model, md.get("source_mA", 0.0)))
        if "stat" in (ka, kk):
            d.append("  charge indicator on the %s status pin (%s; see C04)" % (nl.chg_model, SRC[md.get("src", "TP_chrg")].split(" (")[0]))
        if ka == "gpio":
            pin = [int(p) for rr, p in nl.mems(fa) if rr == nl.mcu][0]
            d.append("  active-high LED on %s pin %d %s" % (nl.mcu_word, pin, nl.mcu_pin_label(pin)))
        elif kk == "gpio":
            pin = [int(p) for rr, p in nl.mems(fk) if rr == nl.mcu][0]
            vhi_max = nl.net_voltage_max(fa) or V_VDD
            d.append("  active-low LED on %s pin %d %s from %s" % (nl.mcu_word, pin, nl.mcu_pin_label(pin),
                                                                 nl.labels.get(fa, fa)))
            if vhi_max - vfmin > V_VDD + 0.3:
                status = WARN if status == PASS else status
                d.append("  with the pin high-Z the LED pulls it to %.1f - %.2f = %.2f V > VI/O max %.1f V"
                         % (vhi_max, vfmin, vhi_max - vfmin, V_VDD + 0.3))
    meta_led = (nl.data.get("matrix") or {}).get("status_led")
    if nl.rp and meta_led:
        # the firmware drives the pin named in the metadata: it must be the one with the LED on it
        pad = nl.mcu_pin_by_name(meta_led)
        net = nl.rppin(pad) if pad else None
        near = {net} | {o for _, _, o in nl.two_pin_parts_on(net, ("res",))} if net else set()
        hit = sorted(l for l in leds if near & {nl.net(l, p) for p in nl.pins_of(l)})
        if hit:
            d.append("matrix.status_led %s = pad %d %s: drives %s" % (meta_led, pad, RP_PINS[pad], hit))
        else:
            status = FAIL
            d.append("matrix.status_led %s (pad %s) has no LED on it: the firmware would drive the wrong pin"
                     % (meta_led, pad))
    rep.add("D01", "LEDs: polarity, series resistor, current within LED / driver limits", status,
            SRC["LED_red"] + "; " + SRC["RP_io"] if nl.rp else "LED_red", d)


# --------------------------------------------------------- reset button -----
def check_reset_button(nl, rep):
    if nl.rp:
        check_rp_buttons(nl, rep)
        return
    if not nl.module:
        rep.add("R01", "reset button", SKIP, "TACT", [])
        return
    rst = nl.modpin(E73_RESET)
    ts = [r for r in nl.refs("tact") if not nl.dnp(r)]
    on_reset = [t for t in ts if rst in {nl.net(t, p) for p in nl.pins_of(t)}]
    if not on_reset:
        rep.add("R01", "reset push button between RESET and GND", SKIP, "TACT",
                ["no tactile switch on the RESET net (the BlueMicro840 has only a test point there)"])
        return
    status = PASS
    d = []
    for t in on_reset:
        nets = {p: nl.net(t, p) for p in nl.pins_of(t)}
        used = {p: n for p, n in nets.items() if n is not None}
        d.append("%s: %s" % (nl.desc(t), {p: nl.label(n) for p, n in nets.items()}))
        if set(used.values()) != {rst, nl.gnd}:
            status = FAIL
            d.append("the used pads must be exactly RESET and GND")
        if len(nets) == 4:
            if len(used) != 2:
                status = FAIL
                d.append("a 4-pad switch must use one pad of each internal pair; %d pads connected" % len(used))
            else:
                status = WARN if status == PASS else status
                d.append("datasheet: pads A-B and C-D are joined internally; it only shows letters, so the "
                         "footprint's 1-4 numbering cannot be verified here - on the bare board measure that pad %s "
                         "to pad %s is OPEN when not pressed (if they are an internal pair the MCU is held in reset)"
                         % tuple(used))
        d.append("contact rating 50 mA / 12 V: fine for a logic input; no debouncing needed (reset)")
    rep.add("R01", "reset push button between RESET and GND, unused pads open", status, "TACT", d)


def check_rp_buttons(nl, rep):
    """R01 on an RP2040: the RESET (RUN) and BOOT (QSPI_SS strap) push buttons close to GND, pads paired right."""
    title = "RESET (RUN) and BOOT (QSPI_SS strap) push buttons between their signal and GND, unused pads open"
    run = nl.rppin(RP_RUN)
    sig = {}
    for t in nl.fitted("tact"):
        nets = {nl.net(t, p) for p in nl.pins_of(t)}
        if run is not None and run in nets:
            sig[t] = (run, "RESET: RUN")
        for ref, rb, bnet in rp_boot_paths(nl):
            if bnet in nets:
                sig[t] = (bnet, "BOOT: QSPI_SS through %s %s" % (ref, fmt_r(rb)))
    if not sig:
        rep.add("R01", title, SKIP, "TACT", ["no tactile switch on RUN or on a QSPI_SS strap"])
        return
    status = PASS
    d = []
    for t, (net, what) in sorted(sig.items()):
        nets = {p: nl.net(t, p) for p in nl.pins_of(t)}
        used = {p: n for p, n in nets.items() if n is not None}
        d.append("%s (%s): %s" % (nl.desc(t), what, {p: nl.label(n) for p, n in nets.items()}))
        if set(used.values()) != {net, nl.gnd}:
            status = FAIL
            d.append("the used pads must be exactly %s and GND" % nl.label(net))
        if len(nets) == 4:
            if len(used) != 2:
                status = FAIL
                d.append("a 4-pad switch must use one pad of each internal pair; %d pads connected" % len(used))
            else:
                status = WARN if status == PASS else status
                d.append("datasheet: pads A-B and C-D are joined internally; it only shows letters, so the footprint's "
                         "1-4 numbering cannot be verified here - on the bare board measure that pad %s to pad %s is "
                         "OPEN when not pressed (if they are an internal pair the switch is always closed)" % tuple(used))
    d.append("contact rating 50 mA / 12 V: fine for logic-level straps; no debouncing needed (reset / boot strap)")
    rep.add("R01", title, status, "TACT", d)


# ------------------------------------------------------------ test points ---
def check_testpoints(nl, rep):
    tps = nl.refs("tp")
    if not tps:
        rep.add("T01", "test points", SKIP, "NETLIST", ["no test points"])
        return
    status = PASS
    d = []
    for t in tps:
        for p in nl.pins_of(t):
            net = nl.net(t, p)
            if net is None or len(nl.mems(net)) < 2:
                status = FAIL
                d.append("%s on %s is floating" % (nl.desc(t), nl.label(net)))
            else:
                d.append("%s -> %s" % (nl.desc(t), nl.label(net)))
    rep.add("T01", "test points sit on real nets", status, "NETLIST", d)


# ------------------------------------------------------------ floating -----
def pin_may_float(nl, ref, pin):
    """For the newer ICs (and the charger): True if the datasheet lets the pin stay open, False if it
    must be connected, None if the part kind is judged by the older rules below."""
    k = nl.kind[ref]
    pin = str(pin)
    if k == "charger":
        return CHARGER_ROLE.get(pin) == "STAT"          # STAT is only a status output (MCP p.11 3.3)
    if k == "hub":
        nm = CH334P_PINS.get(pin)
        if nm is None:
            return False                                # exposed pad = the CH334P's only GND (p.2)
        if re.fullmatch(r"D[PM][1-4]", nm) or nm in ("RESET#/CDP", "PGANG"):
            return True                                 # unused ports, p.4 'leave floating', internal pull-up (p.5)
        if nm == "XO":
            return nl.net(ref, pin_of(CH334P_PINS, "XI")) == nl.gnd   # crystal-free option (p.27)
        return False
    if k == "codec":
        nm = CM108B_PINS.get(pin)
        if nm is None or nm in CM108B_FLOAT_OK:
            return True                                 # pulls / outputs / N.C. (p.7-8)
        return nm in ("MICIN", "VBIAS", "LOL", "LOR", "LOBS")   # unused audio functions (judged by A02/A05/A06)
    if k == "hpamp":
        return TPA6132_PINS.get(pin) is None            # only the thermal pad may float (p.3, p.18)
    if k == "loadsw":
        return TPS22919_PINS.get(pin) in ("NC", "QOD")  # p.3
    if k == "jack":
        return True
    if k == "rp2040":
        # supplies, the ground pad and TESTEN must be connected (Tables 619 / 621); GPIO have pull-downs at reset
        # (Table 615); XIN/XOUT, QSPI, USB, RUN and SWD are judged by Q06-Q11
        if not pin.isdigit() or int(pin) not in RP_PINS:
            return False
        return not (int(pin) in RP_SUPPLY_PINS - {RP_VREG_VOUT} or int(pin) == RP_TESTEN)
    if k == "flash":
        return False                                    # all eight pins have a function (W25Q128JV p.5)
    return None


def check_floating(nl, rep):
    status = PASS
    d = []
    allowed_notes = []
    passive = ("res", "cap", "ind", "schottky", "mdiode", "led", "xtal", "key")
    for net, mems in nl.members.items():
        if len(mems) != 1:
            continue
        ref, pin = mems[0]
        k = nl.kind[ref]
        txt = "net %s has only %s.%s (%s)" % (net, ref, pin, k)
        unfitted = [(r, p) for r, p in nl.members_all.get(net, []) if (r, p) != (ref, pin)]
        if unfitted:
            allowed_notes.append(txt + " plus unfitted (DNP) %s - open by choice" % unfitted)
        elif k in passive or (k == "module" and int(pin) in E73_FIXED and int(pin) != E73_DCCH) \
                or k in ("pmos", "esd", "enc") or pin_may_float(nl, ref, pin) is False:
            status = FAIL
            d.append(txt + " - FLOATING")
        else:
            allowed_notes.append(txt + " - allowed (NC / unused pin)")
    for ref, p in nl.parts.items():
        if nl.dnp(ref):
            continue
        k = nl.kind[ref]
        for pin, pd in p["pins"].items():
            if pd.get("net") is not None:
                continue
            nm = (pd.get("name") or "").upper()
            pin = str(pin)
            txt = "%s.%s (%s %s) unconnected" % (ref, pin, k, nm)
            bad = False
            pmf = pin_may_float(nl, ref, pin)
            if pmf is not None:
                bad = not pmf
            elif k in passive:
                bad = True
            elif k == "module":
                bad = int(pin) in E73_FIXED and int(pin) != E73_DCCH
            elif k == "ldo":
                bad = AP2112_ROLE.get(pin) != "NC"
            elif k == "usbc":
                bad = USBC_ROLE.get(pin, "SHIELD") in ("VBUS", "GND", "CC1", "CC2", "D+", "D-")
            elif k == "esd":
                bad = True
            elif k == "pmos":
                bad = True
            elif k == "enc":
                bad = nm in ("A", "B", "C")
            elif k == "slide":
                bad = pin == "2"
            if bad:
                status = FAIL
                d.append(txt + " - must be connected")
            else:
                allowed_notes.append(txt + " - allowed")
    # a two-pin part with both pins on the same net is shorted out (wrong netlist or useless part)
    for ref, p in nl.parts.items():
        pins = nl.pins_of(ref)
        if len(pins) == 2 and not nl.dnp(ref):
            n1, n2 = nl.net(ref, pins[0]), nl.net(ref, pins[1])
            if n1 is not None and n1 == n2:
                status = FAIL
                d.append("%s has both pins on net %s - component shorted out" % (nl.desc(ref), n1))
    d.extend(allowed_notes)
    if not d:
        d.append("no single-pin nets, no unconnected pins")
    rep.add("N01", "no floating passive / IC pin; single-pin nets only on NC or spare pins; no self-shorted part",
            status, "NETLIST", d)


# ------------------------------------------------------------ key matrix ---
def matrix_meta_pins(nl, key):
    """Ordered module pin numbers from matrix metadata (rows/cols) or None."""
    m = nl.data.get("matrix") or {}
    lst = m.get(key)
    if not lst:
        return None
    out = []
    for name in lst:
        pin = nl.mcu_pin_by_name(name)
        out.append(pin)
    return out


def check_matrix(nl, rep):
    keys = [r for r in nl.refs("key") if not nl.dnp(r)]
    encs = [r for r in nl.refs("enc") if not nl.dnp(r)]
    if not keys and not encs:
        rep.add("K01", "key matrix cells", SKIP, "D4148", ["no key switches"])
        rep.add("K02", "matrix nets and coordinates", SKIP, "D4148", [])
        return
    if not nl.mcu:
        rep.add("K01", "key matrix cells", FAIL, "D4148", ["no module"])
        return
    s1 = PASS
    d1 = []
    gpio_net = nl.mcu_gpio_nets()
    cells = []       # (ref, col_net, row_net, diode)
    col_nets, row_nets = set(), set()

    def analyse_cell(ref, pins, label):
        nonlocal s1
        nets = {p: nl.net(ref, p) for p in pins}
        colp = [p for p, n in nets.items() if n in gpio_net]
        if len(colp) != 1:
            s1 = FAIL
            d1.append("%s: expected exactly one pin on a column (%s GPIO) net, got %s" % (label, nl.mcu_word, {p: nl.label(n) for p, n in nets.items()}))
            return
        cp = colp[0]
        sp = [p for p in pins if p != cp][0]
        cn, sn = nets[cp], nets[sp]
        if sn is None:
            s1 = FAIL
            d1.append("%s: pin %s unconnected" % (label, sp))
            return
        mem = nl.mems(sn, exclude=ref)
        diodes = [(r, p) for r, p in mem if nl.kind[r] == "mdiode"]
        if len(mem) != 1 or len(diodes) != 1:
            s1 = FAIL
            d1.append("%s: pin %s net %s must hold exactly one diode anode, has %s" % (label, sp, sn, mem))
            return
        dref, dpin = diodes[0]
        a, k, assumed = nl.diode_ak(dref)
        if dpin != a:
            s1 = FAIL
            d1.append("%s: diode %s connects its %s to the switch - must be the anode (col2row: col -> switch -> anode, cathode -> row)"
                      % (label, dref, "cathode" if dpin == k else "pin " + dpin))
            return
        rn = nl.net(dref, k)
        if rn not in gpio_net:
            s1 = FAIL
            d1.append("%s: diode %s cathode on %s which is not a %s GPIO (row) net" % (label, dref, nl.label(rn), nl.mcu_word))
            return
        if rn == cn:
            s1 = FAIL
            d1.append("%s: row and column are the same net" % label)
            return
        col_nets.add(cn)
        row_nets.add(rn)
        cells.append((ref, cn, rn, dref, cp))

    for ref in keys:
        pins = nl.pins_of(ref)
        if len(pins) != 2:
            s1 = FAIL
            d1.append("%s has %d pins, expected 2" % (ref, len(pins)))
            continue
        analyse_cell(ref, pins, "key %s '%s'" % (ref, nl.value(ref)))
    for ref in encs:
        sw = [p for p in nl.pins_of(ref) if p.upper() in ("S1", "S2")]
        if len(sw) == 2:
            analyse_cell(ref, sw, "encoder push %s" % ref)
    # diode part check
    for dref in nl.refs("mdiode"):
        a, k, assumed = nl.diode_ak(dref)
        if assumed:
            s1 = WARN if s1 == PASS else s1
            d1.append("%s: pin names missing, polarity assumed (1N4148W datasheet: pin 1 cathode, pin 2 anode)" % dref)
        elif (a, k) != ("2", "1"):
            s1 = FAIL
            d1.append("%s: netlist names pin %s anode / pin %s cathode but the 1N4148W datasheet has 1 = cathode, 2 = anode" % (dref, a, k))
    nk = len(keys) + sum(1 for e in encs if len([p for p in nl.pins_of(e) if p.upper() in ("S1", "S2")]) == 2)
    d1.insert(0, "%d switch cells analysed (%d keys, %d encoder pushes): col -> switch -> 1N4148W anode, cathode -> row"
              % (nk, len(keys), nk - len(keys)))
    unconventional = [ref for ref, cn, rn, dref, cp in cells if nl.kind[ref] == "key" and cp != "1"]
    if unconventional:
        s1 = WARN if s1 == PASS else s1
        d1.append("keys using pin 2 on the column side (symmetric socket, electrically fine): %s" % unconventional)
    if s1 == PASS:
        d1.append("every cell well formed; diode reverse rating 75 V / 150 mA far above matrix levels")
    rep.add("K01", "key matrix cells: pin1 on COL, pin2 on a private net with one diode anode, cathode on ROW", s1, "D4148", d1)

    # --- K02: purity, duplicates, metadata
    s2 = PASS
    d2 = []
    for cn in sorted(col_nets):
        bad = [(r, p) for r, p in nl.mems(cn) if not ((nl.kind[r] == "key") or (nl.kind[r] == "enc" and p.upper() in ("S1", "S2")) or r == nl.mcu)]
        mp = nl.mcu_pins_on(cn)
        if bad or len(mp) != 1:
            s2 = FAIL
            d2.append("column net %s: foreign members %s, %s pins %s" % (cn, bad, nl.mcu_word, mp))
    for rn in sorted(row_nets):
        bad = [(r, p) for r, p in nl.mems(rn) if not (nl.kind[r] == "mdiode" or r == nl.mcu)]
        mp = nl.mcu_pins_on(rn)
        if bad or len(mp) != 1:
            s2 = FAIL
            d2.append("row net %s: foreign members %s, %s pins %s" % (rn, bad, nl.mcu_word, mp))
    if col_nets & row_nets:
        s2 = FAIL
        d2.append("nets used both as row and column: %s" % (col_nets & row_nets))
    rows_meta = matrix_meta_pins(nl, "rows")
    cols_meta = matrix_meta_pins(nl, "cols")
    row_pin = {rn: gpio_net[rn] for rn in row_nets}
    col_pin = {cn: gpio_net[cn] for cn in col_nets}
    if rows_meta is not None:
        if None in rows_meta or set(rows_meta) != set(row_pin.values()):
            s2 = FAIL
            d2.append("matrix.rows %s does not match the row pins found %s"
                      % (nl.data["matrix"].get("rows"), sorted(nl.mcu_pin_label(p) for p in row_pin.values())))
        if None in (cols_meta or [None]) or set(cols_meta or []) != set(col_pin.values()):
            s2 = FAIL
            d2.append("matrix.cols %s does not match the column pins found %s"
                      % (nl.data["matrix"].get("cols"), sorted(nl.mcu_pin_label(p) for p in col_pin.values())))
        row_index = {p: i for i, p in enumerate(rows_meta)}
        col_index = {p: i for i, p in enumerate(cols_meta or [])}
    else:
        row_index = {p: i for i, p in enumerate(sorted(row_pin.values()))}
        col_index = {p: i for i, p in enumerate(sorted(col_pin.values()))}
        d2.append("no matrix metadata: rows/cols numbered by %s pin order" % nl.mcu_word)
    coords = defaultdict(list)
    for ref, cn, rn, dref, cp in cells:
        r = row_index.get(row_pin[rn])
        c = col_index.get(col_pin[cn])
        coords[(r, c)].append(ref)
        note = nl.parts[ref].get("note") or ""
        if r is None or c is None:
            s2 = FAIL
            d2.append("%s: its row/column pin (%s / %s) is not listed in the matrix metadata"
                      % (ref, nl.mcu_pin_label(row_pin[rn]), nl.mcu_pin_label(col_pin[cn])))
        m = re.search(r"\((\d+)\s*,\s*(\d+)\)", note)
        if m and (int(m.group(1)), int(m.group(2))) != (r, c):
            s2 = WARN if s2 == PASS else s2
            d2.append("%s note says %s but it sits at (%s,%s)" % (ref, m.group(0), r, c))
    dups = {rc: refs for rc, refs in coords.items() if len(refs) > 1}
    if dups:
        s2 = FAIL
        d2.append("two switches on the same (row, col): %s" % dups)
    d2.insert(0, "%d rows x %d columns, %d cells occupied, rows %s, cols %s" % (
        len(row_nets), len(col_nets), len(coords),
        [nl.mcu_pin_label(p).split("/")[0] for p in (rows_meta or sorted(row_pin.values()))],
        [nl.mcu_pin_label(p).split("/")[0] for p in (cols_meta or sorted(col_pin.values()))]))
    # gpio metadata
    g = nl.data.get("gpio")
    if g:
        wrong = [(p, n, nl.mcupin(int(p))) for p, n in g.items() if nl.mcupin(int(p)) != n]
        if wrong:
            s2 = FAIL
            d2.append("gpio metadata mismatch (pin, claimed net, actual net): %s" % wrong)
        else:
            d2.append("gpio metadata (%d entries) agrees with the netlist" % len(g))
    rep.add("K02", "row/column nets pure (one %s pin each), no duplicate cell, metadata agrees" % nl.mcu_word, s2, "D4148",
            d2)


def check_encoders(nl, rep):
    encs = [r for r in nl.refs("enc") if not nl.dnp(r)]
    if not encs:
        rep.add("K03", "rotary encoders", SKIP, "EC11", ["no encoders in this netlist"])
        return
    status = PASS
    d = []
    gpio_net = nl.mcu_gpio_nets()
    found = []
    for e in encs:
        pins = {p.upper(): p for p in nl.pins_of(e)}
        line = "%s: " % nl.desc(e) + ", ".join("%s -> %s" % (p, nl.label(nl.net(e, p))) for p in nl.pins_of(e))
        d.append(line)
        ab = []
        for nm in ("A", "B"):
            p = pins.get(nm)
            net = nl.net(e, p) if p else None
            if net is None or net not in gpio_net:
                status = FAIL
                d.append("%s: %s must go to a %s GPIO" % (e, nm, nl.mcu_word))
                continue
            extra = nl.mems(net, exclude=e)
            if len(extra) != 1 or extra[0][0] != nl.mcu:
                status = FAIL
                d.append("%s: %s net %s shared with %s (must be a dedicated GPIO)" % (e, nm, net, extra))
            ab.append(nl.mcu_pin_label(gpio_net[net]).split("/")[0])
        found.append(tuple(ab))
        for nm in ("C", "MP"):
            ps = [p for u, p in pins.items() if u == nm or u.startswith(nm)]
            for p in ps:
                if nl.net(e, p) != nl.gnd:
                    if nm == "C":
                        status = FAIL
                    d.append("%s: %s on %s, expected GND" % (e, p, nl.label(nl.net(e, p))))
        if not ("S1" in pins and "S2" in pins):
            d.append("%s: no push switch pins" % e)
    if nl.rp:
        d.append("A/B read with the GPIO internal pull-ups (50-80 kOhm, RP2040 Table 625 -> <= 66 uA): within the "
                 "10 mA / 5 V DC contact rating; C (common) to GND")
    else:
        d.append("A/B read with the GPIO internal pull-ups (13 kOhm -> ~0.25 mA): within the 10 mA / 5 V DC contact rating; "
                 "C (common) to GND")
    meta = (nl.data.get("matrix") or {}).get("encoders")
    if meta is not None:
        if nl.rp:
            want = {tuple(sorted(RP_PINS.get(rp_pin_by_name(x[k]) or 0, x[k]).split("/")[0] for k in ("a", "b")))
                    for x in meta}
        else:
            want = {tuple(sorted((x["a"].replace("_", "."), x["b"].replace("_", ".")))) for x in meta}
        got = {tuple(sorted(ab)) for ab in found}
        if want != got:
            status = WARN if status == PASS else status
            d.append("matrix.encoders metadata %s differs from the netlist %s" % (sorted(want), sorted(got)))
        else:
            d.append("matrix.encoders metadata agrees: %s" % sorted(got))
    rep.add("K03", "encoders: A/B on dedicated GPIOs, C and MP to GND, push switch wired as a matrix key", status, "EC11", d)


# ------------------------------------------------------------- bootloader ---
def check_bootloader(nl, rep):
    if not nl.module:
        rep.add("B01", "bootloader pin usage", SKIP, "BOOT",
                ["no E73: the RP2040 boots from its USB boot ROM (BOOTSEL strap checked in Q08)"] if nl.rp else [])
        return
    status = PASS
    d = []
    n40 = nl.modpin(E73_P1_04)
    led40 = [r for r, p in nl.mems(n40)] if n40 else []
    leds = [r for r in led40 if nl.kind[r] == "led"]
    if leds:
        a, k, _ = nl.diode_ak(leds[0])
        if nl.net(leds[0], a) == n40:
            d.append("LED_PRIMARY_PIN P1.04 (pin 40): %s anode on it -> active-high, matches LED_STATE_ON 1" % leds[0])
        else:
            status = WARN
            d.append("LED_PRIMARY_PIN P1.04: %s cathode on it -> active-low, inverted vs LED_STATE_ON 1" % leds[0])
    else:
        status = WARN
        d.append("no LED on P1.04 (pin 40): the bootloader status LED will not blink (%s)" % (nl.label(n40)))
    n2 = nl.modpin(E73_P1_10)
    if n2:
        mem = [(r, p) for r, p in nl.mems(n2, exclude=nl.module)]
        if any(nl.kind[r] == "led" for r, _ in mem):
            d.append("LED_SECONDARY_PIN P1.10 (pin 2): LED present")
        else:
            status = WARN if status == PASS else status
            d.append("LED_SECONDARY_PIN P1.10 (pin 2) is used for %s: the bootloader drives it as an output while in DFU; "
                     "harmless for a diode matrix column (rows are inputs), but keep nothing on it that minds a toggling pin"
                     % nl.label(n2))
    rst = nl.modpin(E73_RESET)
    if rst and any(nl.kind[r] == "tact" for r, _ in nl.mems(rst)):
        d.append("BUTTON_DFU = P0.18 = RESET: DFU entered by double reset through the button")
    else:
        d.append("no reset button: DFU only via the test point or software")
    d.append("BUTTON_DFU_OTA P1.01 is not bonded out on the E73 - nothing to wire")
    rep.add("B01", "bluemicro_nrf52840 bootloader pin usage (LEDs, DFU button)", status, "BOOT", d)


# ----------------------------------------------------------------------------
def run(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    nl = Netlist(data)
    rep = Report()
    title = "%s (design=%s variant=%s)" % (path, data.get("design", "?"), data.get("variant", "?"))
    checks = [
        ("N00", check_consistency), ("M01", check_module_gnd), ("M02", check_module_supply),
        ("M03", check_module_vbus), ("M04", check_module_usb_data), ("M05", check_module_swd),
        ("M06", check_module_reset), ("M07", check_crystal), ("M08", check_nfc), ("M09", check_dcch),
        ("M10", check_gpio_nets), ("M11", check_gpio_overvoltage), ("M12", check_module_pin_names),
        ("Q01", check_rp_pins), ("Q02", check_rp_gnd), ("Q03", check_rp_supply), ("Q04", check_rp_decoupling),
        ("Q05", check_rp_core), ("Q06", check_rp_crystal), ("Q07", check_rp_flash), ("Q08", check_rp_bootsel),
        ("Q09", check_rp_run), ("Q10", check_rp_swd), ("Q11", check_rp_usb), ("Q12", check_rp_budget),
        ("C01", check_charger_pins), ("C02", check_charger_bypass), ("C03", check_charger_prog),
        ("C04", check_charger_stat), ("C05", check_charger_outcap), ("C06", check_charger_detect),
        ("L01-L03", check_ldo),
        ("P01", check_schottky), ("P02", check_pmos), ("P03", check_power_nets_distinct),
        ("P04", check_backfeed), ("P05", check_battery), ("P06", check_divider), ("U01", check_usbc),
        ("U02", check_esd), ("U03", check_usb_topology),
        ("H01", check_hub_power), ("H02", check_hub_crystal), ("H03", check_hub_cfg),
        ("A01", check_codec_supply), ("A02", check_codec_regs), ("A03", check_codec_cfg), ("A04", check_codec_usb),
        ("A05", check_codec_lineout), ("A06", check_codec_mic),
        ("A11", check_amp_power), ("A12", check_amp_cp), ("A13", check_amp_inputs), ("A14", check_amp_ctl),
        ("S01", check_loadsw_power), ("S02", check_loadsw_on), ("S03", check_loadsw_qod), ("J01", check_jack),
        ("V01", check_vbus_protection), ("V02", check_vbus_sense), ("G01", check_layout),
        ("D01", check_leds), ("R01", check_reset_button), ("T01", check_testpoints),
        ("N01", check_floating), ("K01-K02", check_matrix), ("K03", check_encoders), ("B01", check_bootloader),
    ]
    for code, fn in checks:
        try:
            fn(nl, rep)
        except Exception as exc:  # a crashing check must never hide a problem: report it as FAIL
            rep.add(code, "%s (check crashed)" % fn.__name__, FAIL, "NETLIST",
                    ["internal error while checking: %s: %s" % (type(exc).__name__, exc)])
    return rep.print(title)


# ---------------------------------------------------------------- VBUS protection, VBUS sense, layout ---
TVS_VBR_MIN, TVS_VC, TVS_IR_MAX = 6.4, 9.2, 200e-6   # SMF5.0A (C2857263)
USB_ATTACH_C_MAX = 10e-6                             # USB 2.0 7.2.4.1
CABLE_L = 1e-6                                       # ~1 m USB cable
X5R_5V_DERATE = 0.6                                  # 0603/0805 X5R at 5 V DC bias (typical, Samsung CL series curves)


def check_vbus_protection(nl, rep):
    title = ("VBUS at the receptacle: TVS surge clamp, damped bulk capacitor (hot-plug ringing), total capacitance "
             "within USB's 10 uF; the 6 V parts on VBUS")
    vbus, gnd = nl.vbus, nl.gnd
    if not vbus or not nl.first("usbc"):
        rep.add("V01", title, SKIP, "VBUS_prot", ["no USB receptacle / VBUS"])
        return
    status, d = PASS, []
    tvs = [r for r in nl.fitted("tvs") if {nl.net(r, p) for p in nl.pins_of(r)} == {vbus, gnd}]
    if not tvs:
        status = WARN
        d.append("no TVS from VBUS to GND: surges and hot-plug ringing only meet the USBLC6's ESD clamp (VBR >= 6 V)")
    for r in tvs:
        a, k, _ = nl.diode_ak(r)
        if nl.net(r, k) == vbus and nl.net(r, a) == gnd:
            d.append("%s %s: cathode on VBUS, anode on GND; VBR >= %.1f V above USB-C's 5.5 V (off in use, leakage <= "
                     "%.0f uA at 5 V), clamps <= %.1f V at its rated surge" % (r, nl.value(r), TVS_VBR_MIN,
                                                                               TVS_IR_MAX * 1e6, TVS_VC))
        else:
            status = FAIL
            d.append("%s is reversed (cathode must be on VBUS): it would conduct at 0.7 V" % r)
    ceramic = [(r, c) for r, c in nl.cap_list(vbus) if c]
    c_direct = sum(c for _, c in ceramic)
    damp = []
    for r, pin, onet in nl.two_pin_parts_on(vbus, ("res",)):
        others = [m for m in nl.mems(onet) if m[0] != r]
        if others and all(nl.kind[m[0]] == "cap" and nl.other_end(*m)[1] == gnd for m in others):
            damp.append((r, parse_number(nl.value(r), "R"), onet, sum(parse_number(nl.value(m[0]), "F") or 0
                                                                     for m in others)))
    d.append("ceramic directly on VBUS: %s = %s (about %s at 5 V)" % ([x for x, _ in ceramic], fmt_c(c_direct),
                                                                    fmt_c(c_direct * X5R_5V_DERATE)))
    if not damp:
        status = WARN if status == PASS else status
        d.append("no damped bulk capacitor: a ~1 uH cable into the ceramic alone rings on hot-plug (overshoot up to ~2x)")
    for r, R, net, C in damp:
        z0 = math.sqrt(CABLE_L / (c_direct * X5R_5V_DERATE))
        n = C / c_direct
        ok = R is not None and 0.3 * z0 <= R <= 3 * z0 and n >= 2
        d.append("damping: %s %s in series with %s on %s; Z0 of 1 uH into %s = %.2f Ohm, Cd / C = %.1f (>= 2 needed, "
                 "R near Z0)" % (r, fmt_r(R), fmt_c(C), net, fmt_c(c_direct * X5R_5V_DERATE), z0, n))
        if not ok:
            status = WARN if status == PASS else status
            d.append("the RC branch is outside the useful damping range")
    total = c_direct + sum(C for *_, C in damp)
    d.append("total capacitance on VBUS at attach: %s (USB 2.0 7.2.4.1: <= 10 uF; capacitance behind the 3.3 V "
             "regulator and the soft-started load switch not counted)" % fmt_c(total))
    if total > USB_ATTACH_C_MAX * 1.001:
        status = WARN if status == PASS else status
        d.append("above 10 uF: the attach inrush exceeds USB 2.0 7.2.4.1")
    six = [r for r, p in nl.mems(vbus) if nl.kind[r] in ("loadsw", "hub")]
    for r in six:
        d.append("%s (%s) on VBUS: abs max 6 V (TPS22919) / 5.5 V (CH334 V5): the TVS and the damping keep hot-plug "
                 "peaks near 5.5-6 V" % (r, nl.kind[r]))
    if any(nl.kind[r] == "hub" for r in six):
        status = WARN if status == PASS else status
        d.append("the hub's V5 (abs max 5.5 V) on VBUS: CH334 6.4 recommends the on-board 3.3 V")
    rep.add("V01", title, status, "VBUS_prot", d)


def check_vbus_sense(nl, rep):
    title = "VBUS sense for the firmware: a divider into an ADC GPIO, inside the ADC range up to USB-C's 5.5 V"
    if not nl.rp or not nl.vbus:
        rep.add("V02", title, SKIP, "VBUS_sense", ["no RP2040"])
        return
    adc = {38: "GPIO26/ADC0", 39: "GPIO27/ADC1", 40: "GPIO28/ADC2", 41: "GPIO29/ADC3"}
    found = []
    for r, pin, onet in nl.two_pin_parts_on(nl.vbus, ("res",)):
        pads = [int(p) for x, p in nl.mems(onet) if x == nl.rp]
        if not pads:
            continue
        found.append((r, onet, pads, nl.resistors_between(onet, nl.gnd), nl.cap_list(onet)))
    if not found:
        rep.add("V02", title, SKIP, "VBUS_sense", ["no divider from VBUS to an RP2040 pin"])
        return
    status, d = PASS, []
    for r, net, pads, bottom, caps in found:
        rt = parse_number(nl.value(r), "R")
        rb = parallel(*[v for _, v in bottom if v]) if bottom else None
        d.append("%s %s from VBUS to %s, RP2040 pin(s) %s" % (r, fmt_r(rt), net, ["%d %s" % (p, adc.get(p, "not ADC"))
                                                                               for p in pads]))
        if any(p not in adc for p in pads):
            status = FAIL
            d.append("not an ADC pin: the firmware cannot read the level")
        if not rb:
            status = FAIL
            d.append("no resistor to GND: the pin would see VBUS through %s" % r)
            continue
        k = rb / (rt + rb)
        d.append("ratio %.3f: 5.0 V -> %.2f V, 5.5 V -> %.2f V (ADC range 0-3.3 V), 4.4 V -> %.2f V" %
                 (k, 5.0 * k, 5.5 * k, 4.4 * k))
        if 5.5 * k > V_VDD:
            status = FAIL
            d.append("above IOVDD at 5.5 V")
        th = rt * rb / (rt + rb)
        c = sum(x for _, x in caps if x)
        d.append("source %s, %s at the pin: tau %.0f us; divider current %.0f uA at 5 V" %
                 (fmt_r(th), fmt_c(c) if c else "no capacitor", th * c * 1e6, 5.0 / (rt + rb) * 1e6))
        if c and th * c > 100e-6:
            status = WARN if status == PASS else status
            d.append("slow: an unplug (VBUS falling ~4 mV/us) is seen late")
    rep.add("V02", title, status, "VBUS_sense", d)


LAYOUT_LIMITS = {  # kind: (mm of copper, vias, status when over)
    "decoupling": (5.0, 0, FAIL), "decoupling_shared": (8.0, 0, FAIL), "regulator": (2.5, 0, FAIL),
    "crystal": (8.0, 0, FAIL), "crystal_load": (3.0, 0, FAIL),
    "usb_termination": (5.0, 0, FAIL), "codec_avdd": (5.0, 0, FAIL), "jack_esd": (6.0, 0, WARN),
    "usb_fs": (60.0, 2, WARN), "vbus_clamp": (15.0, 2, WARN),
}


def check_layout(nl, rep):
    title = ("layout, measured on the routed PCB: supply pins to their capacitors, crystal, USB termination, codec "
             "AVDD, jack and VBUS clamps (copper path length and vias)")
    lay = nl.data.get("layout")
    if not lay:
        rep.add("G01", title, SKIP, "layout", ["no measurements in this netlist (pcb/verify_netlist.py adds them from "
                                               "the routed board)"])
        return
    status, d = PASS, []
    for m in lay:
        limit, vias, bad = LAYOUT_LIMITS.get(m["kind"], (None, None, WARN))
        if m["mm"] is None:
            status = FAIL
            d.append("%-15s %-9s %s -> %s: not joined by tracks" % (m["kind"], m["net"], m["from"], m["to"]))
            continue
        over = limit is not None and (m["mm"] > limit or m["vias"] > vias)
        d.append("%-15s %-9s %s -> %s: %5.2f mm, %d via(s)%s" % (m["kind"], m["net"], m["from"], m["to"], m["mm"],
                                                                 m["vias"], "  OVER (<= %g mm, %d vias)" % (limit, vias)
                                                                 if over else ""))
        if over:
            status = FAIL if bad == FAIL or status == FAIL else WARN
    d.append("limits: %s" % ", ".join("%s <= %g mm / %d vias" % (k, v[0], v[1]) for k, v in LAYOUT_LIMITS.items()))
    rep.add("G01", title, status, "layout", d)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ok = True
    for path in argv[1:]:
        ok = run(path) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
