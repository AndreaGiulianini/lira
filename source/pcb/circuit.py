"""The circuit of Lira as data: every part with its pins and the net each pin is on.

This is the single description of the connectivity. From it come:
  * the nets of the PCB (pcb/gen_pcb.py, pcb/electronics.py place these parts),
  * the schematic (pcb/gen_schematic.py),
  * the JSON netlist read by the independent checks (pcb/check_circuit.py),
  * the consistency check PCB == schematic == this file (pcb/verify_netlist.py).

The power / USB / programming section is a copy of the BlueMicro840 (jpconstantineau/NRF52-Board, a board built
with this same module, assembled by JLCPCB and sold), cross-checked with the nrfmicro 1.x. Every difference from
the BlueMicro840 is listed in DEVIATIONS and printed on the schematic.

The built-in sound card (audio()) sits behind a USB hub: the USB-C receptacle feeds a WCH CH334P hub, whose ports go
to the module and to a C-Media CM108B USB audio codec (headphones + microphone on a 3.5 mm jack). The codec section
follows C-Media's CM108B/CM119B demo board v1.33 (sheet 4) and application notes v1.50.
"""

# ------------------------------------------------------------------------------------------- Ebyte E73 module
# Pad number -> nRF52840 pin (Ebyte datasheet, confirmed by the BlueMicro840 netlist that uses the same module).
E73_PINS = {
    1: "P1.11", 2: "P1.10", 3: "P0.03/AIN1", 4: "P0.28/AIN4", 5: "GND", 6: "P1.13", 7: "P0.02/AIN0",
    8: "P0.29/AIN5", 9: "P0.31/AIN7", 10: "P0.30/AIN6", 11: "P0.00/XL1", 12: "P0.26", 13: "P0.01/XL2",
    14: "P0.06", 15: "P0.05/AIN3", 16: "P0.08", 17: "P1.09", 18: "P0.04/AIN2", 19: "VDD", 20: "P0.12",
    21: "GND", 22: "P0.07", 23: "VDDH", 24: "GND", 25: "DCCH", 26: "P0.18/RESET", 27: "VBUS", 28: "P0.15",
    29: "D-", 30: "P0.17", 31: "D+", 32: "P0.20", 33: "P0.13", 34: "P0.22", 35: "P0.24", 36: "P1.00",
    37: "SWDIO", 38: "P1.02", 39: "SWDCLK", 40: "P1.04", 41: "P0.09/NFC1", 42: "P1.06", 43: "P0.10/NFC2",
}
# Pads with a fixed role (net name). DCCH stays open: in normal-voltage mode (VDDH tied to VDD) REG0 is unused.
E73_FIXED = {
    5: "GND", 21: "GND", 24: "GND", 19: "3V3", 23: "3V3", 26: "RESET", 27: "VBUS", 29: "MCU_DN", 31: "MCU_DP",
    37: "SWDIO", 39: "SWCLK", 9: "BAT_SENSE", 11: "XL1", 13: "XL2", 40: "LED_RED",
    38: "AUD_EN",  # P1.02: switches the sound card on (USB mode only), firmware src/audio_gate.rs
}
E73_NC = (25, 41, 43)  # DCCH; NFC1/NFC2 (NFC antenna pins, not used as GPIO)
# The 25 GPIO pads left for the key matrix (edge pads first, inner pads need an escape via).
E73_EDGE_GPIO = (1, 2, 3, 4, 6, 7, 8, 10, 15, 17, 33, 35)
E73_INNER_GPIO = (12, 14, 16, 18, 20, 22, 28, 30, 32, 34, 36, 38, 42)
E73_GPIO = E73_EDGE_GPIO + E73_INNER_GPIO
E73_NEAR_ANTENNA = (1, 2, 42)  # the antenna is at the module end past these pads: slow signals only


def nrf_pin(pad):
    """'P0.31/AIN7' -> 'P0_31' (the name RMK uses)."""
    return E73_PINS[pad].split("/")[0].replace(".", "_")


# ------------------------------------------------------------------------------------------------------ parts

class Part:
    def __init__(self, ref, value, footprint, pins, lcsc=None, symbol=None, dnp=False, pcb_only=False, note=""):
        """pins: {number: (name, net)}; net None = not connected. symbol: KiCad symbol 'Lib:Name' or a custom id.
        pcb_only: mounting holes and stabilizers, which have no electrical meaning."""
        self.ref, self.value, self.footprint, self.lcsc = ref, value, footprint, lcsc
        self.pins = {str(k): v for k, v in pins.items()}
        self.symbol, self.dnp, self.pcb_only, self.note = symbol, dnp, pcb_only, note

    @property
    def nets(self):
        """{pin number: net} of the connected pins (what pcbnew needs)."""
        return {k: v[1] for k, v in self.pins.items() if v[1]}


