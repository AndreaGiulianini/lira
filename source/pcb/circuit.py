"""The circuit of Lira (wired, RP2040) as data: every part with its pins and the net each pin is on.

This is the single description of the connectivity. From it come:
  * the nets of the PCB (pcb/gen_pcb.py, pcb/electronics.py place these parts),
  * the schematic (pcb/gen_schematic.py),
  * the JSON netlist read by the independent checks (pcb/check_circuit.py),
  * the consistency check PCB == schematic == this file (pcb/verify_netlist.py).

This branch is the wired version of Lira: the same keyboard, case, plate and sound card as the wireless one (branch
main), but USB only, with no battery. With the cable always plugged in the radio, the cell, the charger and the power
path have nothing to do, so the nRF52840 module is replaced by a Raspberry Pi RP2040 with its own minimum circuit,
which follows Raspberry Pi's "Hardware design with RP2040" (minimal design example, the Pico's circuit): 12 MHz
crystal with 15 pF load capacitors and a 1k series resistor, a W25Q128 QSPI flash, 100 nF on every supply pin and
1 uF on the internal regulator's input and output, 27 ohm on USB D+ / D-, BOOTSEL and RUN buttons. Every difference
from the wireless board is listed in DEVIATIONS and printed on the schematic.

The built-in sound card (audio()) is the wireless board's, part for part: the USB-C receptacle feeds a WCH CH334P
hub, whose ports go to the RP2040 and to a C-Media CM108B USB audio codec (headphones + microphone on a 3.5 mm jack).
The codec section follows C-Media's CM108B/CM119B demo board v1.33 (sheet 4) and application notes v1.50. Its supply
switch is turned on by VBUS itself instead of a GPIO: the board is always in USB mode.
"""

# --------------------------------------------------------------------------------------------- Raspberry Pi RP2040
# Pad number -> pin name (RP2040 datasheet 1.4.1, QFN-56; == KiCad's MCU_RaspberryPi:RP2040 symbol).
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
# Pads with a fixed role (net name). The 1.1 V core supply: the internal regulator's output (VREG_VOUT) feeds both
# DVDD pins. TESTEN is grounded (datasheet: "connect to ground"). USB through 27 ohm to the hub's port 3.
RP_FIXED = {
    1: "3V3", 10: "3V3", 22: "3V3", 33: "3V3", 42: "3V3", 49: "3V3", 43: "3V3", 44: "3V3", 48: "3V3",
    23: "1V1", 45: "1V1", 50: "1V1", 19: "GND", 57: "GND", 20: "XIN", 21: "XOUT", 24: "SWCLK", 25: "SWDIO",
    26: "RESET", 46: "RP_DN", 47: "RP_DP", 51: "QSPI_SD3", 52: "QSPI_SCLK", 53: "QSPI_SD0", 54: "QSPI_SD2",
    55: "QSPI_SD1", 56: "QSPI_SS",
}
# The 30 GPIO pads; pcb/electronics.py gives the key matrix and the status LED the ones on the package's two sides
# that face along the strip (the matrix lines leave sideways), so that the fan-out does not cross itself.
RP_GPIO = tuple(p for p, n in sorted(RP_PINS.items()) if n.startswith("GPIO"))


def rp_pin(pad):
    """'GPIO26/ADC0' -> 'PIN_26' (the name RMK and embassy-rp use)."""
    return "PIN_" + RP_PINS[pad].split("/")[0][4:]


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


def button(ref, value, net, note):
    """TS-1187A 5.1 x 5.1 mm tact switch (as the wireless board's reset button): pads 1 and 4 are diagonal, the
    contact whichever adjacent pair is joined inside."""
    return Part(ref, value, "lcsc:SW-SMD_4P-L5.1-W5.1-P3.70-LS6.5-TL_H1.5",
                {1: ("1", net), 2: ("2", None), 3: ("3", None), 4: ("4", "GND")}, LCSC["sw_reset"], "lira:SW_PUSH_4",
                note=note)


