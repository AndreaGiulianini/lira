"""The circuit of Lira USB as data: every part with its pins and the net each pin is on.

USB-only 40% + left-numpad keyboard, RP2040, with a built-in USB headset sound card and headphone
amplifier. No battery, no charger, no Bluetooth, no antenna.

The RP2040 section follows Raspberry Pi's "Hardware design with RP2040" (minimal design example):
12 MHz crystal (ABM8-272-T3) with 15 pF load caps and a 1 kohm series resistor; W25Q128 QSPI flash
wired straight to the QSPI pins with a 10 kohm pull-up on QSPI_SS and a 1 kohm BOOTSEL resistor;
100 nF on every supply pin with 1 uF on VREG_IN/VREG_OUT; TESTEN to GND; 27 ohm series on USB DP/DM.

The sound card and the key matrix are the same as on the nRF52840 Lira (C-Media CM108B reference,
CH334P hub, TPA6132A2 amplifier); the TPS22919 audio load switch is dropped because the board is
USB only - the codec and amplifier are on whenever the cable is plugged.

This is the single description of connectivity. From it come the PCB nets, the schematic and the
JSON netlist the automated checks read. Pin numbers follow the KiCad symbol MCU_RaspberryPi:RP2040
(== the datasheet QFN-56 pinout).
"""

# ----------------------------------------------------------------------------------------------- RP2040
RP_PINS = {
    1: "IOVDD", 2: "GPIO0", 3: "GPIO1", 4: "GPIO2", 5: "GPIO3", 6: "GPIO4", 7: "GPIO5", 8: "GPIO6",
    9: "GPIO7", 10: "IOVDD", 11: "GPIO8", 12: "GPIO9", 13: "GPIO10", 14: "GPIO11", 15: "GPIO12",
    16: "GPIO13", 17: "GPIO14", 18: "GPIO15", 19: "TESTEN", 20: "XIN", 21: "XOUT", 22: "IOVDD",
    23: "DVDD", 24: "SWCLK", 25: "SWDIO", 26: "RUN", 27: "GPIO16", 28: "GPIO17", 29: "GPIO18",
    30: "GPIO19", 31: "GPIO20", 32: "GPIO21", 33: "IOVDD", 34: "GPIO22", 35: "GPIO23", 36: "GPIO24",
    37: "GPIO25", 38: "GPIO26/ADC0", 39: "GPIO27/ADC1", 40: "GPIO28/ADC2", 41: "GPIO29/ADC3",
    42: "IOVDD", 43: "ADC_AVDD", 44: "VREG_IN", 45: "VREG_OUT", 46: "USB_DM", 47: "USB_DP",
    48: "USB_VDD", 49: "IOVDD", 50: "DVDD", 51: "QSPI_SD3", 52: "QSPI_SCLK", 53: "QSPI_SD0",
    54: "QSPI_SD2", 55: "QSPI_SD1", 56: "QSPI_SS", 57: "GND",
}
# pads with a fixed role (net name); the GPIO pads are filled from the key matrix
RP_FIXED = {
    1: "3V3", 10: "3V3", 22: "3V3", 33: "3V3", 42: "3V3", 48: "3V3", 43: "3V3", 49: "3V3",
    19: "GND", 20: "XIN", 21: "XOUT", 23: "VREG_VOUT", 50: "VREG_VOUT", 45: "VREG_VOUT",
    24: "SWCLK", 25: "SWDIO", 26: "RUN", 46: "RP_DM", 47: "RP_DP",
    51: "QSPI_SD3", 52: "QSPI_SCLK", 53: "QSPI_SD0", 54: "QSPI_SD2", 55: "QSPI_SD1", 56: "QSPI_SS",
    57: "GND",
}
# the 30 GPIO pads, edge pads first (a QFN has no inner pads: every pad is reachable on the bottom)
RP_GPIO_EDGE = (2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 27, 28, 29, 30, 31, 32, 34, 35, 36,
                37, 38, 39, 40, 41)
RP_GPIO = RP_GPIO_EDGE
RP_INNER_GPIO = ()


def rp_pin(pad):
    """'GPIO26/ADC0' -> 'GPIO26'."""
    return RP_PINS[pad].split("/")[0]


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


def tp(ref, net, d="1.0"):
    return Part(ref, net, "TestPoint:TestPoint_Pad_D%smm" % d, {1: ("1", net)}, symbol="Connector:TestPoint")