def two(ref, value, footprint, lcsc, a, b, symbol, note=""):
    return Part(ref, value, footprint, {1: ("1", a), 2: ("2", b)}, lcsc, symbol, note=note)


def r0603(ref, value, lcsc, a, b, note=""):
    return two(ref, value, "Resistor_SMD:R_0603_1608Metric", lcsc, a, b, "Device:R", note)


def c0603(ref, value, lcsc, a, b, note=""):
    return two(ref, value, "Capacitor_SMD:C_0603_1608Metric", lcsc, a, b, "Device:C", note)


def bead(ref, lcsc, a, b, note=""):
    return two(ref, "600R@100MHz", "Inductor_SMD:L_0603_1608Metric", lcsc, a, b, "Device:FerriteBead", note)


def tp(ref, net, d="1.5"):
    return Part(ref, net, "TestPoint:TestPoint_Pad_D%smm" % d, {1: ("1", net)}, symbol="Connector:TestPoint")


LCSC = {
    "e73": "C356849", "mcp73831": "C424093", "ap2112k": "C51118", "usblc6": "C7519", "si2301": "C10487",
    "b5819w": "C8598", "led_white": "C2290", "led_red": "C2286", "usbc": "C165948", "jst": "C295747",
    "sw_power": "C221660", "sw_reset": "C318884", "xtal": "C32346",
    "r100k": "C25803", "r1k": "C21190", "r10k": "C25804", "r10M": "C7250", "r5k1": "C23186",
    "c10u": "C19702", "c4u7": "C19666", "c22p": "C1653", "c100n": "C14663",
    "socket": "C41430893", "diode": "C81598",
    # sound card: hub, codec, jack, 12 MHz crystal, and the passives not used elsewhere
    "ch334p": "C5373042", "cm108b": "C371347", "jack": "C95562", "xtal12": "C9002",
    "c1u": "C15849", "c100p": "C14858", "r22": "C23345", "r2k2": "C4190", "bead": "C1002",
    "tps22919": "C2149796", "tpa6132": "C69901", "c2u2": "C23630", "c470n": "C1623", "c10n": "C57112",
    "r1M": "C22935", "r1k2": "C22765",
    "c18p": "C53084486", "esd_jack": "C19224",
}

DEVIATIONS = [
    "Second AP2112K (switched 3.3 V for external devices, P0.12 enable) omitted: nothing external to power.",
    "USBLC6-2SC6 ESD array added on D+ / D- / VBUS at the USB-C receptacle.",
    "Power switch SW101 (C&K JS102011SAQN, 300 mA) in the battery + line, as on ZMK keyboards; JP2 bypasses it.",
    "JP1 + R104: closing the solder jumper puts a second 10k on PROG: charge current 100 mA -> 200 mA.",
    "Reset push button SW102 to GND (the BlueMicro840 has only a test point).",
    "USB-C shield pads to GND (left open on the BlueMicro840).",
    "LEDs: charging LED white, status LED red on P1.04 only (BlueMicro840: green charging, red P1.04, blue P1.10).",
    "DCCH inductor pads (DNP on the BlueMicro840) not fitted at all; P1.10 is a free GPIO here, P1.02 switches the "
    "sound card.",
    "Test points added on VBUS, VBAT and VIN (BlueMicro840: SWDIO, SWCLK, VCC, GND, RESET, P1.02).",
    "C107 4.7 uF added on VBUS at the charger's VDD pin (the MCP73831 datasheet asks for 4.7 uF; Nordic's "
    "reference circuit has 4.7 uF on VBUS; the BlueMicro840 has none).",
    "C108 1 uF at the regulator output and C109 100 nF at the module: the 10 uF C103 sits at the module's supply "
    "pins (VDD / VDDH), 25 mm away. C102 on VIN is 1 uF instead of 10 uF: together they keep the capacitance charged "
    "at USB attach near USB 2.0's 10 uF.",
    "Charger MCP73831 instead of the TP4054, same pins and same PROG resistor (1000 V / R_PROG): it is stable with "
    "no battery, so the board also works when built without one (its STAT pin, and the white LED, stay off).",
    "Battery divider 10M + 10M with 10 nF (BlueMicro840: 806k + 2M, 1 nF): the MCP73831 recognises a missing battery "
    "only if VBAT sees more than 7 MOhm (datasheet 4.2); 10 nF >= 2^12 x the SAADC's 2.5 pF keeps the reading within "
    "1 LSB (Nordic, 'Measuring Lithium battery voltage with nRF52'), and RMK samples it every 30 s. Drain 0.2 uA.",
    "Built-in USB sound card: the USB-C data lines go (through the ESD array) to a CH334P hub; hub port 3 goes to "
    "the module's D+ / D-, port 2 to a CM108B codec (C-Media demo board v1.33) with a 3.5 mm headset jack.",
]


