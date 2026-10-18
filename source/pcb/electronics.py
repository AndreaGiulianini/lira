"""Placement of the electronics (everything that is not a key) in the strip behind the top row, bottom side.

The connectivity comes from pcb/circuit.py; this file only decides where each part goes and which RP2040 pad
takes which matrix line (chosen from the geometry so that the fan-out does not cross itself). A few connections are
drawn here instead of by the autorouter: the USB high-speed pair (usb_pair), the hub's downstream escapes and its
crystal, the RP2040's ground (exposed pad and TESTEN) and core supply, the codec's and the amplifier's ground pins and the
amplifier's supply.
"""
import math

from circuit import RP_FIXED, RP_GPIO, electronics as circuit_parts, rp_pin

STRIP_DEPTH = 22.0  # mm of PCB behind the top row

X_USB = 110.0  # KiCad x of the USB-C receptacle (about 30% of the width, like the M0110 cord jack)
X_MCU = 135.0
X_CODEC = 200.0  # sound card: codec, its parts to the right of it, the headset jack on the back edge
X_JACK = 243.0
Y_MCU = 12.5  # RP2040 centre, behind the strip's front edge (the back edge is y = top)
SWD_PITCH, SWD_Y = 2.0, 9.8  # SWD pads: pitch, and their row in front of the RP2040's centre (mm)
# rows of 0402 parts behind the RP2040 (supply pins 42-50): the capacitors, then the USB resistors and DVDD's capacitor,
# as Raspberry Pi's minimal design does (Hardware design with RP2040, Figure 6); and in front of it (pins 22 / 23)
ROW1, ROW2, FRONT = -5.15, -7.3, 7.1
# The RP2040 is turned so that its QSPI / USB / supply side faces the back edge and its crystal / SWD side the keys;
# the matrix lines and the status LED leave from the two sides that face along the strip (pads 1-14 and 29-42).
MATRIX_SIDES = (range(1, 15), range(29, 43))
# the RP2040's exposed pad: four ground vias near its corners, and the solder paste in five windows (a centre square
# and four arms between the vias) that keep 0.2 mm from every via's copper ring, so the open vias do not drain the
# paste (46 % of the pad, KiCad's default four windows being 65 %); the vias are tented on the top side
EP_VIAS = ((1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0))
EP_PASTE = (((0.0, 0.0), (1.1, 1.1)), ((0.0, 1.1), (1.0, 0.8)), ((0.0, -1.1), (1.0, 0.8)),
            ((1.1, 0.0), (0.8, 1.0)), ((-1.1, 0.0), (0.8, 1.0)))
# top-layer area under the RP2040, its decoupling and its crystal kept free of tracks (relative to the RP2040's centre):
# a whole ground plane there, into which the exposed pad and every capacitor's ground via drop
CORE_KEEPOUT = (-4.4, -7.1, 4.4, 8.9)
CRYSTAL_KEEPOUT = (2.0, 5.0, 7.5, 9.9)  # the crystal, its 1k and load capacitors
CODEC_VIA = 2.6  # ground vias under the codec, this far from its centre
HS_CORRIDOR = "usb-hs-corridor"  # rule area under the USB high-speed pair (finish_pcb.py finds it by name)
JACK_PEG = 1.0  # locating holes of the headset jack (HRO PJ-320D-4A drawing: 1.00 mm for 0.75 mm pegs)
# top-layer keep-outs (tracks only: the ground pour and vias stay), relative to the exposed pad's centre: the matrix
# lines must not cut the ground plane over the hub, its 12 MHz crystal and capacitors, or over the amplifier and its
# capacitors (the planes carry their ground returns)
HUB_KEEPOUT = (-2.0, -6.0, 6.2, 2.7)
AMP_KEEPOUT = (-3.2, -6.0, 5.0, 8.2)
# 3D models KiCad 10 does not ship for these footprints: the headset jack's is made by case/jack_model.py, the hub
# has the body of the generic 3 x 3 mm QFN-16
MODELS = {"J3": "lib/lira.3dshapes/Jack_3.5mm_PJ-320D-4A.step",
          "U5": "${KICAD10_3DMODEL_DIR}/Package_DFN_QFN.3dshapes/QFN-16-1EP_3x3mm_P0.5mm_EP1.8x1.8mm.step"}
BOLTS_X = (40.0, 185.0, 275.0)  # M3 case bolts through the strip: the PCB has a 7.4 mm hole, the case boss passes
BOLT_HOLE = 7.4


def pad_xy(fp, num):
    import pcbnew
    p = fp.FindPadByNumber(str(num)).GetPosition()
    return pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)


def positions(top):
    """ref -> (x, y, rotation) in board mm. Every connector faces the back edge (board y = top): on the bottom side
    KiCad mirrors the footprint top<->bottom, so orientation 0 already points a footprint's +y side towards the back
    edge. Vertical two-pad parts: rotation 90 puts pad 1 towards the keys, 270 towards the back edge."""
    m, c = X_MCU, top + Y_MCU
    pos = {
        # RP2040 turned 180 degrees: pads 43-56 (supplies, USB, QSPI) towards the back edge, 15-28 (crystal, SWD,
        # RUN) towards the keys, 1-14 on the right, 29-42 on the left
        "U1": (m, c, 180),
        # behind it, 0402 at 1.7 mm from the pins (Hardware design with RP2040 2.1.2-2.1.3; Raspberry Pi's minimal
        # design, Figure 6): ADC_AVDD (43), IOVDD (42) and VREG_VIN (44) on a short 3.3 V bus round the corner, the
        # 1 uF of VREG_VOUT (45) straight above its pin, USB D- / D+ (46 / 47) up between the capacitors to their 27 ohm,
        # USB_VDD + IOVDD (48 / 49) into one 100 nF (as in the design guide), 48 on up between it and the USB resistors
        # to the flash's 3.3 V (48 / 49 have no other way out: see rp2040_decoupling); DVDD (50) only under the package,
        # on the 1.1 V ring. The 3.3 V bulk capacitor at the bus's end
        "C8": (m - 5.0, c + ROW1, 90), "C5": (m - 4.0, c + ROW1, 90), "C11": (m - 3.0, c + ROW1, 90),
        "C12": (m - 2.0, c + ROW1, 90), "C6": (m + 0.0, c + ROW1, 90),
        "R6": (m - 2.2, c + ROW2, 90), "R5": (m - 1.2, c + ROW2, 90),
        "C103": (m - 6.4, c + ROW1 - 0.35, 90),
        # QSPI flash behind-right of the QSPI pads (51-56), turned so that the six lines reach it without crossing:
        # SD3 / SCLK / SD0 (the inner three) into its left column, SD2 / SD1 / SS (the outer three) round its front
        # into its right column; VCC capacitor at its back-left pin, /CS pull-up on the /CS line beyond it
        "U2": (m + 8.8, top + 4.3, 180), "C15": (m + 2.6, top + 2.39, 180), "R2": (m + 16.0, top + 2.39, 180),
        # the side supply pins: IOVDD 1 (right, back end) beside its pin, at the top edge of the matrix lines' fan;
        # IOVDD 10 and 33, in the middle of the fan, are tied to 1 and 42 inside the package, under it
        "C1": (m + 5.2, c - 3.05, 0),
        # in front: the I/O and core capacitors under pins 22 / 23; the 12 MHz crystal to the right, XIN to its
        # top-right pad (with its 15 pF beside it), XOUT through the 1k down its left side to the bottom-left pad
        "C9": (m - 0.1, c + FRONT, 270), "C3": (m + 1.35, c + FRONT, 270),
        "Y1": (m + 4.6, c + 7.1, 270), "R1": (m + 2.3, c + 6.5, 270), "C14": (m + 2.3, c + 8.5, 270),
        "C13": (m + 6.85, c + 6.0, 270),
        # SWD pads in one row in front of the RP2040, just past the strip, below their pins (lines drawn here):
        # SWCLK, SWDIO, RESET, GND; the 3V3 pad behind the package
        "TP2": (m - 1.0, c + SWD_Y, 0), "TP1": (m - 1.0 - SWD_PITCH, c + SWD_Y, 0),
        "TP5": (m - 1.0 - 2 * SWD_PITCH, c + SWD_Y, 0), "TP4": (m - 1.0 - 3 * SWD_PITCH, c + SWD_Y, 0),
        "TP3": (m - 14.2, c - 7.4, 0),
        # VBUS divider for the firmware (GPIO29, pin 41) and its 1 nF, left of the 3.3 V corner
        "C16": (m - 8.7, c - 2.7, 180), "R9": (m - 8.7, c - 4.3, 180), "R8": (m - 8.7, c - 5.9, 0),
        # BOOT and RESET buttons right of the flash (BOOT under the case's paperclip hole), the BOOT resistor and
        # the RUN pull-up next to them
        "SW101": (m + 21.0, top + 5.5, 0), "SW102": (m + 29.5, top + 5.5, 0),
        "R3": (m + 17.0, top + 5.5, 90), "R4": (m + 25.2, top + 5.5, 90),
        "TP6": (82.5, top + 19.3, 0),
        # USB-C on the back edge (overhangs it by 0.4 mm), CC resistors and ESD array behind it; the ESD array is
        # turned so that D+ is the upper pin on both sides (the order of the hub's upstream pins)
        "J1": (X_USB, top - 0.4 + 3.65, 0), "R108": (X_USB - 5.5, top + 11.0, 90), "R109": (X_USB + 5.5, top + 10.6, 270),
        "U4": (X_USB, top + 12.5, 180),
        # VBUS protection next to the receptacle's VBUS via: the TVS, the bulk capacitor and its damping resistor
        "D108": (X_USB - 5.3, top + 13.8, 180), "R7": (X_USB - 4.7, top + 16.0, 180),
        "C104": (X_USB - 9.0, top + 16.15, 180),
        # USB hub right behind the ESD array: upstream pins (left side) facing it, the crystal on its right, the
        # supply capacitors above it; ports 2 and 3 (front side) go down to the channel along the keys, port 3 to
        # the RP2040, port 2 to the codec
        "U5": (X_USB + 6.5, top + 17.5, 180), "Y2": (X_USB + 10.55, top + 17.6, 90),
        "C110": (X_USB + 6.9, top + 13.8, 90), "C112": (X_USB + 8.6, top + 13.8, 90),
        # status LED behind the port window in the back wall, as on the wireless board
        "D103": (101.0, top + 2.0, 90), "R107": (101.0, top + 5.2, 90),
        # 3.3 V regulator with its input and output capacitors next to its pins (the wireless board's place)
        "U3": (103.0, top + 19.0, 0), "C102": (99.6, top + 19.0, 90), "C108": (106.4, top + 19.0, 90),
    }
    pos.update(audio_positions(top))
    return pos