LCSC = {
    # RP2040 section
    "rp2040": "C2040", "flash": "C97521", "xtal12": "C20625731", "ap2112k": "C51118",
    "usbc": "C165948", "usblc6": "C7519", "jack": "C95562",
    "r27": "C25190", "c15p": "C1644", "r5k1": "C23186", "led_red": "C2286", "sw_reset": "C318884",
    # sound card (same parts as the nRF board)
    "ch334p": "C5373042", "cm108b": "C371347", "tpa6132": "C69901", "xtal_hub": "C9002", "esd_jack": "C19224",
    "bead": "C1002", "c2u2": "C23630", "c4u7": "C19666", "c10n": "C57112", "c100p": "C14858",
    "r22": "C23345", "r2k2": "C4190", "r1k2": "C22765",
    # shared passives
    "r100k": "C25803", "r1k": "C21190", "r10k": "C25804", "c100n": "C14663", "c1u": "C15849", "c10u": "C19702",
    "socket": "C2803348", "diode": "C81598",
}

DEVIATIONS = [
    "USB only (deviation from the nRF52840 Lira): no Ebyte E73 module, no Bluetooth, no Li-Po cell, no "
    "charger, no power switch, no 32.768 kHz crystal, no antenna keep-out. Everything runs from the "
    "USB-C cable.",
    "RP2040 instead of the nRF52840: bare QFN-56 with an external 12 MHz crystal and a W25Q128 QSPI "
    "flash, per Raspberry Pi's 'Hardware design with RP2040'. 27 ohm series resistors on USB DP/DM "
    "(datasheet 1.4.2). UF2 flashing over USB (BOOTSEL / RUN buttons), SWD pads kept for recovery.",
    "The sound card (CH334P hub, CM108B codec, TPA6132A2 amplifier, headset jack) is the same as on the "
    "nRF board; the TPS22919 load switch and the audio-gate firmware are gone: the codec and amplifier "
    "are on whenever the cable is plugged, and the amplifier EN is tied high.",
]


# ------------------------------------------------------------------------------------------------------ parts

def _usbc_pins():
    p = {n: ("VBUS", "VBUS") for n in ("A4", "A9", "B4", "B9")}
    p.update({n: ("GND", "GND") for n in ("A1", "A12", "B1", "B12")})
    p.update({"A5": ("CC1", "CC1"), "B5": ("CC2", "CC2"), "A6": ("D+", "USB_DP"), "B6": ("D+", "USB_DP"),
              "A7": ("D-", "USB_DN"), "B7": ("D-", "USB_DN"), "A8": ("SBU1", None), "B8": ("SBU2", None),
              "SH": ("SHIELD", "GND")})
    return p