def electronics(gpio=None):
    """Everything that is not the key matrix (sound card included). gpio: {module pad: net} for the matrix lines."""
    gpio = gpio or {}
    e73 = {}
    for pad, name in E73_PINS.items():
        if pad in E73_FIXED:
            e73[pad] = (name, E73_FIXED[pad])
        elif pad in E73_GPIO:
            e73[pad] = (name, gpio.get(pad))
        else:
            e73[pad] = (name, None)
    usb = {}
    for p in ("A4", "A9", "B4", "B9"):
        usb[p] = ("VBUS", "VBUS")
    for p in ("A1", "A12", "B1", "B12"):
        usb[p] = ("GND", "GND")
    usb.update({"A5": ("CC1", "CC1"), "B5": ("CC2", "CC2"), "A6": ("D+", "USB_DP"), "B6": ("D+", "USB_DP"),
                "A7": ("D-", "USB_DN"), "B7": ("D-", "USB_DN"), "A8": ("SBU1", None), "B8": ("SBU2", None),
                "SH": ("SHIELD", "GND")})
    return [
        Part("U1", "E73-2G4M08S1C", "lcsc:WIRELM-SMD_E73-2G4M08S1C", e73, LCSC["e73"], "lira:E73",
             note="nRF52840 module, normal-voltage mode: VDD and VDDH both on the 3.3 V rail"),
        # --- USB
        Part("J1", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", usb, LCSC["usbc"],
             "Connector:USB_C_Receptacle_USB2.0_16P"),
        r0603("R108", "5.1k", LCSC["r5k1"], "CC1", "GND", "USB-C sink: 5.1k on each CC"),
        r0603("R109", "5.1k", LCSC["r5k1"], "CC2", "GND"),
        Part("U4", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
             {1: ("I/O1", "USB_DP"), 2: ("GND", "GND"), 3: ("I/O2", "USB_DN"), 4: ("I/O2", "USB_DN"),
              5: ("VBUS", "VBUS"), 6: ("I/O1", "USB_DP")}, LCSC["usblc6"], "Power_Protection:USBLC6-2SC6",
             note="ESD protection, placed next to the receptacle"),
        r0603("R101", "100k", LCSC["r100k"], "VBUS", "GND", "VBUS bleeder (BlueMicro840 R3)"),
        # (the data lines continue to the hub, audio(): the module is on hub port 3)
        c0603("C107", "4.7uF", LCSC["c4u7"], "VBUS", "GND", "VBUS bypass for the charger and the module (deviation 10)"),
        # --- power path: USB through the Schottky, battery through the P-MOSFET (off while USB is present)
        Part("D101", "B5819W", "Diode_SMD:D_SOD-123", {1: ("K", "VIN"), 2: ("A", "VBUS")}, LCSC["b5819w"],
             "Device:D_Schottky", note="BlueMicro840 D1"),
        Part("Q1", "SI2301CDS", "Package_TO_SOT_SMD:SOT-23", {1: ("G", "VBUS"), 2: ("S", "VIN"), 3: ("D", "VBAT")},
             LCSC["si2301"], "Transistor_FET:AO3401A", note="BlueMicro840 Q1: gate to VBUS, source VIN, drain VBAT"),
        c0603("C101", "10uF", LCSC["c10u"], "VBAT", "GND"),
        c0603("C102", "1uF", LCSC["c1u"], "VIN", "GND", "regulator input (deviation 11)"),
        # --- charger (BlueMicro840 U4, a TP4054; here the pin-compatible MCP73831, deviation 12): 100 mA with 10k
        # on PROG, 200 mA with JP1 closed
        Part("U2", "MCP73831", "Package_TO_SOT_SMD:SOT-23-5",
             {1: ("STAT", "STAT"), 2: ("VSS", "GND"), 3: ("VBAT", "VBAT"), 4: ("VDD", "VBUS"), 5: ("PROG", "PROG")},
             LCSC["mcp73831"], "lira:MCP73831", note="Li-Ion linear charger, 4.2 V (MCP73831T-2ACI/OT)"),
        r0603("R103", "10k", LCSC["r10k"], "PROG", "GND", "I_charge = 1000 V / R_PROG = 100 mA"),
        Part("JP1", "charge 200 mA", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
             {1: ("A", "PROG"), 2: ("B", "PROG_ALT")}, symbol="Jumper:SolderJumper_2_Open",
             note="open = 100 mA (BlueMicro840 value), closed = 200 mA"),
        r0603("R104", "10k", LCSC["r10k"], "PROG_ALT", "GND"),
        Part("D102", "LED white", "LED_SMD:LED_0603_1608Metric", {1: ("K", "LED_CHG_K"), 2: ("A", "VBUS")},
             LCSC["led_white"], "Device:LED",
             note="charging indicator: VBUS -> LED -> 1k -> STAT (low while charging, high when done, open with no "
                  "battery)"),
        r0603("R102", "1k", LCSC["r1k"], "LED_CHG_K", "STAT"),
        # --- battery: connector, power switch (bypass jumper), voltage divider into AIN7 (BlueMicro840 R4/R6/C6)
        Part("J2", "battery JST-PH", "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal",
             {1: ("+", "BAT+"), 2: ("-", "GND"), "MP": ("MP", None)}, LCSC["jst"], "Connector:Conn_01x02_Pin",
             note="1 = +, 2 = -: check the cell's lead order with a meter"),
        Part("SW101", "JS102011SAQN", "Button_Switch_SMD:SW_SPDT_CK_JS102011SAQN",
             {1: ("A", "BAT+"), 2: ("B", "VBAT"), 3: ("C", None)}, LCSC["sw_power"], "Switch:SW_SPDT",
             note="power switch, 300 mA contacts, common pin 2"),
        Part("JP2", "switch bypass", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
             {1: ("A", "BAT+"), 2: ("B", "VBAT")}, symbol="Jumper:SolderJumper_2_Open",
             note="close if the switch is unusable"),
        r0603("R105", "10M", LCSC["r10M"], "VBAT", "BAT_SENSE", "divider 10M / 10M -> firmware 10000 / 20000"),
        r0603("R106", "10M", LCSC["r10M"], "BAT_SENSE", "GND"),
        c0603("C104", "10nF", LCSC["c10n"], "BAT_SENSE", "GND", "charge reservoir for the ADC (high-impedance divider)"),
        # --- 3.3 V regulator (BlueMicro840 U3)
        Part("U3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
             {1: ("VIN", "VIN"), 2: ("GND", "GND"), 3: ("EN", "VIN"), 4: ("NC", None), 5: ("VOUT", "3V3")},
             LCSC["ap2112k"], "Regulator_Linear:AP2112K-3.3", note="EN tied to VIN: always on"),
        c0603("C103", "10uF", LCSC["c10u"], "3V3", "GND", "at the module's VDD / VDDH pins"),
        c0603("C109", "100nF", LCSC["c100n"], "3V3", "GND", "at the module's VDD pin (deviation 11)"),
        c0603("C108", "1uF", LCSC["c1u"], "3V3", "GND", "regulator output (deviation 11)"),
        # --- 32.768 kHz crystal (BlueMicro840 Y2 / C1 / C2)
        Part("Y1", "32.768kHz", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm", {1: ("1", "XL1"), 2: ("2", "XL2")},
             LCSC["xtal"], "Device:Crystal"),
        c0603("C105", "18pF", LCSC["c18p"], "XL1", "GND", "18 pF centres the 12.5 pF load (BlueMicro840: 22 pF)"),
        c0603("C106", "18pF", LCSC["c18p"], "XL2", "GND"),
        # --- status LED on P1.04 (bootloader LED_PRIMARY_PIN, active high) and reset button
        Part("D103", "LED red", "LED_SMD:LED_0603_1608Metric", {1: ("K", "LED_RED_K"), 2: ("A", "LED_RED")},
             LCSC["led_red"], "Device:LED"),
        r0603("R107", "1k", LCSC["r1k"], "LED_RED_K", "GND"),
        Part("SW102", "reset", "lcsc:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5",
             {1: ("1", "RESET"), 2: ("2", None), 3: ("3", None), 4: ("4", "GND")}, LCSC["sw_reset"], "lira:SW_PUSH_4",
             note="pads 1 (-3,-1.85) and 4 (+3,+1.85) are diagonal: the contact, whichever adjacent pair is joined inside"),
        # --- test points (1.5 mm pads on the bottom side)
        # SWD: the five pads in one 2.54 mm column (a pogo-pin clip reaches them all), 1 mm pads
        tp("TP1", "SWDIO", "1.0"), tp("TP2", "SWCLK", "1.0"), tp("TP3", "3V3", "1.0"), tp("TP4", "GND", "1.0"),
        tp("TP5", "RESET", "1.0"),
        tp("TP6", "VBUS"), tp("TP7", "VBAT"), tp("TP8", "VIN"),
    ] + audio()