def audio_positions(top):
    """The sound card, right of the middle bolt: codec (analog pins on its right side) with a 100 nF right at each AVDD
    pin, its regulator capacitors around it, the microphone bias above the line outputs, the headphone amplifier
    between the codec and the jack (inputs facing the codec, charge pump towards the jack), the supply switch in front
    of them; at the jack, its ESD clamps and 100 pF between the ferrites and the contacts.
    Vertical parts: rotation 90 puts pad 1 towards the keys, 270 towards the back edge (bottom side)."""
    c, j = X_CODEC, X_JACK
    d = c + 6.0  # the 0402 column at the codec's AVDD pins
    a, b = c + 8.1, c + 10.5  # first two columns right of the codec
    e = c + 1.5  # the parts right of the columns, 1.5 mm further than on rev A (room for the AVDD capacitors)
    m = c + 18.1  # amplifier
    return {
        "U6": (c, top + 10.0, 0),
        # left side: core and I/O regulators (pins 8 / 9), with the demo board's 10 nF to DVDD next to them
        "C119": (c - 6.8, top + 7.4, 90), "C118": (c - 6.8, top + 10.6, 270),
        "C139": (c - 6.8, top + 4.2, 270), "C138": (c - 6.8, top + 13.8, 90),
        # front side: USB series resistors under pins 41 / 42, 3.6 V regulator capacitor under pin 37
        "R111": (c - 0.6, top + 17.8, 90), "R110": (c + 1.6, top + 17.8, 90), "C120": (c + 3.8, top + 17.8, 270),
        # right side: AVDD 29's 100 nF at the pin (C140, the line-outs below it keep their way out)
        "C140": (d, top + 8.72, 90),
        # first column: microphone bias resistor, reference, line-out bias, AVDD 34's 100 nF, digital supply
        "R114": (a, top + 2.6, 90), "C121": (a, top + 6.3, 90), "C122": (a, top + 10.0, 90),
        "C117": (a, top + 13.7, 270), "C115": (a, top + 17.4, 270),
        # second column: bias filter, microphone coupling, the two supply ferrites, digital bulk capacitor
        "C127": (b, top + 2.6, 270), "C129": (b, top + 6.3, 270), "L101": (b, top + 10.0, 90),
        "L102": (b, top + 13.7, 90), "C116": (b, top + 17.4, 270),
        # microphone resistors along the back edge
        "R115": (e + 12.0, top + 2.0, 270), "R116": (e + 14.4, top + 2.0, 90),
        # amplifier input capacitors (right channel above, left below), amplifier and its own capacitors
        "C126": (e + 12.0, top + 7.6, 90), "C123": (e + 12.0, top + 12.6, 90),
        "U7": (m, top + 10.0, 0),
        "JP3": (m - 1.4, top + 5.6, 0), "R112": (m + 1.8, top + 5.6, 270), "C135": (m + 4.0, top + 6.6, 90),
        "C136": (m + 3.4, top + 9.9, 90), "C134": (m + 3.4, top + 13.2, 270), "C133": (m, top + 14.6, 270),
        # amplifier enable from GPIO13: 1M pull-down at EN, 100k in series from the GPIO line, just outside the
        # top-layer keep-out over the amplifier (so the GPIO line can arrive on either layer)
        "R113": (m + 2.2, top + 16.4, 90), "R124": (m + 3.0, top + 20.2, 180),
        # supply switch (VBUS -> AUD_5V) with its input capacitor and its ON pull-down, AUD_5V bulk
        "U8": (e + 12.6, top + 17.6, 0), "C130": (e + 12.6, top + 20.4, 270), "R119": (e + 10.5, top + 20.5, 90),
        "R118": (e + 14.86, top + 17.6, 90), "C113": (m, top + 18.8, 90), "C114": (e + 14.4, top + 14.4, 90),
        # ferrites next to the jack's tip and ring 1 (a filter at the connector, against RF and ESD); between them
        # and the jack's contacts, in one column: ring 1's 100 pF and ESD clamp, the tip's clamp and 100 pF
        "L104": (j - 9.2, top + 6.6, 90), "L103": (j - 9.2, top + 12.6, 90),
        "C125": (j - 6.6, top + 2.6, 90), "D106": (j - 6.6, top + 6.4, 270),
        "D105": (j - 6.6, top + 10.4, 90), "C124": (j - 6.6, top + 14.4, 270),
        # headset jack on the back edge: its nose (2 mm) overhangs the edge by 1.8 mm (the locating peg needs 0.8 mm
        # of board in front of its hole); microphone 100 pF and ESD clamp in front of it, next to the sleeve pad
        "J3": (j, top + 6.55, 270),
        "C128": (j + 3.0, top + 16.4, 270), "D107": (j + 1.2, top + 14.6, 270),
        # explicit straps on the CM108B mode jumpers: the free gap left of the codec's capacitor column
        "R120": (191.2, top + 4.0, 90), "R121": (191.2, top + 7.5, 90),
        "R122": (191.2, top + 11.0, 90), "R123": (191.2, top + 14.5, 90),
    }