LCSC = {
    "rp2040": "C2040", "flash": "C97521", "xtal_mcu": "C20625731", "ap2112k": "C51118", "usblc6": "C7519",
    "led_red": "C2286", "usbc": "C165948", "sw_reset": "C318884", "b5819w": "C8598",
    "r100k": "C25803", "r1k": "C21190", "r10k": "C25804", "r5k1": "C23186", "r27": "C25190",
    "c10u": "C19702", "c4u7": "C19666", "c15p": "C1644", "c100n": "C14663",
    "socket": "C2803348", "diode": "C81598",
    # sound card: hub, codec, jack, 12 MHz crystal, and the passives not used elsewhere
    "ch334p": "C5373042", "cm108b": "C371347", "jack": "C95562", "xtal12": "C9002",
    "c1u": "C15849", "c100p": "C14858", "r22": "C23345", "r2k2": "C4190", "bead": "C1002",
    "tps22919": "C2149796", "tpa6132": "C69901", "c2u2": "C23630", "c470n": "C1623", "c10n": "C57112",
    "r1M": "C22935", "r1k2": "C22765", "esd_jack": "C19224",
}

DEVIATIONS = [
    "USB only, no battery: no Ebyte E73 (nRF52840) module, no Bluetooth, no Li-Po cell, no charger (MCP73831), no power "
    "path (B5819W + SI2301), no power switch, no battery divider, no 32.768 kHz crystal, no antenna keep-out.",
    "Raspberry Pi RP2040 instead of the module, with the minimum circuit of Raspberry Pi's 'Hardware design with RP2040' "
    "(the Pico's): 12 MHz crystal ABM8-272-T3 (the one Raspberry Pi qualified) with 2 x 15 pF and 1k in series on "
    "XOUT; W25Q128JV QSPI flash (16 MB) with a 10k pull-up on QSPI_SS; 100 nF on each of the six IOVDD pins, on both "
    "DVDD, USB_VDD and ADC_AVDD, 1 uF on VREG_VIN and VREG_VOUT; the internal regulator makes the 1.1 V core supply; "
    "TESTEN grounded.",
    "USB: hub port 3 goes to the RP2040's USB_DP / USB_DM through 27 ohm series resistors (as on the Pico and in the "
    "design guide), instead of the module's D+ / D-.",
    "Programming: the RP2040's boot ROM is a USB drive (RPI-RP2) - no bootloader to flash with an SWD probe. A blank "
    "board starts in it; BOOT (SW101, QSPI_SS to GND through 1k) held while plugging the cable enters it again; "
    "RESET (SW102) pulls RUN low. The SWD pads stay for debugging.",
    "3.3 V regulator AP2112K-3.3 (the same as the wireless board) fed straight from VBUS: 1 uF in, 1 uF + 10 uF out.",
    "Status LED (red, Caps Lock) on an RP2040 GPIO, through 1k, as on the wireless board.",
    "Test points: SWD (SWCLK, SWDIO, RESET, GND) in one row in front of the RP2040, 3V3 behind it, VBUS; no VBAT / "
    "VIN.",
    "Sound card: the supply switch U8 is turned on by VBUS instead of a GPIO (the wireless board has it on only in USB "
    "mode; here it always is) and its pull-down is dropped. It still soft-starts the sound card's 5 V: its 17 uF are "
    "charged through the switch's controlled rise, not straight from the cable (only ~3 uF sit directly on VBUS). "
    "The amplifier's EN delay (1M + 470 nF) runs from VBUS too, and D104 drags EN down with VBUS on unplug.",
]