AUDIO_DEVIATIONS = [
    "Supply: VBUS through a TPS22919 load switch (soft start 1.3 ms, output discharge) to AUD_5V, ON = P1.02 with "
    "a 100k pull-down: the sound card is powered only in USB mode (firmware src/audio_gate.rs). A hard switch-on "
    "would dip VBUS enough to reset the hub (CH334 datasheet 6.1).",
    "Headphones: a TPA6132A2 DirectPath amplifier after LOL / LOR (demo board: 100 uF + 39R straight to the jack): "
    "about 0 ohm output impedance, no coupling capacitors, 0 dB gain (-6 dB with JP3 closed, for very sensitive "
    "earphones). Inputs single-ended through 1 uF (8 Hz); EN about 0.25 s after the supply (1M + 470 nF from P1.02) "
    "and off at once through a Schottky. The switch's output discharge goes through 1k (TPS22919 9.2.2.2): the 5 V falls in "
    "about 3 ms, so the amplifier is off before the codec loses its supply (TPA6132A2 p.12, no pop).",
    "Microphone: bias 1.2k + 2.2k (demo board 2.2k + 8.2k, for PC microphones) for phone headsets (Android: "
    "1.8-2.9 V through 2.2k); 1k in series before MICIN against the step when a plug goes in.",
    "The demo board's two 10 nF capacitors DVDD - DREG18 and DVDD - DREG33 ('close to IC', for ESD) are fitted.",
    "The amplifier's SGND (pin 15) is grounded at the amplifier (its ground pad and a via into the top ground plane), "
    "not on a track of its own to the jack's ground pin as TI suggests (datasheet 10.3): with both layers poured "
    "the difference is a few millivolts.",
    "The four mode jumpers are also strapped with 10k (MODE/ADSEL low, PWRSEL/MSEL high to DREG33) on top of the "
    "chip's internal pulls. D105-D107 are bidirectional ESD clamps (PESD5V0S1BA) on the jack's left, right and "
    "microphone contacts: a DirectPath output swings below GND, so the clamp must be bidirectional.",
]