def add_electronics(B, left, top, right, keys_top):
    parts = {p.ref: p for p in circuit_parts()}
    pos = positions(top)
    missing = sorted(set(parts) - set(pos))
    assert not missing, "no position for %s" % missing
    placed = {}
    for ref, part in parts.items():
        lib, name = part.footprint.split(":")
        x, y, rot = pos[ref]
        placed[ref] = B.place(lib, name, ref, x, y, rot=rot, bottom=True, value=part.value, nets=part.nets,
                              lcsc=part.lcsc, in_bom=part.lcsc is not None)
    u1 = placed["U1"]
    import pcbnew
    m_x, m_y = pad_centre(u1)
    rp2040_ground(B, placed)
    rp2040_core(B, placed)
    rp2040_decoupling(B, placed)
    rp2040_crystal(B, placed)
    rp2040_qspi(B, placed)
    vbus_sense(B, placed)
    swd_lines(B, placed)
    usb_pair(B, placed)
    vbus_parts(B, placed)
    hub_ports(B, placed)
    x0, y0, x1, y1 = CORE_KEEPOUT
    keepout(B, m_x + x0, m_y + y0, m_x + x1, m_y + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="rp2040")
    x0, y0, x1, y1 = CRYSTAL_KEEPOUT
    keepout(B, m_x + x0, m_y + y0, m_x + x1, m_y + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="crystal")
    for pad in placed["J3"].Pads():  # the jack's locating pegs: 1.0 mm holes as on the HRO drawing (KiCad: 1.6)
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            size = pcbnew.VECTOR2I(pcbnew.FromMM(JACK_PEG), pcbnew.FromMM(JACK_PEG))
            pad.SetDrillSize(size)
            pad.SetSize(size)
    for ref, step in MODELS.items():
        model = pcbnew.FP_3DMODEL()
        model.m_Filename = step
        placed[ref].Models().clear()
        placed[ref].Models().push_back(model)
    # the hub's exposed pad (its only ground) is ringed by its pins: a via at its centre, between the four paste
    # windows (the board cannot have filled vias, and an open via drains solder), takes it to the top ground plane,
    # which a top-layer keep-out keeps whole over the hub, its crystal and capacitors; each capacitor's ground pad
    # has its own via
    hx, hy = pad_xy(placed["U5"], 17)
    via(B, "GND", hx, hy)
    for ref in ("C110", "C112"):
        gnd_via(B, placed[ref])
    # V5 (pin 15) and VDD33 (pin 16), both on 3.3 V (CH334 datasheet 6.4), straight up into C110's 3.3 V pad, which a
    # short track joins to C112's
    c110, c112 = pad_xy(placed["C110"], 1), pad_xy(placed["C112"], 1)
    for pin in (15, 16):
        x, y = pad_xy(placed["U5"], pin)
        path(B, "3V3", [(x, y), (x, c110[1])], width=0.25)
    path(B, "3V3", [c110, c112], width=0.3)
    hub_supply(B, placed)
    x0, y0, x1, y1 = HUB_KEEPOUT
    keepout(B, hx + x0, hy + y0, hx + x1, hy + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="hub")
    # the hub's crystal, drawn here (short, and the autorouter does not always find them among the lines around the
    # hub): XI (pin 2) down into the crystal's pin 1, XO (pin 1) up over the crystal's ground pad into its pin 3
    u5, y2 = placed["U5"], placed["Y2"]
    xo, xi = pad_xy(u5, 1), pad_xy(u5, 2)
    p1, p2, p3 = (pad_xy(y2, n) for n in (1, 2, 3))
    path(B, "HUB_XI", [xi, (xi[0] + 0.6, xi[1]), (p1[0], xi[1] + 1.1), p1], width=0.25)
    y_over = p2[1] - 1.15  # between the crystal's ground pad and the capacitors above it
    path(B, "HUB_XO", [xo, (xo[0] + 0.96, y_over), (p3[0] - 0.8, y_over), (p3[0], y_over + 0.8), p3], width=0.25)
    # the codec's ground pins sit between signal pins, where neither the pour nor the router can reach them: a short
    # track from each one inwards to a via under the chip's body (no exposed pad there), into the top ground pour
    u6 = placed["U6"]
    cx, cy = pad_centre(u6)
    for pin in (14, 24, 36):
        x, y = pad_xy(u6, pin)
        if abs(x - cx) > abs(y - cy):
            stub(B, "GND", x, y, cx + math.copysign(CODEC_VIA, x - cx), y)
        else:
            stub(B, "GND", x, y, x, cy + math.copysign(CODEC_VIA, y - cy))
    # 33 (between LOR and AVDD 34): a short track in, to a via between the pads and the AVDD tie (codec_avdd)
    x, y = pad_xy(u6, 33)
    track(B, "GND", x, y, cx + 3.15, y, width=0.25)
    via(B, "GND", cx + 3.0, y - 0.2)
    # the amplifier's ground pins (IN+ of both channels, G1, PGND, SGND) to its exposed pad, which takes a via at its
    # centre; G1 and SGND also get a via of their own just outside the package (ground that does not depend on the
    # pad's solder joint); the top ground plane stays whole over the amplifier and its capacitors (keep-out)
    u7 = placed["U7"]
    ax, ay = pad_centre(u7)
    for pin in (2, 3, 7, 10, 15):
        x, y = pad_xy(u7, pin)
        k = 0.55 / max(abs(x - ax), abs(y - ay))  # end 0.55 mm from the centre: well inside the 1.68 mm pad
        track(B, "GND", x, y, ax + (x - ax) * k, ay + (y - ay) * k, width=0.2)  # 0.2 mm: 0.5 mm pin pitch
    via(B, "GND", ax, ay)
    for pin in (7, 15):
        x, y = pad_xy(u7, pin)
        out = math.copysign(1.15, y - ay)
        stub(B, "GND", x, y, x, y + out, width=0.2)
    gnd_via(B, placed["C133"])
    # the amplifier's supply, VDD (pin 14), straight down into its 2.2 uF (C133), beside the SGND via
    x14, y14 = pad_xy(u7, 14)
    xc, yc = pad_xy(placed["C133"], 1)
    sgnd = pad_xy(u7, 15)[0]
    xs = x14 + math.copysign(0.1, x14 - sgnd)  # 0.1 mm further from the SGND via
    path(B, "AUD_5V", [(x14, y14), (x14, y14 + 0.5), (xs, y14 + 0.6), (xs, yc - 0.2)], width=0.25)
    # the amplifier's EN (pin 13) down beside C133 into its 1M pull-down and on into the 100k from GPIO13, just outside
    # the keep-out below
    x13, y13 = pad_xy(u7, 13)
    r113, r124 = pad_xy(placed["R113"], 1), pad_xy(placed["R124"], 2)
    path(B, "AMP_EN", [(x13, y13), (x13, r113[1]), r113, r124], width=0.2)
    gx, gy = pad_xy(placed["R113"], 2)
    stub(B, "GND", gx, gy, gx + 0.95, gy, width=0.25)
    x0, y0, x1, y1 = AMP_KEEPOUT
    keepout(B, ax + x0, ay + y0, ax + x1, ay + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="amplifier")
    # the load switch's GND (pin 2) sits between its IN and ON pins, both on VBUS here: a via of its own just outside
    # the package, or the VBUS connection between them can wall it in
    gx, gy = pad_xy(placed["U8"], 2)
    stub(B, "GND", gx, gy, gx + math.copysign(1.35, gx - pad_xy(placed["U8"], 5)[0]), gy, width=0.25)
    x23, y23 = pad_xy(u6, 23)  # TEST, next to 24: to the same via
    x24, y24 = pad_xy(u6, 24)
    track(B, "GND", x23, y23, x24, cy + math.copysign(CODEC_VIA, y24 - cy))
    codec_avdd(B, placed)
    jack_protection(B, placed)

    ports = {"usb": (X_USB, top), "window": (pos["D103"][0] - 4.0, top, X_USB + 7.0),
             "boot": pos["SW101"][:2], "jack": (X_JACK, top)}
    for i, x in enumerate(BOLTS_X, start=1):
        fp = B.place("MountingHole", "MountingHole_3.2mm_M3", "HB%d" % i, x, top + 11.0, value="case bolt",
                     in_bom=False)
        enlarge_hole(fp, BOLT_HOLE)
    ports["bolts"] = [(x, top + 11.0) for x in BOLTS_X]
    rows, cols, led, gpio = assign_matrix_pins(B, u1)
    labels(B, placed, top)
    ports["matrix"] = dict(rows=rows, cols=cols, status_led=led)
    ports["gpio"] = gpio
    return ports