def rp2040(gpio=None):
    """The RP2040, its flash, crystal, decoupling, buttons, status LED and test points; the USB-C receptacle, its ESD
    array and the 3.3 V regulator. gpio: {RP2040 pad: net} for the key matrix and the status LED."""
    gpio = gpio or {}
    u1 = {}
    for pad, name in RP_PINS.items():
        if pad in RP_FIXED:
            u1[pad] = (name, RP_FIXED[pad])
        else:
            u1[pad] = (name, gpio.get(pad))  # a GPIO: matrix line, status LED, or unused (left open)
    usb = {}
    for p in ("A4", "A9", "B4", "B9"):
        usb[p] = ("VBUS", "VBUS")
    for p in ("A1", "A12", "B1", "B12"):
        usb[p] = ("GND", "GND")
    usb.update({"A5": ("CC1", "CC1"), "B5": ("CC2", "CC2"), "A6": ("D+", "USB_DP"), "B6": ("D+", "USB_DP"),
                "A7": ("D-", "USB_DN"), "B7": ("D-", "USB_DN"), "A8": ("SBU1", None), "B8": ("SBU2", None),
                "SH": ("SHIELD", "GND")})
    decoupling = [(1, "3V3"), (10, "3V3"), (22, "3V3"), (33, "3V3"), (42, "3V3"), (49, "3V3"), (48, "3V3"),
                  (43, "3V3"), (23, "1V1"), (50, "1V1")]
    return [
        Part("U1", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", u1, LCSC["rp2040"],
             "lira:RP2040", note="RP2040: 3.3 V I/O, 1.1 V core from its own regulator (VREG_VOUT -> DVDD)"),
        # --- 100 nF at every supply pin (one per pin, next to it), 1 uF at the regulator's input and output
        *[c0603("C%d" % i, "100nF", LCSC["c100n"], net, "GND", "at %s (pin %d)" % (RP_PINS[pin], pin))
          for i, (pin, net) in enumerate(decoupling, start=1)],
        c0603("C11", "1uF", LCSC["c1u"], "3V3", "GND", "at VREG_VIN (pin 44)"),
        c0603("C12", "1uF", LCSC["c1u"], "1V1", "GND", "at VREG_VOUT (pin 45)"),
        # --- 12 MHz crystal (Hardware design with RP2040 2.3.1: ABM8-272-T3, CL 10 pF, 2 x 15 pF, 1k on XOUT)
        Part("Y1", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
             {1: ("1", "XIN"), 2: ("G", "GND"), 3: ("3", "XOUT_X"), 4: ("G", "GND")}, LCSC["xtal_mcu"],
             "Device:Crystal_GND24", note="Abracon ABM8-272-T3: CL 10 pF, ESR <= 50 ohm"),
        c0603("C13", "15pF", LCSC["c15p"], "XIN", "GND", "load: 2 x (10 pF - ~2.5 pF of board and pin)"),
        c0603("C14", "15pF", LCSC["c15p"], "XOUT_X", "GND"),
        r0603("R1", "1k", LCSC["r1k"], "XOUT", "XOUT_X", "limits the crystal's drive level"),
        # --- QSPI flash: W25Q128JV, 16 MB (the boot ROM's default second stage drives it)
        Part("U2", "W25Q128JVS", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
             {1: ("/CS", "QSPI_SS"), 2: ("DO(IO1)", "QSPI_SD1"), 3: ("/WP(IO2)", "QSPI_SD2"), 4: ("GND", "GND"),
              5: ("DI(IO0)", "QSPI_SD0"), 6: ("CLK", "QSPI_SCLK"), 7: ("/HOLD(IO3)", "QSPI_SD3"), 8: ("VCC", "3V3")},
             LCSC["flash"], "Memory_Flash:W25Q128JVS", note="W25Q128JVSIQ, SOIC-8 208 mil, next to the QSPI pins"),
        c0603("C15", "100nF", LCSC["c100n"], "3V3", "GND", "at the flash's VCC"),
        r0603("R2", "10k", LCSC["r10k"], "3V3", "QSPI_SS", "keeps the flash deselected while the RP2040 starts"),
        # --- BOOT: QSPI_SS low at reset -> USB boot ROM (the Pico's BOOTSEL, through 1k as in the design guide)
        r0603("R3", "1k", LCSC["r1k"], "QSPI_SS", "BOOT"),
        button("SW101", "BOOT", "BOOT", "hold while plugging the cable (or pressing RESET): USB drive RPI-RP2"),
        # --- RESET: RUN held high by 10k (datasheet: tie it to IOVDD if there is no reset), button to GND
        r0603("R4", "10k", LCSC["r10k"], "3V3", "RESET", "RUN pull-up"),
        button("SW102", "RESET", "RESET", "pulls RUN low: the RP2040 restarts"),
        # --- USB: the RP2040 on hub port 3 through 27 ohm (as on the Pico and in the design guide)
        r0603("R5", "27", LCSC["r27"], "RP_DP", "MCU_DP", "USB D+ series resistor, at the RP2040"),
        r0603("R6", "27", LCSC["r27"], "RP_DN", "MCU_DN", "USB D- series resistor, at the RP2040"),
        # --- USB-C receptacle (sink), ESD array (as on the wireless board)
        Part("J1", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12", usb, LCSC["usbc"],
             "Connector:USB_C_Receptacle_USB2.0_16P"),
        r0603("R108", "5.1k", LCSC["r5k1"], "CC1", "GND", "USB-C sink: 5.1k on each CC"),
        r0603("R109", "5.1k", LCSC["r5k1"], "CC2", "GND"),
        Part("U4", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
             {1: ("I/O1", "USB_DP"), 2: ("GND", "GND"), 3: ("I/O2", "USB_DN"), 4: ("I/O2", "USB_DN"),
              5: ("VBUS", "VBUS"), 6: ("I/O1", "USB_DP")}, LCSC["usblc6"], "Power_Protection:USBLC6-2SC6",
             note="ESD protection, placed next to the receptacle"),
        # --- 3.3 V regulator from VBUS (the wireless board's AP2112K, there fed from the power path)
        Part("U3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
             {1: ("VIN", "VBUS"), 2: ("GND", "GND"), 3: ("EN", "VBUS"), 4: ("NC", None), 5: ("VOUT", "3V3")},
             LCSC["ap2112k"], "Regulator_Linear:AP2112K-3.3", note="EN tied to VIN: always on"),
        c0603("C102", "1uF", LCSC["c1u"], "VBUS", "GND", "regulator input"),
        c0603("C108", "1uF", LCSC["c1u"], "3V3", "GND", "regulator output"),
        c0603("C103", "10uF", LCSC["c10u"], "3V3", "GND", "3.3 V bulk, at the RP2040"),
        # --- status LED (Caps Lock), active high
        Part("D103", "LED red", "LED_SMD:LED_0603_1608Metric", {1: ("K", "LED_RED_K"), 2: ("A", "LED_RED")},
             LCSC["led_red"], "Device:LED"),
        r0603("R107", "1k", LCSC["r1k"], "LED_RED_K", "GND"),
        # --- test points: SWD in one row in front of the RP2040, 1 mm pads; VBUS 1.5 mm
        tp("TP1", "SWDIO", "1.0"), tp("TP2", "SWCLK", "1.0"), tp("TP3", "3V3", "1.0"), tp("TP4", "GND", "1.0"),
        tp("TP5", "RESET", "1.0"), tp("TP6", "VBUS"),
    ]