def audio():
    """The sound card: CH334P USB 2.0 hub between the receptacle and the module, CM108B USB audio codec on a hub port,
    TPA6132A2 headphone amplifier, 3.5 mm headset jack (CTIA: tip = left, ring 1 = right, ring 2 = ground, sleeve =
    microphone). The codec and the amplifier run from AUD_5V, switched by a TPS22919 from P1.02."""
    hub = {1: ("XO", "HUB_XO"), 2: ("XI", "HUB_XI"), 3: ("DM4", None), 4: ("DP4", None),
           5: ("DM3", "MCU_DN"), 6: ("DP3", "MCU_DP"), 7: ("DM2", "AUD_DN"), 8: ("DP2", "AUD_DP"), 9: ("DM1", None),
           10: ("DP1", None), 11: ("DMU", "USB_DN"), 12: ("DPU", "USB_DP"), 13: ("RESET#/CDP", None),
           14: ("PGANG", None), 15: ("V5", "VBUS"), 16: ("VDD33", "HUB_3V3"), 17: ("GND", "GND")}
    names = {1: "SPDIFO", 2: "DR", 3: "DW", 4: "SK", 5: "CS", 6: "MUTER", 7: "PWRSEL", 8: "DREG18", 9: "DREG33",
             10: "MODE", 11: "NC", 12: "LEDO", 13: "GPIO3", 14: "DVSS", 15: "GPIO4", 16: "SDIN", 17: "ADSCLK",
             18: "MUTEP", 19: "ADLRCK", 20: "ADMCLK", 21: "LEDR", 22: "ADSEL", 23: "TEST", 24: "AVSS", 25: "VBIAS",
             26: "VREF", 27: "MICIN", 28: "NC", 29: "AVDD", 30: "LOL", 31: "LOBS", 32: "LOR", 33: "AVSS", 34: "AVDD",
             35: "DVDD", 36: "DVSS", 37: "AREG36", 38: "MSEL", 39: "VOLUP", 40: "PDSW", 41: "USBDP", 42: "USBDM",
             43: "GPIO1", 44: "SDOUT", 45: "DAMCLK", 46: "DALRCK", 47: "DASCLK", 48: "VOLDN"}
    # the four mode jumpers are strapped to their datasheet-defined levels with 10k on top of the chip's internal
    # pulls: MODE/ADSEL low = headset mode (playback + record) and internal ADC; PWRSEL/MSEL high (to DREG33, so
    # they are only driven while the codec is on) = 100 mA bus-powered and mixer enabled. Every other unlisted pin
    # is left open (outputs / N.C. / unused audio functions).
    nets = {7: "CM_PWRSEL", 8: "DREG18", 9: "DREG33", 10: "CM_MODE", 14: "GND", 22: "CM_ADSEL", 23: "GND",
            24: "GND", 25: "VBIAS", 26: "VREF", 27: "MICIN", 29: "AUD_AVDD", 30: "LOL", 31: "LOBS", 32: "LOR",
            33: "GND", 34: "AUD_AVDD", 35: "AUD_DVDD", 36: "GND", 37: "AREG36", 38: "CM_MSEL", 41: "CM_DP",
            42: "CM_DN"}
    codec = {n: (names[n], nets.get(n)) for n in names}
    amp = {1: ("INL-", "AMP_INL"), 2: ("INL+", "GND"), 3: ("INR+", "GND"), 4: ("INR-", "AMP_INR"),
           5: ("OUTR", "HPR2"), 6: ("G0", "AMP_G0"), 7: ("G1", "GND"), 8: ("HPVSS", "AMP_VSS"), 9: ("CPN", "AMP_CPN"),
           10: ("PGND", "GND"), 11: ("CPP", "AMP_CPP"), 12: ("HPVDD", "AMP_VDDH"), 13: ("EN", "AMP_EN"),
           14: ("VDD", "AUD_5V"), 15: ("SGND", "GND"), 16: ("OUTL", "HPL2"), 17: ("EP", "GND")}
    return [
        # --- hub (CH334P datasheet V2.91): 12 MHz crystal without load capacitors (they are inside the chip)
        Part("U5", "CH334P", "Package_DFN_QFN:WCH_QFN-16-1EP_3x3mm_P0.5mm_EP1.8x1.8mm", hub, LCSC["ch334p"],
             "lira:CH334P", note="USB 2.0 hub: upstream to the receptacle, port 3 module, port 2 sound card"),
        Part("Y2", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
             {1: ("1", "HUB_XI"), 2: ("G", "GND"), 3: ("3", "HUB_XO"), 4: ("G", "GND")}, LCSC["xtal12"],
             "Device:Crystal_GND24", note="no load capacitors: the CH334 has them inside"),
        c0603("C110", "1uF", LCSC["c1u"], "VBUS", "GND", "hub V5 input"),
        c0603("C111", "10uF", LCSC["c10u"], "HUB_3V3", "GND", "hub VDD33 (internal regulator output)"),
        c0603("C112", "100nF", LCSC["c100n"], "HUB_3V3", "GND", "hub VDD33"),
        # --- codec (CM108B): USB through 22R, supplies from VBUS through ferrite beads
        Part("U6", "CM108B", "Package_QFP:LQFP-48_7x7mm_P0.5mm", codec, LCSC["cm108b"], "lira:CM108B",
             note="USB audio codec, crystal-free; operating 0-70 C"),
        r0603("R110", "22", LCSC["r22"], "AUD_DP", "CM_DP", "series resistor at the codec's D+"),
        r0603("R111", "22", LCSC["r22"], "AUD_DN", "CM_DN", "series resistor at the codec's D-"),
        # --- the sound card's 5 V: on only in USB mode (TPS22919, soft start; QOD through 1k for a slow fall)
        Part("U8", "TPS22919", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
             {1: ("IN", "VBUS"), 2: ("GND", "GND"), 3: ("ON", "AUD_EN"), 4: ("NC", None), 5: ("QOD", "AUD_QOD"),
              6: ("VOUT", "AUD_5V")}, LCSC["tps22919"], "lira:TPS22919",
             note="load switch, ON from P1.02: sound card on only in USB mode"),
        c0603("C130", "1uF", LCSC["c1u"], "VBUS", "GND", "load switch input"),
        r0603("R117", "100k", LCSC["r100k"], "AUD_EN", "GND", "keeps the sound card off while P1.02 floats"),
        r0603("R118", "1k", LCSC["r1k"], "AUD_QOD", "AUD_5V", "output discharge: 5 V falls in ~3 ms, after the amplifier's EN"),
        bead("L101", LCSC["bead"], "AUD_5V", "AUD_AVDD", "analog supply filter"),
        bead("L102", LCSC["bead"], "AUD_5V", "AUD_DVDD", "digital supply filter"),
        c0603("C113", "10uF", LCSC["c10u"], "AUD_5V", "GND", "bulk on the switched 5 V"),
        c0603("C114", "100nF", LCSC["c100n"], "AUD_5V", "GND"),
        c0603("C115", "100nF", LCSC["c100n"], "AUD_DVDD", "GND", "at DVDD (pin 35)"),
        c0603("C116", "4.7uF", LCSC["c4u7"], "AUD_DVDD", "GND"),
        c0603("C117", "100nF", LCSC["c100n"], "AUD_AVDD", "GND", "at AVDD (pin 34)"),
        c0603("C118", "1uF", LCSC["c1u"], "DREG18", "GND", "1.8 V core regulator"),
        c0603("C119", "100nF", LCSC["c100n"], "DREG33", "GND", "3.3 V I/O regulator"),
        c0603("C120", "10uF", LCSC["c10u"], "AREG36", "GND", "3.6 V analog regulator"),
        c0603("C121", "10uF", LCSC["c10u"], "VREF", "GND", "bandgap reference"),
        c0603("C122", "10uF", LCSC["c10u"], "LOBS", "GND", "line-out bias"),
        c0603("C138", "10nF", LCSC["c10n"], "AUD_DVDD", "DREG18", "demo board C24, close to the codec (ESD)"),
        c0603("C139", "10nF", LCSC["c10n"], "AUD_DVDD", "DREG33", "demo board C23, close to the codec (ESD)"),
        # explicit straps on the mode jumpers (belt and braces on the internal pulls, p.7-8)
        r0603("R120", "10k", LCSC["r10k"], "CM_MODE", "GND", "MODE low: headset mode (p.7)"),
        r0603("R121", "10k", LCSC["r10k"], "CM_ADSEL", "GND", "ADSEL low: internal ADC (p.8)"),
        r0603("R122", "10k", LCSC["r10k"], "CM_PWRSEL", "DREG33", "PWRSEL high: 100 mA bus-powered (p.7)"),
        r0603("R123", "10k", LCSC["r10k"], "CM_MSEL", "DREG33", "MSEL high: mixer enabled (p.8)"),
        # --- headphone amplifier (TPA6132A2, DirectPath: outputs at 0 V, no coupling capacitors)
        Part("U7", "TPA6132A2", "Package_DFN_QFN:WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm", amp, LCSC["tpa6132"],
             "lira:TPA6132A2", note="headphone amplifier, 25 mW into 16 ohm; gain 0 dB, -6 dB with JP3 closed"),
        c0603("C123", "1uF", LCSC["c1u"], "LOL", "AMP_INL", "left input coupling (19.8k: 8 Hz)"),
        c0603("C126", "1uF", LCSC["c1u"], "LOR", "AMP_INR", "right input coupling"),
        c0603("C133", "2.2uF", LCSC["c2u2"], "AUD_5V", "GND", "amplifier VDD, within 5 mm of the pin"),
        c0603("C134", "2.2uF", LCSC["c2u2"], "AMP_VDDH", "GND", "HPVDD (internal supply, nothing else on it)"),
        c0603("C135", "1uF", LCSC["c1u"], "AMP_VSS", "GND", "HPVSS (charge pump output)"),
        c0603("C136", "1uF", LCSC["c1u"], "AMP_CPP", "AMP_CPN", "charge pump flying capacitor"),
        r0603("R112", "100k", LCSC["r100k"], "AUD_5V", "AMP_G0", "G0 high: 0 dB"),
        Part("JP3", "-6 dB", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
             {1: ("A", "AMP_G0"), 2: ("B", "GND")}, symbol="Jumper:SolderJumper_2_Open",
             note="closed: amplifier gain -6 dB, for very sensitive earphones"),
        r0603("R113", "1M", LCSC["r1M"], "AUD_EN", "AMP_EN", "amplifier on about 0.25 s after the supply"),
        c0603("C137", "470nF", LCSC["c470n"], "AMP_EN", "GND"),
        Part("D104", "B5819W", "Diode_SMD:D_SOD-123", {1: ("K", "AUD_EN"), 2: ("A", "AMP_EN")}, LCSC["b5819w"],
             "Device:D_Schottky", note="amplifier off at once when the sound card is switched off"),
        bead("L103", LCSC["bead"], "HPL2", "HP_L"),
        c0603("C124", "100pF", LCSC["c100p"], "HP_L", "GND"),
        bead("L104", LCSC["bead"], "HPR2", "HP_R"),
        c0603("C125", "100pF", LCSC["c100p"], "HP_R", "GND"),
        # --- microphone: bias 1.2k + 4.7 uF filter + 2.2k, 1k + 1 uF into MICIN, 100 pF at the jack
        r0603("R114", "1.2k", LCSC["r1k2"], "VBIAS", "MICB", "microphone bias"),
        c0603("C127", "4.7uF", LCSC["c4u7"], "MICB", "GND", "bias filter"),
        r0603("R115", "2.2k", LCSC["r2k2"], "MICB", "MIC", "bias resistor of the microphone (phone headsets)"),
        c0603("C128", "100pF", LCSC["c100p"], "MIC", "GND"),
        r0603("R116", "1k", LCSC["r1k"], "MIC", "MICR", "limits the step into MICIN when a plug goes in"),
        c0603("C129", "1uF", LCSC["c1u"], "MICR", "MICIN", "microphone coupling"),
        Part("J3", "PJ-320D-4A", "Connector_Audio:Jack_3.5mm_KoreanHropartsElec_PJ-320D-4A_Horizontal",
             {"T": ("T", "HP_L"), "R1": ("R1", "HP_R"), "R2": ("R2", "GND"), "S": ("S", "MIC")}, LCSC["jack"],
             "Connector_Audio:AudioJack4", note="3.5 mm headset jack, CTIA: tip L, ring 1 R, ring 2 GND, sleeve mic"),
        # ESD clamps at the jack (just right of it). Bidirectional: the TPA6132A2 DirectPath outputs swing below
        # GND, so a diode-to-GND array would clip the negative half of the waveform.
        two("D105", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "HP_L", "GND", "Device:D_TVS",
            note="bidirectional ESD clamp, left headphone output"),
        two("D106", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "HP_R", "GND", "Device:D_TVS",
            note="bidirectional ESD clamp, right headphone output"),
        two("D107", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "MIC", "GND", "Device:D_TVS",
            note="ESD clamp, microphone contact"),
    ]