def usb_pair(B, placed):
    """The USB 2.0 high-speed pair (480 Mbit/s) from the receptacle through the ESD array to the hub's upstream
    pins, drawn here rather than left to the autorouter: on the bottom layer under the top ground pour, no vias,
    lengths matched to about 0.5 mm; side by side (0.5 mm apart) where the parts allow, split around the ESD array.
      * receptacle: the doubled pads are joined on the bottom layer itself, D- above the pad row (over the end of
        A6), D+ below it (under the end of A7);
      * ESD array (turned so that D+ is the upper pin on both sides): D+ comes down between its two pin rows and
        joins pins 6 and 1, D- goes round its left side into pin 4 and across to pin 3 (both lines pass straight
        through it, the way ST lays it out); its VBUS pin takes a via under its body, its GND pin a via beside it;
      * hub: D+ makes a small detour (the length D- loses going round the ESD array), then both run down and enter
        the hub's upstream pins (12, 11) from the left."""
    j1, u4, u5 = placed["J1"], placed["U4"], placed["U5"]
    dn_b, dp_a, dn_a, dp_b = (pad_xy(j1, n) for n in ("B7", "A6", "A7", "B6"))
    assert dn_b[0] < dp_a[0] < dn_a[0] < dp_b[0], "unexpected USB-C pad order"
    half = pcbnew_mm(j1.FindPadByNumber("A6").GetBoundingBox().GetHeight()) / 2
    y_top, y_bot = dp_a[1] - half, dp_a[1] + half  # ends of the pad row
    ux, uy = pad_centre(u4)
    dp6, dn4, dp1, dn3 = (pad_xy(u4, n) for n in (6, 4, 1, 3))
    assert dp6[1] < dn4[1] and dp1[1] < dn3[1], "the ESD array must have D+ above D-"
    dpu, dmu = pad_xy(u5, 12), pad_xy(u5, 11)
    assert dpu[1] < dmu[1] and dpu[0] < pad_centre(u5)[0], "the hub's upstream pins must face left, D+ on top"
    pad_w = pcbnew_mm(u4.FindPadByNumber("4").GetBoundingBox().GetWidth())
    y_up, y_dn = y_top - 0.42, y_bot + 0.58
    # receptacle: D- joined above the pads, D+ below them (every junction is a segment end: the autorouter does not
    # see a track that ends in the middle of another one as connected)
    path(B, "USB_DN", [dn_b, (dn_b[0], y_up), (dn_a[0], y_up), dn_a])
    path(B, "USB_DP", [dp_a, (dp_a[0], y_dn), (ux, y_dn), (dp_b[0], y_dn), dp_b])
    # D+ down between the ESD array's pin rows, through pins 6 and 1
    path(B, "USB_DP", [(ux, y_dn), (ux, dp6[1])])
    path(B, "USB_DP", [dp6, (ux, dp6[1]), dp1])
    # D- round the left of the ESD array into pin 4, through to pin 3
    x_wrap = dn4[0] - pad_w / 2 - 0.35
    y_turn = y_dn + 0.4
    path(B, "USB_DN", [dn_b, (dn_b[0], y_turn), (x_wrap, y_turn + dn_b[0] - x_wrap), (x_wrap, dn4[1]), dn4])
    path(B, "USB_DN", [dn4, dn3])
    # the ESD array's VBUS (between the two lines) to a via under its body, its GND pin to a via on its right
    v5, g2 = pad_xy(u4, 5), pad_xy(u4, 2)
    stub(B, "VBUS", v5[0], v5[1], ux - 0.2, uy)
    stub(B, "GND", g2[0], g2[1], g2[0] + pad_w / 2 + 0.55, g2[1])
    # VBUS: the receptacle's two VBUS pad pairs and the ESD array's VBUS via are inside the pair's loops; a top-layer
    # link joins them, crossing each line of the pair once and squarely (the autorouter, left to itself, gets stuck)
    va, vb = pad_xy(j1, "A4"), pad_xy(j1, "A9")
    y_link = y_dn + 0.35
    x_side = x_wrap - 1.25
    for x, y in (va, vb):
        track(B, "VBUS", x, y, x, y_link, width=0.4, locked=True)
        via(B, "VBUS", x, y_link)
    for (x0, y0), (x1, y1) in (((x_side, y_link), (va[0], y_link)), ((va[0], y_link), (vb[0], y_link)),
                               ((x_side, y_link), (x_side, uy)), ((x_side, uy), (ux - 0.2, uy))):
        track(B, "VBUS", x0, y0, x1, y1, width=0.4, locked=True, layer="F")
    via(B, "VBUS", x_side, uy)  # where the rest of VBUS (regulator, protection, sound card) joins, on the bottom layer
    B.vbus_join = (x_side, uy)
    # to the hub: D+ outside (right), D- inside, 0.5 mm apart; D+ with a 2.5 mm detour for the length
    x_dp, x_dn = dp1[0] + 2.21, dp1[0] + 1.71
    bump = (dp1[0] + 1.16, dp1[0] + 1.66, dp1[1] - 1.25)
    path(B, "USB_DP", [dp1, (bump[0], dp1[1]), (bump[0], bump[2]), (bump[1], bump[2]), (bump[1], dp1[1]),
                       (x_dp, dp1[1]), (x_dp, dpu[1] - 0.75), (x_dp + 0.75, dpu[1]), dpu])
    path(B, "USB_DN", [dn3, (x_dn, dn3[1]), (x_dn, dmu[1] - 0.75), (x_dn + 0.75, dmu[1]), dmu])
    # the return path: finish_pcb.py brings the bottom ground pour to 0.2 mm beside both lines (coplanar ground,
    # ~96 ohm differential instead of ~110) over this area, found by its name; ground vias along the pair tie it to
    # the top pour. (Keeping the top layer free of tracks under the pair as well would leave the matrix lines no room
    # to pass the receptacle, so it is not done.) The area itself, on the top layer, only forbids footprints there.
    import pcbnew
    keepout(B, x_wrap - 0.9, y_up - 0.6, x_dp + 0.9, dmu[1] + 0.6, layers=(pcbnew.F_Cu,), pours=True, vias=True,
            tracks=True, footprints=True, name=HS_CORRIDOR)
    for x, y in ((x_dp + 0.9, dp1[1] + 1.45), (x_dp + 0.9, dpu[1] - 1.75), (x_dn + 0.15, dmu[1] + 0.75)):
        via(B, "GND", x, y)


def vbus_parts(B, placed):
    """The receptacle's VBUS protection, drawn from the via where VBUS leaves the receptacle (usb_pair): straight down
    into the TVS's cathode and on into the damping resistor; the TVS's anode and the bulk capacitor's ground each
    take a via."""
    x, y = B.vbus_join
    k = pad_xy(placed["D108"], 1)
    r = pad_xy(placed["R7"], 1)
    path(B, "VBUS", [(x, y), (x, k[1]), k], width=0.5)
    path(B, "VBUS", [(x, k[1]), (x, r[1]), r], width=0.4)
    a = pad_xy(placed["D108"], 2)
    stub(B, "GND", a[0], a[1], a[0] - 1.2, a[1], width=0.5)
    d = pad_xy(placed["R7"], 2)
    c = pad_xy(placed["C104"], 1)
    path(B, "VBUS_DAMP", [d, c], width=0.4)
    g = pad_xy(placed["C104"], 2)
    stub(B, "GND", g[0], g[1], g[0] - 1.1, g[1], width=0.5)