def rp2040(gpio=None, status_led=37):
    """The RP2040 minimum design, the USB-C receptacle with ESD, and the 3.3 V regulator."""
    gpio = dict(gpio or {})
    gpio.setdefault(status_led, "LED_RED")
    u1 = {pad: (name, gpio.get(pad, RP_FIXED.get(pad))) for pad, name in RP_PINS.items()}
    parts = [
        Part("U1", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", u1, LCSC["rp2040"],
             "lira:RP2040", note="RP2040, 3.3 V I/O, 1.1 V core from the internal regulator"),
        # one 100 nF per supply pin, 1 uF on VREG in/out
        *[c0603("C%02d" % (i + 1), "100nF", LCSC["c100n"], "3V3", "GND", "IOVDD %d" % p)
          for i, p in enumerate(p for p in (1, 10, 22, 33, 42, 49))],
        c0603("C07", "100nF", LCSC["c100n"], "VREG_VOUT", "GND", "DVDD 23"),
        c0603("C08", "100nF", LCSC["c100n"], "VREG_VOUT", "GND", "DVDD 50"),
        c0603("C09", "100nF", LCSC["c100n"], "3V3", "GND", "USB_VDD 48"),
        c0603("C10", "100nF", LCSC["c100n"], "3V3", "GND", "ADC_AVDD 43"),
        c0603("C11", "1uF", LCSC["c1u"], "3V3", "GND", "VREG_IN"),
        c0603("C12", "1uF", LCSC["c1u"], "VREG_VOUT", "GND", "VREG_VOUT (1.1 V core)"),
        # 12 MHz crystal (ABM8-272-T3: CL 10 pF, ESR <= 50 ohm) with the HDG's load caps and series resistor
        Part("Y1", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
             {1: ("1", "XIN"), 2: ("G", "GND"), 3: ("3", "XOUT_C"), 4: ("G", "GND")}, LCSC["xtal12"],
             "Device:Crystal_GND24", note="Abracon ABM8-272-T3"),
        c0603("C13", "15pF", LCSC["c15p"], "XIN", "GND"), c0603("C14", "15pF", LCSC["c15p"], "XOUT_C", "GND"),
        r0603("R01", "1k", LCSC["r1k"], "XOUT_C", "XOUT", "series damping (HDG R5)"),
        # QSPI flash
        Part("U2", "W25Q128JVS", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
             {1: ("CS", "QSPI_SS"), 2: ("DO/IO1", "QSPI_SD1"), 3: ("WP/IO2", "QSPI_SD2"), 4: ("GND", "GND"),
              5: ("DI/IO0", "QSPI_SD0"), 6: ("CLK", "QSPI_SCLK"), 7: ("HOLD/IO3", "QSPI_SD3"), 8: ("VCC", "3V3")},
             LCSC["flash"], "Memory_Flash:W25Q128JVS", note="close to U1, short QSPI tracks"),
        c0603("C15", "100nF", LCSC["c100n"], "3V3", "GND", "flash decoupling"),
        r0603("R02", "10k", LCSC["r10k"], "3V3", "QSPI_SS", "QSPI_SS pull-up"),
        r0603("R03", "1k", LCSC["r1k"], "BOOTSEL", "QSPI_SS", "BOOTSEL series resistor"),
        Part("SW101", "BOOTSEL", "Button_Switch_SMD:SW_SPST_TL3342", {1: ("1", "BOOTSEL"), 2: ("2", "GND")},
             LCSC["sw_reset"], "Switch:SW_Push"),
        r0603("R04", "10k", LCSC["r10k"], "3V3", "RUN", "RUN pull-up"), c0603("C16", "100nF", LCSC["c100n"], "RUN", "GND"),
        Part("SW102", "RUN", "Button_Switch_SMD:SW_SPST_TL3342", {1: ("1", "RUN"), 2: ("2", "GND")},
             LCSC["sw_reset"], "Switch:SW_Push"),
        # USB to the hub's downstream port 3: 27 ohm series, required by the datasheet
        r0603("R05", "27", LCSC["r27"], "RP_DP", "MCU_DP"), r0603("R06", "27", LCSC["r27"], "RP_DM", "MCU_DN"),
        # test pads
        tp("TP1", "SWCLK"), tp("TP2", "SWDIO"), tp("TP3", "3V3"), tp("TP4", "GND"), tp("TP5", "VBUS"),
        # status LED (Caps Lock / bootloader) on GPIO25
        Part("D60", "LED red", "LED_SMD:LED_0603_1608Metric", {1: ("K", "LED_RED_K"), 2: ("A", "LED_RED")},
             LCSC["led_red"], "Device:LED"),
        r0603("R07", "1k", LCSC["r1k"], "LED_RED_K", "GND"),
        # USB-C receptacle, ESD and the 3.3 V regulator
        Part("J1", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", _usbc_pins(), LCSC["usbc"],
             "Connector:USB_C_Receptacle_USB2.0_16P"),
        r0603("R08", "5.1k", LCSC["r5k1"], "CC1", "GND"), r0603("R09", "5.1k", LCSC["r5k1"], "CC2", "GND"),
        Part("U3", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
             {1: ("I/O1", "USB_DP"), 2: ("GND", "GND"), 3: ("I/O2", "USB_DN"), 4: ("I/O2", "USB_DN"),
              5: ("VBUS", "VBUS"), 6: ("I/O1", "USB_DP")}, LCSC["usblc6"], "Power_Protection:USBLC6-2SC6"),
        Part("U4", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
             {1: ("VIN", "VBUS"), 2: ("GND", "GND"), 3: ("EN", "VBUS"), 4: ("NC", None), 5: ("VOUT", "3V3")},
             LCSC["ap2112k"], "Regulator_Linear:AP2112K-3.3"),
        c0603("C17", "1uF", LCSC["c1u"], "VBUS", "GND"), c0603("C18", "1uF", LCSC["c1u"], "3V3", "GND"),
        c0603("C19", "10uF", LCSC["c10u"], "3V3", "GND"),
    ]
    return parts