def matrix(keys):
    """Switches and diodes of the key matrix (col2row: column -> switch -> diode -> row)."""
    parts = []
    for i, k in enumerate(sorted(keys, key=lambda k: (k.row, k.col)), start=1):
        col, row, sd = "COL%d" % k.col, "ROW%d" % k.row, "SD%d" % i
        size = max(k.w, k.h)
        fp = "Switch_Keyboard_Hotswap_Kailh:SW_Hotswap_Kailh_MX_%.2fu%s" % (size, "_90deg" if k.h > k.w else "")
        parts.append(Part("SW%d" % i, k.label, fp, {1: ("1", col), 2: ("2", sd)}, LCSC["socket"], "Switch:SW_Push",
                          note="(%d,%d)" % (k.row, k.col)))
        parts.append(Part("D%d" % i, "1N4148W", "Diode_SMD:D_SOD-123", {1: ("K", row), 2: ("A", sd)}, LCSC["diode"],
                          "Device:D"))
    return parts


def to_json(parts, extra=None):
    """Netlist for the automated checks: parts with pin names and nets, and nets with members."""
    out = {"parts": {}, "nets": {}}
    for p in parts:
        if p.pcb_only:
            continue
        out["parts"][p.ref] = {"value": p.value, "footprint": p.footprint, "lcsc": p.lcsc, "dnp": p.dnp,
                               "note": p.note, "pins": {n: {"name": v[0], "net": v[1]} for n, v in p.pins.items()}}
        for n, (name, net) in p.pins.items():
            if net:
                out["nets"].setdefault(net, []).append([p.ref, n])
    out["nets"] = {k: sorted(v) for k, v in sorted(out["nets"].items())}
    if extra:
        out.update(extra)
    return out