def rp2040_decoupling(B, placed):
    """Every supply pin to its own capacitor, drawn here on the bottom layer, a few mm each (Hardware design with
    RP2040 2.1.2: decoupling close to the power pins; RP2040 datasheet 2.10.1: the regulator's 1 uF close to VREG_VIN
    and VREG_VOUT). Behind the package: ADC_AVDD (43), VREG_VIN (44) and IOVDD (42) join on a short bus round the
    corner, from which the 3.3 V bulk capacitor, C8, C5 and C11 (1 uF) hang; VREG_VOUT (45) goes straight up into C12
    (1 uF); USB D- / D+ (46 / 47) up between C12 and C6 to their 27 ohm; USB_VDD (48) and IOVDD (49) into C6 and on to
    the flash's capacitor C15; DVDD (50) shares C12 through the 1.1 V ring. In front, IOVDD (22) and DVDD (23) into C3
    and C9. On the sides IOVDD 1 and 10, 33 and 42 are joined under the package (inside the pin ring), 22 joins the
    1-10 tie there too, 1 has a straight stub to C1 (which joins the rail at the flash's VCC: rp2040_qspi).
    Every capacitor's ground pad has its own via into the top layer's ground plane (whole under the package)."""
    u1 = placed["U1"]
    P = {n: pad_xy(u1, n) for n in (1, 10, 22, 23, 33, 42, 43, 44, 45, 46, 47, 48, 49, 50)}
    cap = {ref: pad_xy(placed[ref], 1) for ref in ("C1", "C3", "C5", "C6", "C8", "C9", "C11", "C12", "C103")}
    w = 0.2  # the RP2040's pads are 0.2 mm wide
    # the 3.3 V corner bus, 0.5 mm outside the back pins: 42 (left side) and 43 / 44 join it, the capacitors hang off it
    yb = P[43][1] - 0.56
    xs = [cap["C103"][0], cap["C8"][0], cap["C5"][0], cap["C11"][0], P[43][0], P[44][0]]
    path(B, "3V3", [(x, yb) for x in xs], width=w)
    path(B, "3V3", [P[42], (cap["C5"][0], P[42][1]), (cap["C5"][0], yb)], width=w)
    for n in (43, 44):
        path(B, "3V3", [P[n], (P[n][0], yb)], width=w)
    for ref in ("C103", "C8", "C5", "C11"):
        path(B, "3V3", [(cap[ref][0], yb), cap[ref]], width=0.25)
    # VREG_VOUT: straight up into its 1 uF
    x45, y45 = P[45]
    c12 = cap["C12"]
    path(B, "1V1", [P[45], (x45, yb - 0.15), (c12[0], yb - 0.35), c12], width=w)
    # USB_VDD (48) and IOVDD (49): 3.3 V pins between the 1.1 V pins 45 and 50, behind which the USB lines go up and under
    # which the 1.1 V ring joins 45 to 50, so on one layer they are walled in: 49 goes up into C6 and 48, joined to it,
    # goes on up between C6 and the USB resistors and across to the flash's 3.3 V capacitor (C15), which joins them to
    # the rest of the rail
    y_j = P[48][1] - 0.66
    path(B, "3V3", [P[49], (P[49][0], y_j), (P[49][0], cap["C6"][1])], width=w)
    c15 = pad_xy(placed["C15"], 1)
    path(B, "3V3", [P[48], (P[48][0], y_j), (P[48][0], c15[1] + 0.81), (c15[0], c15[1] + 0.81), c15], width=w)
    path(B, "3V3", [(P[48][0], y_j), (P[49][0], y_j)], width=w)
    # USB: D- up and left into R6, D+ straight up into R5
    r6, r5 = pad_xy(placed["R6"], 1), pad_xy(placed["R5"], 1)
    y_dn = r6[1] + 0.62
    path(B, "RP_DN", [P[46], (P[46][0], y_dn), (r6[0], y_dn), r6], width=w)
    path(B, "RP_DP", [P[47], (P[47][0], r5[1])], width=w)
    # the ground pads: C12's joins C11's, the others each have a via just beyond them
    g11, g12 = pad_xy(placed["C11"], 2), pad_xy(placed["C12"], 2)
    path(B, "GND", [g11, g12], width=0.25)
    for ref in ("C8", "C5", "C11", "C6", "C103"):
        gx, gy = pad_xy(placed[ref], 2)
        stub(B, "GND", gx, gy, gx, gy - (0.87 if ref != "C103" else 1.0), width=0.25)
    # front, nested under XOUT's turn: IOVDD 22 down and right over C9 into C3, DVDD 23 down and right under it into C9
    # (SWCLK keeps the column left of them free); their ground vias below them
    y22 = cap["C3"][1] - 0.62
    path(B, "3V3", [P[22], (P[22][0], y22), (cap["C3"][0], y22), cap["C3"]], width=w)
    y23 = cap["C9"][1] - 0.1
    path(B, "1V1", [P[23], (P[23][0], y23), (cap["C9"][0], y23), cap["C9"]], width=w)
    # (DVDD 50 is on the 1.1 V ring of rp2040_core, which also joins VREG_VOUT 45 and its 1 uF)
    for ref in ("C9", "C3"):
        gx, gy = pad_xy(placed[ref], 2)
        stub(B, "GND", gx, gy, gx, gy + 0.87, width=0.25)
    # the sides: 1 into C1 beside it; 1-10 and 42-33 joined inside the pin ring (0.3 mm in from the pads' inner ends,
    # between them and the 1.1 V ring of rp2040_core)
    cx, cy = pad_centre(u1)
    for a, b in ((1, 10), (42, 33)):
        xa, ya = P[a]
        xi = cx + math.copysign(2.7, xa - cx)
        path(B, "3V3", [P[a], (xi, ya), (xi, P[b][1]), P[b]], width=w)
    # IOVDD 22 (in front, walled in there by the crystal's and the SWD lines and C9) joins the 1-10 tie inside too,
    # between the exposed pad and the front pins (TESTEN's ground goes out to a via instead: rp2040_ground)
    xr = cx + 2.7
    y22 = cy + 2.1
    path(B, "3V3", [P[22], (P[22][0], y22), (xr, y22), (xr, P[10][1])], width=w)
    path(B, "3V3", [P[1], (P[1][0] + 0.7, P[1][1]), cap["C1"]], width=w)  # C1 between the QSPI lines and the fan
    gx, gy = pad_xy(placed["C1"], 2)
    stub(B, "GND", gx, gy, gx + 0.85, gy, width=0.25)