AUDIO_DEVIATIONS = [
    "Supply: VBUS through a TPS22919 load switch (soft start 1.3 ms, output discharge) to AUD_5V, ON tied to VBUS (the "
    "wireless board drives it from a GPIO, on only in USB mode): the sound card's capacitors are charged slowly after "
    "the cable has made contact. A hard switch-on would dip VBUS enough to reset the hub (CH334 datasheet 6.1).",
    "Headphones: a TPA6132A2 DirectPath amplifier after LOL / LOR (demo board: 100 uF + 39R straight to the jack): "
    "about 0 ohm output impedance, no coupling capacitors, 0 dB gain (-6 dB with JP3 closed, for very sensitive "
    "earphones). Inputs single-ended through 1 uF (8 Hz); EN about 0.15 s after the supply (1M + 470 nF from VBUS), "
    "and dragged down with VBUS through a Schottky when the cable is pulled (EN stays within a Schottky drop of "
    "VBUS). On unplug the codec and the amplifier lose their supply together: listen for a click.",
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
    """The sound card: CH334P USB 2.0 hub between the receptacle and the RP2040, CM108B USB audio codec on a hub port,
    TPA6132A2 headphone amplifier, 3.5 mm headset jack (CTIA: tip = left, ring 1 = right, ring 2 = ground, sleeve =
    microphone). The codec and the amplifier run from AUD_5V, switched by a TPS22919 that VBUS turns on."""
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
             "lira:CH334P", note="USB 2.0 hub: upstream to the receptacle, port 3 RP2040, port 2 sound card"),
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
        # --- the sound card's 5 V: soft-started by a TPS22919 that VBUS turns on (QOD through 1k for a slow fall)
        Part("U8", "TPS22919", "Package_TO_SOT_SMD:SOT-363_SC-70-6",
             {1: ("IN", "VBUS"), 2: ("GND", "GND"), 3: ("ON", "VBUS"), 4: ("NC", None), 5: ("QOD", "AUD_QOD"),
              6: ("VOUT", "AUD_5V")}, LCSC["tps22919"], "lira:TPS22919",
             note="load switch, ON tied to VBUS: soft start of the sound card's supply"),
        c0603("C130", "1uF", LCSC["c1u"], "VBUS", "GND", "load switch input"),
        r0603("R118", "1k", LCSC["r1k"], "AUD_QOD", "AUD_5V", "output discharge, once VBUS (ON) is gone"),
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
        r0603("R113", "1M", LCSC["r1M"], "VBUS", "AMP_EN", "amplifier on about 0.15 s after the supply"),
        c0603("C137", "470nF", LCSC["c470n"], "AMP_EN", "GND"),
        Part("D104", "B5819W", "Diode_SMD:D_SOD-123", {1: ("K", "VBUS"), 2: ("A", "AMP_EN")}, LCSC["b5819w"],
             "Device:D_Schottky", note="EN follows VBUS down when the cable is pulled"),
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


def electronics(gpio=None):
    """Everything that is not the key matrix (sound card included). gpio: {RP2040 pad: net} for the matrix lines and
    the status LED."""
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