def audio():
    """The sound card: CH334P hub, CM108B codec, TPA6132A2 amplifier, headset jack. Same as the nRF board,
    with the TPS22919 load switch removed (VBUS feeds the codec and amplifier directly)."""
    hub = {1: ("XO", "HUB_XO"), 2: ("XI", "HUB_XI"), 3: ("DM4", None), 4: ("DP4", None),
           5: ("DM3", "MCU_DN"), 6: ("DP3", "MCU_DP"), 7: ("DM2", "AUD_DN"), 8: ("DP2", "AUD_DP"),
           9: ("DM1", None), 10: ("DP1", None), 11: ("DMU", "USB_DN"), 12: ("DPU", "USB_DP"),
           13: ("RESET#/CDP", None), 14: ("PGANG", None), 15: ("V5", "VBUS"), 16: ("VDD33", "HUB_3V3"),
           17: ("GND", "GND")}
    names = {1: "SPDIFO", 2: "DR", 3: "DW", 4: "SK", 5: "CS", 6: "MUTER", 7: "PWRSEL", 8: "DREG18",
             9: "DREG33", 10: "MODE", 11: "NC", 12: "LEDO", 13: "GPIO3", 14: "DVSS", 15: "GPIO4",
             16: "SDIN", 17: "ADSCLK", 18: "MUTEP", 19: "ADLRCK", 20: "ADMCLK", 21: "LEDR", 22: "ADSEL",
             23: "TEST", 24: "AVSS", 25: "VBIAS", 26: "VREF", 27: "MICIN", 28: "NC", 29: "AVDD", 30: "LOL",
             31: "LOBS", 32: "LOR", 33: "AVSS", 34: "AVDD", 35: "DVDD", 36: "DVSS", 37: "AREG36",
             38: "MSEL", 39: "VOLUP", 40: "PDSW", 41: "USBDP", 42: "USBDM", 43: "GPIO1", 44: "SDOUT",
             45: "DAMCLK", 46: "DALRCK", 47: "DASCLK", 48: "VOLDN"}
    nets = {7: "CM_PWRSEL", 8: "DREG18", 9: "DREG33", 10: "CM_MODE", 14: "GND", 22: "CM_ADSEL", 23: "GND",
            24: "GND", 25: "VBIAS", 26: "VREF", 27: "MICIN", 29: "AUD_AVDD", 30: "LOL", 31: "LOBS",
            32: "LOR", 33: "GND", 34: "AUD_AVDD", 35: "AUD_DVDD", 36: "GND", 37: "AREG36", 38: "CM_MSEL",
            41: "CM_DP", 42: "CM_DN"}
    codec = {n: (names[n], nets.get(n)) for n in names}
    amp = {1: ("INL-", "AMP_INL"), 2: ("INL+", "GND"), 3: ("INR+", "GND"), 4: ("INR-", "AMP_INR"),
           5: ("OUTR", "HPR2"), 6: ("G0", "AMP_G0"), 7: ("G1", "GND"), 8: ("HPVSS", "AMP_VSS"),
           9: ("CPN", "AMP_CPN"), 10: ("PGND", "GND"), 11: ("CPP", "AMP_CPP"), 12: ("HPVDD", "AMP_VDDH"),
           13: ("EN", "AMP_EN"), 14: ("VDD", "VBUS"), 15: ("SGND", "GND"), 16: ("OUTL", "HPL2"), 17: ("EP", "GND")}
    return [
        Part("U5", "CH334P", "Package_DFN_QFN:WCH_QFN-16-1EP_3x3mm_P0.5mm_EP1.8x1.8mm", hub, LCSC["ch334p"],
             "lira:CH334P", note="USB 2.0 hub: upstream from the receptacle, port 3 -> RP2040, port 2 -> codec"),
        Part("Y2", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
             {1: ("1", "HUB_XI"), 2: ("G", "GND"), 3: ("3", "HUB_XO"), 4: ("G", "GND")}, LCSC["xtal_hub"],
             "Device:Crystal_GND24", note="no load caps: the CH334 has them inside"),
        c0603("C110", "1uF", LCSC["c1u"], "VBUS", "GND"), c0603("C111", "10uF", LCSC["c10u"], "HUB_3V3", "GND"),
        c0603("C112", "100nF", LCSC["c100n"], "HUB_3V3", "GND"),
        Part("U6", "CM108B", "Package_QFP:LQFP-48_7x7mm_P0.5mm", codec, LCSC["cm108b"], "lira:CM108B"),
        r0603("R110", "22", LCSC["r22"], "AUD_DP", "CM_DP"), r0603("R111", "22", LCSC["r22"], "AUD_DN", "CM_DN"),
        bead("L101", LCSC["bead"], "VBUS", "AUD_AVDD"), bead("L102", LCSC["bead"], "VBUS", "AUD_DVDD"),
        c0603("C113", "10uF", LCSC["c10u"], "VBUS", "GND"), c0603("C114", "100nF", LCSC["c100n"], "VBUS", "GND"),
        c0603("C115", "100nF", LCSC["c100n"], "AUD_DVDD", "GND"), c0603("C116", "4.7uF", LCSC["c4u7"], "AUD_DVDD", "GND"),
        c0603("C117", "100nF", LCSC["c100n"], "AUD_AVDD", "GND"), c0603("C118", "1uF", LCSC["c1u"], "DREG18", "GND"),
        c0603("C119", "100nF", LCSC["c100n"], "DREG33", "GND"), c0603("C120", "10uF", LCSC["c10u"], "AREG36", "GND"),
        c0603("C121", "10uF", LCSC["c10u"], "VREF", "GND"), c0603("C122", "10uF", LCSC["c10u"], "LOBS", "GND"),
        c0603("C138", "10nF", LCSC["c10n"], "AUD_DVDD", "DREG18"), c0603("C139", "10nF", LCSC["c10n"], "AUD_DVDD", "DREG33"),
        r0603("R120", "10k", LCSC["r10k"], "CM_MODE", "GND"), r0603("R121", "10k", LCSC["r10k"], "CM_ADSEL", "GND"),
        r0603("R122", "10k", LCSC["r10k"], "CM_PWRSEL", "DREG33"), r0603("R123", "10k", LCSC["r10k"], "CM_MSEL", "DREG33"),
        Part("U7", "TPA6132A2", "Package_DFN_QFN:WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm", amp, LCSC["tpa6132"],
             "lira:TPA6132A2"),
        c0603("C123", "1uF", LCSC["c1u"], "LOL", "AMP_INL"), c0603("C126", "1uF", LCSC["c1u"], "LOR", "AMP_INR"),
        c0603("C133", "2.2uF", LCSC["c2u2"], "VBUS", "GND"), c0603("C134", "2.2uF", LCSC["c2u2"], "AMP_VDDH", "GND"),
        c0603("C135", "1uF", LCSC["c1u"], "AMP_VSS", "GND"), c0603("C136", "1uF", LCSC["c1u"], "AMP_CPP", "AMP_CPN"),
        r0603("R112", "100k", LCSC["r100k"], "VBUS", "AMP_G0", "G0 high: 0 dB"),
        Part("JP3", "-6 dB", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
             {1: ("A", "AMP_G0"), 2: ("B", "GND")}, symbol="Jumper:SolderJumper_2_Open"),
        r0603("R113", "100k", LCSC["r100k"], "VBUS", "AMP_EN", "amplifier EN tied high (USB only)"),
        bead("L103", LCSC["bead"], "HPL2", "HP_L"), c0603("C124", "100pF", LCSC["c100p"], "HP_L", "GND"),
        bead("L104", LCSC["bead"], "HPR2", "HP_R"), c0603("C125", "100pF", LCSC["c100p"], "HP_R", "GND"),
        r0603("R114", "1.2k", LCSC["r1k2"], "VBIAS", "MICB"), c0603("C127", "4.7uF", LCSC["c4u7"], "MICB", "GND"),
        r0603("R115", "2.2k", LCSC["r2k2"], "MICB", "MIC"), c0603("C128", "100pF", LCSC["c100p"], "MIC", "GND"),
        r0603("R116", "1k", LCSC["r1k"], "MIC", "MICR"), c0603("C129", "1uF", LCSC["c1u"], "MICR", "MICIN"),
        Part("J3", "PJ-320D-4A", "Connector_Audio:Jack_3.5mm_KoreanHropartsElec_PJ-320D-4A_Horizontal",
             {"T": ("T", "HP_L"), "R1": ("R1", "HP_R"), "R2": ("R2", "GND"), "S": ("S", "MIC")}, LCSC["jack"],
             "Connector_Audio:AudioJack4", note="3.5 mm headset jack, CTIA"),
        two("D105", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "HP_L", "GND", "Device:D_TVS"),
        two("D106", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "HP_R", "GND", "Device:D_TVS"),
        two("D107", "PESD5V0", "Diode_SMD:D_SOD-323", LCSC["esd_jack"], "MIC", "GND", "Device:D_TVS"),
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


def electronics(gpio=None):
    """Everything that is not the key matrix. gpio: {pad: net} for the matrix lines."""
    return rp2040(gpio) + audio()


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