def rp2040_crystal(B, placed):
    """The 12 MHz crystal, drawn here (Hardware design with RP2040 2.3: keep it short): XIN and XOUT leave the
    package's front side together and turn right, under the two GPIO lines that switch the sound card; XIN runs to
    the crystal's top-right pad and on to its 15 pF; XOUT turns down left of the crystal into the 1k, and from it the
    crystal's side (XOUT_X) goes to the 15 pF below and into the bottom-left pad. The crystal's two ground pads are
    joined under it; each ground pad and capacitor has a via into the top layer's plane, whole under all of this."""
    u1, y1 = placed["U1"], placed["Y1"]
    xin, xout = pad_xy(u1, 20), pad_xy(u1, 21)
    p1, p3, p2, p4 = (pad_xy(y1, n) for n in (1, 3, 2, 4))  # XIN top-right, XOUT_X bottom-left, ground
    c13, c14 = pad_xy(placed["C13"], 1), pad_xy(placed["C14"], 1)
    r1a, r1b = pad_xy(placed["R1"], 1), pad_xy(placed["R1"], 2)
    y_in, y_out = xin[1] + 1.56, xin[1] + 1.96
    w = 0.2
    path(B, "XIN", [xin, (xin[0], y_in), (p1[0], y_in), p1], width=w)
    path(B, "XIN", [(p1[0], y_in), (c13[0], y_in), c13], width=w)
    path(B, "XOUT", [xout, (xout[0], y_out), (r1a[0], y_out), r1a], width=w)
    path(B, "XOUT_X", [r1b, (r1b[0], c14[1]), (p3[0], c14[1])], width=0.25)
    path(B, "GND", [p4, p2], width=0.3)
    for x, y in ((p2[0], p2[1] + 1.35),):
        stub(B, "GND", p2[0], p2[1], x, y, width=0.4)
    for ref in ("C13", "C14"):
        gx, gy = pad_xy(placed[ref], 2)
        stub(B, "GND", gx, gy, gx, gy + 0.87, width=0.25)
    # the sound card's two enables leave the pins right of the crystal's above it, nested the same way, turn down past
    # it and run side by side along the bottom of the strip (in front of the SWD pads, behind the top row's sockets)
    # to their resistors at the sound card: 70-80 mm that the autorouter, among the matrix lines, does not reliably find
    ends = {"AUD_EN": pad_xy(placed["R119"], 1), "AMP_ON": pad_xy(placed["R124"], 1)}
    for k, (pin, net) in enumerate(((15, "AUD_EN"), (16, "AMP_ON"))):
        x, y = pad_xy(u1, pin)
        y_run = y + 0.76 + 0.4 * k
        x_down = c13[0] + 1.7 - 0.4 * k
        y_long = 33.6 + 0.5 * k
        ex, ey = ends[net]
        path(B, net, [(x, y), (x, y_run), (x_down, y_run), (x_down, y_long), (ex, y_long), (ex, ey)], width=0.25)


def rp2040_qspi(B, placed):
    """The six QSPI lines to the flash, drawn here, nested so that none crosses another: each goes straight up from
    its pin and turns right (SD3 first and highest, /CS last and lowest); SD3, SCLK and SD0 turn up again left of the
    flash and enter its left column from the side, SD2, SD1 and /CS run on under its front and turn up right of it into
    its right column. The flash's VCC goes to its capacitor at the back edge, its ground pin to a via under it.
    The IOVDD capacitor C1 (beside pin 1, below the lines; through the tie inside the package also IOVDD 10 and 22's
    link to the rail) joins the flash's VCC: right above C1, a via just past it, on the top layer across the three
    lines that run on under the flash, and up under the flash into its VCC pin."""
    u1, u2 = placed["U1"], placed["U2"]
    nets = ("QSPI_SD3", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD2", "QSPI_SD1", "QSPI_SS")
    flash = {p.GetNetname(): pad_xy(u2, p.GetNumber()) for p in u2.Pads()}
    w = 0.2
    x_left = min(x for x, y in flash.values())
    x_right = max(x for x, y in flash.values())
    for k, (pin, net) in enumerate(zip(range(51, 57), nets)):
        x, y = pad_xy(u1, pin)
        y_run = y - 2.86 + 0.4 * k
        fx, fy = flash[net]
        if k < 3:
            x_up = x_left - 2.2 + 0.4 * k
            path(B, net, [(x, y), (x, y_run), (x_up, y_run), (x_up, fy), (fx, fy)], width=w)
        else:
            x_up = x_right + 1.6 + 0.4 * (k - 3)
            path(B, net, [(x, y), (x, y_run), (x_up, y_run), (x_up, fy), (fx, fy)], width=w)
    ss = flash["QSPI_SS"]
    r2 = pad_xy(placed["R2"], 2)
    path(B, "QSPI_SS", [(x_right + 1.6 + 0.8, ss[1]), r2], width=w)
    vcc, c15 = flash["3V3"], pad_xy(placed["C15"], 1)
    path(B, "3V3", [vcc, c15], width=0.3)
    g = flash["GND"]
    x_mid = (x_left + x_right) / 2
    stub(B, "GND", g[0], g[1], g[0] + math.copysign(1.6, x_mid - g[0]), g[1], width=0.3)  # in, under the flash
    c1 = pad_xy(placed["C1"], 1)
    y_c1 = c1[1] - 0.6  # between C1 and /CS's line
    x_v = c1[0] + 2.6
    y_v = pad_xy(u1, 54)[1] - 2.86 + 0.4 * 3 - 0.6  # under the flash, just behind SD2's line
    path(B, "3V3", [c1, (c1[0], y_c1), (x_v, y_c1)], width=0.2)
    via(B, "3V3", x_v, y_c1)
    track(B, "3V3", x_v, y_c1, x_v, y_v, width=0.25, locked=True, layer="F")
    via(B, "3V3", x_v, y_v)
    path(B, "3V3", [(x_v, y_v), (x_v, vcc[1] + 0.6), (x_v - 0.6, vcc[1]), vcc], width=0.25)
    gx, gy = pad_xy(placed["C15"], 2)
    stub(B, "GND", gx, gy, gx - 0.9, gy, width=0.3)


def vbus_sense(B, placed):
    """GPIO29 (pin 41) left to the divider: the 1 nF, the lower and the upper resistor share one vertical line."""
    u1 = placed["U1"]
    x41, y41 = pad_xy(u1, 41)
    c16, r9, r8 = pad_xy(placed["C16"], 1), pad_xy(placed["R9"], 1), pad_xy(placed["R8"], 2)
    path(B, "VBUS_SENSE", [(x41, y41), (c16[0], y41), c16, r9, r8], width=0.2)
    g1, g2 = pad_xy(placed["C16"], 2), pad_xy(placed["R9"], 2)
    path(B, "GND", [g1, g2], width=0.3)
    stub(B, "GND", g2[0], g2[1], g2[0] - 0.95, (g1[1] + g2[1]) / 2, width=0.3)


def codec_avdd(B, placed):
    """Each of the codec's AVDD pins (29, 34) to its own 100 nF, drawn here: 29 straight out into C140, 1 mm away; 34 out
    and down into C117 in the first column (the line-outs between them need the room right of the pins to cross). The
    two pins are also joined under the codec (inside its pin ring, which has no exposed pad); the autorouter brings
    the analog ferrite's side to them (on rev A the analog supply had one capacitor, 30 mm of track away)."""
    u6 = placed["U6"]
    cx0, cy0 = pad_centre(u6)
    x, y = pad_xy(u6, 29)
    c = pad_xy(placed["C140"], 1)
    path(B, "AUD_AVDD", [(x, y), (c[0], y), c], width=0.2)
    gx, gy = pad_xy(placed["C140"], 2)
    stub(B, "GND", gx, gy, gx + 0.9, gy, width=0.25)
    x, y = pad_xy(u6, 34)
    c = pad_xy(placed["C117"], 1)
    path(B, "AUD_AVDD", [(x, y), (c[0] - (c[1] - y), y), c], width=0.25)
    gx, gy = pad_xy(placed["C117"], 2)
    stub(B, "GND", gx, gy, gx, gy + 0.9, width=0.25)
    p29, p34 = pad_xy(u6, 29), pad_xy(u6, 34)
    xi = cx0 + 2.4
    path(B, "AUD_AVDD", [p29, (xi, p29[1]), (xi, p34[1]), p34], width=0.25)


def jack_protection(B, placed):
    """The headphone outputs and the microphone at the jack, drawn here: each ferrite's jack side runs through its ESD
    clamp's pad (and the 100 pF beside it) to the jack's contact, so the clamp sits between the jack and everything
    else (on rev A they hung on a 14 mm stub beyond the jack). The two clamps' ground pads share a via between them;
    the 100 pF and the microphone's clamp each have their own."""
    j3 = placed["J3"]
    contact = {p.GetNumber(): pad_xy(j3, p.GetNumber()) for p in j3.Pads() if p.GetNumber()}
    for net, bead, clamp, cap, pin in (("HP_R", "L104", "D106", "C125", "R1"), ("HP_L", "L103", "D105", "C124", "T")):
        b2 = pad_xy(placed[bead], 2)
        d1 = pad_xy(placed[clamp], 1)
        c1 = pad_xy(placed[cap], 1)
        path(B, net, [b2, (b2[0], d1[1]), d1, (contact[pin][0] - 0.6, d1[1]), (contact[pin][0] - 0.6, contact[pin][1]),
                      contact[pin]], width=0.3)
        path(B, net, [c1, d1], width=0.3)
        gx, gy = pad_xy(placed[cap], 2)
        stub(B, "GND", gx, gy, gx, gy + math.copysign(0.85, gy - c1[1]), width=0.3)
    g6, g5 = pad_xy(placed["D106"], 2), pad_xy(placed["D105"], 2)
    path(B, "GND", [g6, g5], width=0.3)
    via(B, "GND", g6[0], (g6[1] + g5[1]) / 2)
    d7 = pad_xy(placed["D107"], 1)
    s = contact["S"]
    path(B, "MIC", [s, (d7[0], s[1]), d7], width=0.3)
    gx, gy = pad_xy(placed["D107"], 2)
    stub(B, "GND", gx, gy, gx, gy + 0.9, width=0.3)

def hub_supply(B, placed):
    """The hub's 3.3 V, drawn here (on the bottom layer the high-speed pair and the receptacle's VBUS link wall the hub's
    capacitors off from the regulator, and the top layer over the hub is kept whole): from the regulator's output
    capacitor C108 to a via, on the top layer up below the VBUS link and across over the pair (its ground corridor allows
    tracks), down a via just past the pair's ground vias and into C110; and from C112 out of the hub's keep-out and
    straight back to the 3.3 V test pad TP3, where the autorouter joins the RP2040's side of the rail."""
    import pcbnew
    c108, c110, c112 = pad_xy(placed["C108"], 1), pad_xy(placed["C110"], 1), pad_xy(placed["C112"], 1)
    v1 = (c108[0] + 1.5, c108[1])
    v2 = (X_USB + 4.25, c110[1] - 0.62)
    path(B, "3V3", [c108, v1], width=0.4)
    via(B, "3V3", *v1)
    for (x0, y0), (x1, y1) in ((v1, (v1[0], v2[1])), ((v1[0], v2[1]), v2)):
        track(B, "3V3", x0, y0, x1, y1, width=0.4, locked=True, layer="F")
    via(B, "3V3", *v2)
    path(B, "3V3", [v2, (c110[0] - 0.6, v2[1]), (c110[0], v2[1] + 0.6)], width=0.3)
    x_out = c112[0] + 1.7
    tp = pad_xy(placed["TP3"], 1)
    path(B, "3V3", [c112, (x_out, c112[1]), (x_out, tp[1] + 0.5), tp], width=0.3)

def hub_ports(B, placed):
    """The hub's two downstream pairs leave its front side straight down and turn right one inside the other (port 3
    to the module inside, port 2 to the codec outside), 0.9 mm apart, each ending in a via: the autorouter picks
    them up from there already untangled, on either layer."""
    u5 = placed["U5"]
    x_end = X_MCU - 10.0
    for k, (net, pin) in enumerate((("MCU_DN", 5), ("MCU_DP", 6), ("AUD_DN", 7), ("AUD_DP", 8))):
        x, y = pad_xy(u5, pin)
        y_run = y + 0.9 + 0.9 * k
        path(B, net, [(x, y), (x, y_run), (x_end, y_run)])
        via(B, net, x_end, y_run)


def rp2040_ground(B, placed):
    """The RP2040's only ground is its exposed pad, ringed by its pins where no pour can reach: four vias near its
    corners take it to the top ground plane (tented there, like every via). TESTEN, grounded, has its own via just in
    front of its pin. The solder paste on the pad is cut into five windows clear of the vias (EP_PASTE)."""
    import pcbnew
    u1 = placed["U1"]
    cx, cy = pad_centre(u1)
    for dx, dy in EP_VIAS:
        via(B, "GND", cx + dx, cy + dy)
    x, y = pad_xy(u1, 19)  # out to a via of its own in front (inside, the 3.3 V link of IOVDD 22 passes)
    track(B, "GND", x, y, x, y + 0.45, width=0.2)
    track(B, "GND", x, y + 0.45, x + 0.15, y + 1.01, width=0.2)
    via(B, "GND", x + 0.15, y + 1.01)
    windows = [p for p in u1.Pads() if p.GetNumber() == "" and not p.IsOnCopperLayer()]
    layers = windows[0].GetLayerSet()
    for p in windows:
        u1.Remove(p)
    for (dx, dy), (w, h) in EP_PASTE:
        pad = pcbnew.PAD(u1)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT)
        pad.SetRoundRectRadiusRatio(0.15)
        pad.SetLayerSet(layers)
        pad.SetSize(pcbnew.VECTOR2I(pcbnew.FromMM(w), pcbnew.FromMM(h)))
        u1.Add(pad)
        pad.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx + dx), pcbnew.FromMM(cy + dy)))


def rp2040_core(B, placed):
    """The 1.1 V core supply, drawn here: VREG_VOUT (45) and DVDD (50) on the back side and DVDD (23) on the front are
    joined under the package, in the ring between the pins and the exposed pad (the autorouter does not reliably get
    across the package between the matrix lines); each pin's own capacitor is then a short hop outside."""
    u1 = placed["U1"]
    cx, cy = pad_centre(u1)
    r = 2.3  # the ring: pins end 3.0 mm from the centre, the exposed pad 1.6 mm
    p45, p50, p23 = (pad_xy(u1, n) for n in (45, 50, 23))
    sy = math.copysign(1.0, p45[1] - cy)  # the side 45 and 50 are on
    sx = math.copysign(1.0, (p45[0] + p23[0]) / 2 - cx)  # round the side nearer to 45 and 23
    a, b = (p45[0], cy + sy * r), (p50[0], cy + sy * r)
    path(B, "1V1", [p45, a, b, p50], width=0.2)
    path(B, "1V1", [a, (cx + sx * r, a[1]), (cx + sx * r, cy - sy * r), (p23[0], cy - sy * r), p23], width=0.2)


def swd_lines(B, placed):
    """SWCLK, SWDIO and RUN (pins 24-26) straight from their pins to their pads in the row in front of the package,
    drawn here: between the matrix lines that come down on the left and the RP2040's own capacitors on the right the
    autorouter does not reliably find a way out for all three."""
    u1 = placed["U1"]
    for k, (pin, ref) in enumerate(((24, "TP2"), (25, "TP1"), (26, "TP5"))):
        x, y = pad_xy(u1, pin)
        tx, ty = pad_centre(placed[ref])
        net = placed[ref].Pads()[0].GetNetname()
        bend = ty - (x - tx) - 1.0  # 45 degrees across to the pad's column, 1 mm before it
        path(B, net, [(x, y), (x, bend), (tx, bend + (x - tx)), (tx, ty)] if tx != x else [(x, y), (tx, ty)], width=0.2)


def assign_matrix_pins(B, u1):
    """Map ROW*/COL* nets and the status LED onto the RP2040's GPIO pads on the two sides facing along the strip, so
    that the fan-out does not cross itself: nets and pads are both sorted by angle around the package and matched
    in order. Returns the RMK pin names of the rows, the columns and the LED, and {pad: net}."""
    import pcbnew
    cx, cy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    nets = sorted(n for n in B.nets if n.startswith(("ROW", "COL"))) + ["LED_RED"]
    pool = [p for p in RP_GPIO if p not in RP_FIXED and any(p in side for side in MATRIX_SIDES)]
    assert len(nets) <= len(pool), "%d lines but only %d free pads" % (len(nets), len(pool))
    target = {}
    for fp in B.footprints:
        for p in fp.Pads():
            n = p.GetNetname()
            if n in nets and fp.GetReference() != "U1":
                x, y = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
                d = (x - cx) ** 2 + (y - cy) ** 2
                if n not in target or d < target[n][0]:
                    target[n] = (d, x, y)

    def key(x, y):  # angle around the package, starting from straight behind it (never inside the key area)
        return (math.atan2(y - cy, x - cx) - 1.5 * math.pi) % (2 * math.pi)

    # the pads are taken from the two sides in proportion to the lines that leave on each side
    nets_sorted = sorted(nets, key=lambda n: key(target[n][1], target[n][2]))
    right = [p for p in pool if pad_xy(u1, p)[0] > cx]
    left = [p for p in pool if pad_xy(u1, p)[0] < cx]
    n_right = sum(1 for n in nets if target[n][1] > cx)
    n_right = min(max(n_right, len(nets) - len(left)), len(right))
    pads = sorted(right, key=lambda n: key(*pad_xy(u1, n)))[-n_right:] if n_right else []
    pads += sorted(left, key=lambda n: key(*pad_xy(u1, n)))[:len(nets) - n_right]
    pads_sorted = sorted(pads, key=lambda n: key(*pad_xy(u1, n)))
    mapping = dict(zip(nets_sorted, pads_sorted))
    for net, pad in mapping.items():
        u1.FindPadByNumber(str(pad)).SetNet(B.net(net))
    n_rows = sum(1 for n in nets if n.startswith("ROW"))
    n_cols = sum(1 for n in nets if n.startswith("COL"))
    rows = [rp_pin(mapping["ROW%d" % r]) for r in range(n_rows)]
    cols = [rp_pin(mapping["COL%d" % c]) for c in range(n_cols)]
    gpio = {str(pad): net for net, pad in mapping.items()}
    return rows, cols, rp_pin(mapping["LED_RED"]), gpio


def gnd_via(B, fp, reach=0.95):
    """A via just beyond a two-pad part's ground pad, along the part, joined to it by a short track."""
    pads = {p.GetNetname(): p for p in fp.Pads()}
    g, other = pads["GND"], [p for n, p in pads.items() if n != "GND"][0]
    gx, gy = pcbnew_mm(g.GetPosition().x), pcbnew_mm(g.GetPosition().y)
    ox, oy = pcbnew_mm(other.GetPosition().x), pcbnew_mm(other.GetPosition().y)
    d = math.hypot(gx - ox, gy - oy)
    stub(B, "GND", gx, gy, gx + (gx - ox) / d * reach, gy + (gy - oy) / d * reach, width=0.3)


def enlarge_hole(fp, d):
    import pcbnew
    size = pcbnew.VECTOR2I(pcbnew.FromMM(d), pcbnew.FromMM(d))
    for p in fp.Pads():
        p.SetDrillSize(size)
        p.SetSize(size)


def pad_centre(fp):
    import pcbnew
    return pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y)


def keepout(B, x0, y0, x1, y1, layers=None, pours=False, vias=False, tracks=False, footprints=False, name=None):
    """Rule area on the given layers (default both): no tracks (unless tracks=True), no vias (unless vias=True), no
    pours (unless pours=True); footprints=True forbids footprints too."""
    import pcbnew
    z = pcbnew.ZONE(B.b)
    z.SetIsRuleArea(True)
    if name:
        z.SetZoneName(name)
    z.SetDoNotAllowTracks(not tracks)
    z.SetDoNotAllowVias(not vias)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowZoneFills(not pours)
    z.SetDoNotAllowFootprints(footprints)
    ls = pcbnew.LSET()
    for layer in layers or (pcbnew.F_Cu, pcbnew.B_Cu):
        ls.AddLayer(layer)
    z.SetLayerSet(ls)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        o.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    B.b.Add(z)


def track(B, net, x0, y0, x1, y1, width=0.25, locked=False, layer="B"):
    import pcbnew
    t = pcbnew.PCB_TRACK(B.b)
    t.SetLocked(locked)
    t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(x0), pcbnew.FromMM(y0)))
    t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(x1), pcbnew.FromMM(y1)))
    t.SetWidth(pcbnew.FromMM(width))
    t.SetLayer(pcbnew.B_Cu if layer == "B" else pcbnew.F_Cu)
    t.SetNet(B.net(net))
    B.b.Add(t)


def via(B, net, x, y):
    import pcbnew
    v = pcbnew.PCB_VIA(B.b)
    v.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    v.SetDrill(pcbnew.FromMM(0.3))
    v.SetWidth(pcbnew.FromMM(0.6))
    v.SetNet(B.net(net))
    B.b.Add(v)


def pcbnew_mm(v):
    import pcbnew
    return pcbnew.ToMM(v)


def path(B, net, pts, width=0.3):
    """Pre-routed bottom-side polyline, locked (the autorouter keeps it as it is)."""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        track(B, net, x0, y0, x1, y1, width, locked=True)


def stub(B, net, x0, y0, x1, y1, width=0.25):
    """Pre-routed bottom-side track ending in a via (the autorouter keeps it and continues from the via)."""
    track(B, net, x0, y0, x1, y1, width)
    via(B, net, x1, y1)


SILK_MIN_TEXT = 1.0  # mm: JLCPCB's smallest legible silkscreen text (line 0.16 mm, its minimum is 0.153)


def label(B, text, x, y, size=1.0, angle=0):
    """Bottom silkscreen text (mirrored, so it reads right from below), never under SILK_MIN_TEXT."""
    import pcbnew
    size = max(size, SILK_MIN_TEXT)
    s = pcbnew.PCB_TEXT(B.b)
    s.SetText(text)
    s.SetLayer(pcbnew.B_SilkS)
    s.SetMirrored(True)
    s.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    s.SetTextThickness(pcbnew.FromMM(0.16 if size < 1.2 else 0.2))
    s.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    s.SetTextAngleDegrees(angle)
    s.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    B.b.Add(s)


def labels(B, placed, top):
    """What a builder needs to read on the bottom: the SWD pads, the jumper, the LED, the VBUS test point, the BOOT
    and RESET buttons, the headset jack and the board's name."""
    # the SWD row (2 mm pitch): each pad's name under it or above it, alternately, "SWD" beside the row
    for ref, text, dy in (("TP2", "CLK", 1.45), ("TP1", "DIO", -1.3), ("TP5", "RST", 1.45), ("TP4", "GND", -1.3)):
        x, y = pad_centre(placed[ref])
        label(B, text, x, y + dy)
    x, y = pad_centre(placed["TP4"])
    label(B, "SWD", x - 2.6, y + 0.4)
    x, y = pad_centre(placed["TP3"])
    label(B, "3V3", x, y + 1.7)
    x, y = pad_centre(placed["TP6"])
    label(B, "VBUS", x, y + 2.3, 0.7)
    x, y = pad_centre(placed["D103"])
    label(B, "CAPS", x - 2.7, y + 0.4)  # beside the LED (its resistor is below it, the USB-C on its right)
    for ref, text, dx, dy in (("JP3", "-6dB", 0.0, 1.75),):
        x, y = pad_centre(placed[ref])
        label(B, text, x + dx, y + dy, 0.7)
    for ref, text in (("SW101", "BOOT"), ("SW102", "RESET")):
        x, y = pad_centre(placed[ref])
        label(B, text, x, y + 3.6, 0.8)
    x, y = pad_centre(placed["J3"])
    label(B, "HEADSET (CTIA)", x - 1.0, y + 7.3, 0.8)
    label(B, "LIRA  wired  rev B", 88.0, top + 12.0, 1.5)
