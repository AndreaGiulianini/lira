"""Placement of the electronics (everything that is not a key) in the strip behind the top row, bottom side.

The connectivity comes from pcb/circuit.py; this file only decides where each part goes and which module pad
takes which matrix line (chosen from the geometry so that the fan-out does not cross itself). A few connections are
drawn here instead of by the autorouter: the USB high-speed pair (usb_pair), the hub's downstream escapes, the
escape vias of the module's inner pads and of the codec's ground pins.
"""
import math

from circuit import E73_FIXED, E73_GPIO, E73_INNER_GPIO, E73_NEAR_ANTENNA, electronics as circuit_parts, nrf_pin

STRIP_DEPTH = 22.0  # mm of PCB behind the top row

X_USB = 110.0  # KiCad x of the USB-C receptacle (about 30% of the width, like the M0110 cord jack)
X_MCU = 135.0
X_CODEC = 200.0  # sound card: codec, its parts to the right of it, the headset jack on the back edge
X_JACK = 243.0
X_SW = 88.0  # power switch
SWD_PITCH = 2.54
# Antenna (the module's end at the back edge): no copper on either layer under it and for a margin past it. The
# matrix leaves the three pads next to the antenna free (E73_NEAR_ANTENNA), so the copper-free area reaches past them.
ANTENNA_KEEPOUT = 4.6  # depth from the back edge (mm)
ANTENNA_HALF_WIDTH = 13.0  # either side of the module's axis: no track runs along the back edge past the antenna
# Under the module, on its own layer (bottom): ground copper only (Ebyte E73 datasheet 5.1), apart from the escapes of
# the inner pads; the area, relative to the module centre (x0, y0, x1, y1)
UNDER_MODULE = (-2.8, -8.0, 5.0, 3.3)
ROW_PADS = (15, 17, 10, 8)  # front-edge and front-right pads of the module, for the 4 row lines
CODEC_VIA = 2.6  # ground vias under the codec, this far from its centre
HS_CORRIDOR = "usb-hs-corridor"  # rule area under the USB high-speed pair (finish_pcb.py finds it by name)
JACK_PEG = 1.0  # locating holes of the headset jack (HRO PJ-320D-4A drawing: 1.00 mm for 0.75 mm pegs)
# top-layer keep-outs (tracks only: the ground pour and vias stay), relative to the exposed pad's centre: the matrix
# lines must not cut the ground plane over the hub, its 12 MHz crystal and capacitors, or over the amplifier and its
# capacitors (the planes carry their ground returns)
HUB_KEEPOUT = (-2.6, -6.0, 6.2, 2.7)
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
    """ref -> (x, y, rotation) in board mm. The module's antenna end and every connector face the back edge
    (board y = top): on the bottom side KiCad mirrors the footprint top<->bottom, so orientation 0 already
    points a footprint's +y side towards the back edge."""
    m = X_MCU
    pos = {
        "U1": (m, top + 11.0, 0),
        # crystal and its caps right of the module's front corner (pads 11 / 13), leaving the front free for the
        # matrix lines that leave the front pads towards the keys
        "Y1": (m + 9.5, top + 19.0, 0), "C105": (m + 13.5, top + 19.0, 90), "C106": (m + 9.5, top + 22.0, 0),
        # battery divider at pad 9 (right side of the module), in a row below the side pads
        "R105": (m + 9.5, top + 16.0, 90), "R106": (m + 12.5, top + 16.0, 90), "C104": (m + 15.5, top + 16.0, 90),
        # reset button right of the module (left of it is the USB hub); SWD pads in one 2.54 mm column next to
        # pads 39 / 37 / 26 (pogo clip): SWCLK, SWDIO, GND, 3V3, RESET from the back edge forwards
        "SW102": (m + 21.0, top + 12.0, 0),
        "TP2": (m - 11.5, top + 6.5, 0), "TP1": (m - 11.5, top + 6.5 + SWD_PITCH, 0),
        "TP4": (m - 11.5, top + 6.5 + 2 * SWD_PITCH, 0), "TP3": (m - 11.5, top + 6.5 + 3 * SWD_PITCH, 0),
        "TP5": (m - 11.5, top + 6.5 + 4 * SWD_PITCH, 0),
        # power test points next to the charger / regulator
        "TP6": (82.5, top + 19.3, 0), "TP7": (85.5, top + 19.3, 0), "TP8": (88.5, top + 19.3, 0),
        # USB-C on the back edge (overhangs it by 0.4 mm), CC resistors and ESD array behind it; the ESD array is
        # turned so that D+ is the upper pin on both sides (the order of the hub's upstream pins)
        "J1": (X_USB, top - 0.4 + 3.65, 0), "R108": (X_USB - 5.5, top + 11.0, 90), "R109": (X_USB + 5.5, top + 10.6, 270),
        "U4": (X_USB, top + 12.5, 180), "R101": (X_USB - 7.5, top + 9.5, 90),
        # USB hub right behind the ESD array: upstream pins (left side) facing it, the crystal on its right, the
        # supply capacitors above it; ports 2 and 3 (front side) go down to the channel along the keys, port 3 to
        # the module, port 2 to the codec
        "U5": (X_USB + 6.5, top + 17.5, 180), "Y2": (X_USB + 10.55, top + 17.6, 90),
        "C110": (X_USB + 6.9, top + 13.8, 90), "C112": (X_USB + 8.6, top + 13.8, 90),
        "C111": (X_USB + 10.3, top + 13.8, 90),
        # power switch on the back edge (actuator protrudes 2 mm), bypass jumper behind it, charging / status LEDs
        "SW101": (X_SW, top + 1.8, 0), "JP2": (X_SW - 4.5, top + 8.5, 90),
        "D102": (97.0, top + 2.0, 90), "R102": (97.0, top + 5.2, 90),
        "D103": (101.0, top + 2.0, 90), "R107": (101.0, top + 5.2, 90),
        # power path and charger, its input (VBUS) and output (VBAT) capacitors next to its pins
        "D101": (X_SW, top + 9.5, 0), "Q1": (X_SW, top + 13.5, 0),
        "U2": (95.0, top + 12.0, 0), "C101": (91.6, top + 11.5, 270), "C107": (98.4, top + 11.5, 270),
        "R103": (91.5, top + 15.8, 0), "JP1": (95.0, top + 15.8, 0), "R104": (98.5, top + 15.8, 0),
        # 3.3 V regulator with its input and output capacitors next to its pins
        "U3": (103.0, top + 19.0, 0), "C102": (99.6, top + 19.0, 90), "C108": (106.4, top + 19.0, 90),
        # the module's own capacitors, right in front of its supply pins 23 (VDDH) and 19 (VDD)
        "C103": (m - 4.2, top + 20.4, 180), "C109": (m - 1.1, top + 20.4, 180),
        # battery connector on the left (the cell sits under the numpad), plug towards the back
        "J2": (65.0, top + 6.0, 180),
    }
    pos.update(audio_positions(top))
    return pos


def audio_positions(top):
    """The sound card, right of the middle bolt: codec (analog pins on its right side), its regulator capacitors
    around it, the microphone bias above the line outputs, the headphone amplifier between the codec and the jack
    (inputs facing the codec, charge pump towards the jack), the supply switch in front of them.
    Vertical parts: rotation 90 puts pad 1 towards the keys, 270 towards the back edge (bottom side)."""
    c, j = X_CODEC, X_JACK
    a, b = c + 6.6, c + 9.0  # first two columns right of the codec
    m = c + 16.6  # amplifier
    return {
        "U6": (c, top + 10.0, 0),
        # left side: core and I/O regulators (pins 8 / 9), with the demo board's 10 nF to DVDD next to them
        "C119": (c - 6.8, top + 7.4, 90), "C118": (c - 6.8, top + 10.6, 270),
        "C139": (c - 6.8, top + 4.2, 270), "C138": (c - 6.8, top + 13.8, 90),
        # front side: USB series resistors under pins 41 / 42, 3.6 V regulator capacitor under pin 37
        "R111": (c - 0.6, top + 17.8, 90), "R110": (c + 1.6, top + 17.8, 90), "C120": (c + 3.8, top + 17.8, 270),
        # right side, first column: microphone bias resistor, reference, line-out bias, analog and digital supply
        "R114": (a, top + 2.6, 90), "C121": (a, top + 6.3, 90), "C122": (a, top + 10.0, 90),
        "C117": (a, top + 13.7, 270), "C115": (a, top + 17.4, 270),
        # second column: bias filter, microphone coupling, the two supply ferrites, digital bulk capacitor
        "C127": (b, top + 2.6, 270), "C129": (b, top + 6.3, 270), "L101": (b, top + 10.0, 90),
        "L102": (b, top + 13.7, 90), "C116": (b, top + 17.4, 270),
        # microphone resistors along the back edge
        "R115": (c + 12.0, top + 2.0, 270), "R116": (c + 14.4, top + 2.0, 90),
        # amplifier input capacitors (right channel above, left below), amplifier and its own capacitors
        "C126": (c + 12.0, top + 7.6, 90), "C123": (c + 12.0, top + 12.6, 90),
        "U7": (m, top + 10.0, 0),
        "JP3": (m - 1.4, top + 5.6, 0), "R112": (m + 1.8, top + 5.6, 270), "C135": (m + 4.0, top + 6.6, 90),
        "C136": (m + 3.4, top + 9.9, 90), "C134": (m + 3.4, top + 13.2, 270), "C133": (m, top + 14.6, 270),
        # amplifier enable: 1M + 470 nF delay from P1.02, Schottky to switch it off at once
        "C137": (m + 2.2, top + 16.4, 270), "R113": (m + 4.6, top + 16.4, 90), "D104": (m + 4.0, top + 20.2, 0),
        # supply switch (VBUS -> AUD_5V) with its input capacitor and pull-down, AUD_5V bulk
        "U8": (c + 12.6, top + 17.6, 0), "C130": (c + 12.6, top + 20.4, 270), "R117": (c + 14.8, top + 20.8, 90),
        "R118": (c + 14.86, top + 17.6, 90), "C113": (m, top + 18.8, 90), "C114": (c + 14.4, top + 14.4, 90),
        # ferrites and 100 pF next to the jack's tip and ring 1 (a filter at the connector, against RF and ESD)
        "L104": (j - 9.2, top + 6.6, 90), "L103": (j - 9.2, top + 12.6, 90),
        "C125": (j - 6.6, top + 6.4, 90), "C124": (j - 6.6, top + 10.4, 90),
        # headset jack on the back edge: its nose (2 mm) overhangs the edge by 1.8 mm (the locating peg needs 0.8 mm
        # of board in front of its hole); microphone 100 pF in front of it, next to the sleeve pad
        "J3": (j, top + 6.55, 270),
        "C128": (j + 3.0, top + 16.4, 270),
        # explicit straps on the CM108B mode jumpers: the free gap left of the codec's capacitor column
        "R120": (191.2, top + 4.0, 90), "R121": (191.2, top + 7.5, 90),
        "R122": (191.2, top + 11.0, 90), "R123": (191.2, top + 14.5, 90),
        # jack ESD clamps, in the free area just right of the jack
        "D105": (250.6, top + 2.2, 90), "D106": (253.6, top + 2.2, 90), "D107": (256.6, top + 2.2, 90),
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
    n_lines = sum(1 for n in B.nets if n.startswith(("ROW", "COL")))
    free = [p for p in E73_GPIO if p not in E73_NEAR_ANTENNA and p not in E73_FIXED]
    assert n_lines <= len(free), "the pads next to the antenna would be needed"
    keepout(B, X_MCU - ANTENNA_HALF_WIDTH, top - 1.0, X_MCU + ANTENNA_HALF_WIDTH, top + ANTENNA_KEEPOUT)
    ux, uy = pad_centre(u1)
    x0, y0, x1, y1 = UNDER_MODULE
    keepout(B, ux + x0, uy + y0, ux + x1, uy + y1, layers=(pcbnew.B_Cu,), pours=True)
    usb_pair(B, placed)
    hub_ports(B, placed)
    for pad in placed["J3"].Pads():  # the jack's locating pegs: 1.0 mm holes as on the HRO drawing (KiCad: 1.6)
        if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            size = pcbnew.VECTOR2I(pcbnew.FromMM(JACK_PEG), pcbnew.FromMM(JACK_PEG))
            pad.SetDrillSize(size)
            pad.SetSize(size)
    for ref, path in MODELS.items():
        model = pcbnew.FP_3DMODEL()
        model.m_Filename = path
        placed[ref].Models().clear()
        placed[ref].Models().push_back(model)
    # the hub's exposed pad (its only ground) is ringed by its pins: a via at its centre, between the four paste
    # windows (the board cannot have filled vias, and an open via drains solder), takes it to the top ground plane,
    # which a top-layer keep-out keeps whole over the hub, its crystal and capacitors; each capacitor's ground pad
    # has its own via
    hx, hy = pad_xy(placed["U5"], 17)
    via(B, "GND", hx, hy)
    for ref in ("C110", "C111", "C112"):
        gnd_via(B, placed[ref])
    x0, y0, x1, y1 = HUB_KEEPOUT
    keepout(B, hx + x0, hy + y0, hx + x1, hy + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="hub")
    # the codec's ground pins sit between signal pins, where neither the pour nor the router can reach them: a short
    # track from each one inwards to a via under the chip's body (no exposed pad there), into the top ground pour
    u6 = placed["U6"]
    cx, cy = pad_centre(u6)
    for pin in (14, 24, 33, 36):
        x, y = pad_xy(u6, pin)
        if abs(x - cx) > abs(y - cy):
            stub(B, "GND", x, y, cx + math.copysign(CODEC_VIA, x - cx), y)
        else:
            stub(B, "GND", x, y, x, cy + math.copysign(CODEC_VIA, y - cy))
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
    x0, y0, x1, y1 = AMP_KEEPOUT
    keepout(B, ax + x0, ay + y0, ax + x1, ay + y1, layers=(pcbnew.F_Cu,), pours=True, vias=True, name="amplifier")
    x23, y23 = pad_xy(u6, 23)  # TEST, next to 24: to the same via
    x24, y24 = pad_xy(u6, 24)
    track(B, "GND", x23, y23, x24, cy + math.copysign(CODEC_VIA, y24 - cy))

    ports = {"usb": (X_USB, top), "switch": (X_SW, top), "window": (81.0, top, X_USB + 7.0),
             "battery": pos["J2"][:2], "reset": pos["SW102"][:2], "jack": (X_JACK, top)}
    for i, x in enumerate(BOLTS_X, start=1):
        fp = B.place("MountingHole", "MountingHole_3.2mm_M3", "HB%d" % i, x, top + 11.0, value="case bolt",
                     in_bom=False)
        enlarge_hole(fp, BOLT_HOLE)
    ports["bolts"] = [(x, top + 11.0) for x in BOLTS_X]
    rows, cols, gpio = assign_matrix_pins(B, u1)
    escape_inner_pads(B, u1)
    labels(B, placed, top)
    ports["matrix"] = dict(rows=rows, cols=cols, battery_adc="P0_31", status_led="P1_04")
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
    via(B, "VBUS", x_side, uy)  # where the charger's VBUS joins, on the bottom layer
    # the hub's V5 (pin 15) through its 1 uF: no top-layer track may cross the hub (keep-out in add_electronics), so
    # the feed runs on the bottom layer to a via just outside that area, then on the top layer to the A9 via
    v15, c110 = pad_xy(u5, 15), pad_xy(placed["C110"], 1)
    hx, hy = pad_xy(u5, 17)
    x_feed, y_feed = c110[0] + 0.85, hy + HUB_KEEPOUT[1] - 0.5  # down between C110 and C112, out of the keep-out
    path(B, "VBUS", [v15, (v15[0], c110[1])], width=0.3)  # (between the hub's pins 14 and 16)
    path(B, "VBUS", [(v15[0], c110[1]), (x_feed, c110[1]), (x_feed, y_feed)], width=0.4)
    via(B, "VBUS", x_feed, y_feed)
    x_turn = x_feed - (y_feed - y_link)  # 45 degrees up to the link's height
    for (x0, y0), (x1, y1) in (((x_feed, y_feed), (x_turn, y_link)), ((x_turn, y_link), (vb[0], y_link))):
        track(B, "VBUS", x0, y0, x1, y1, width=0.4, locked=True, layer="F")
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


def assign_matrix_pins(B, u1):
    """Map ROW*/COL* nets onto the module's free GPIO pads so that the fan-out does not cross itself: nets and pads
    are both sorted by angle around the module and matched in order (edge pads first, inner pads need an escape
    via; the pads next to the antenna stay free)."""
    import pcbnew
    cx, cy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    nets = sorted(n for n in B.nets if n.startswith(("ROW", "COL")))
    assert len(nets) <= len(E73_GPIO), "%d matrix lines but only %d free pads" % (len(nets), len(E73_GPIO))
    target = {}
    for fp in B.footprints:
        for p in fp.Pads():
            n = p.GetNetname()
            if n in nets:
                x, y = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
                d = (x - cx) ** 2 + (y - cy) ** 2
                if n not in target or d < target[n][0]:
                    target[n] = (d, x, y)
    def key(x, y):  # angle around the module, starting from straight behind it (never inside the key area)
        return (math.atan2(y - cy, x - cx) - 1.5 * math.pi) % (2 * math.pi)

    # the row lines run the length of the board: give them the edge pads facing the keys (front corner)
    rows_nets = sorted(n for n in nets if n.startswith("ROW"))
    row_pads = list(ROW_PADS[:len(rows_nets)])
    mapping = dict(zip(sorted(rows_nets, key=lambda n: key(target[n][1], target[n][2])),
                       sorted(row_pads, key=lambda n: key(*pad_xy(u1, n)))))
    others = [n for n in nets if n not in mapping]
    pool = [p for p in E73_GPIO if p not in row_pads and p not in E73_NEAR_ANTENNA and p not in E73_FIXED]
    pads = sorted(pool, key=lambda n: (n in E73_INNER_GPIO, n))[:len(others)]
    nets_sorted = sorted(others, key=lambda n: key(target[n][1], target[n][2]))
    pads_sorted = sorted(pads, key=lambda n: key(*pad_xy(u1, n)))
    mapping.update(zip(nets_sorted, pads_sorted))
    for net, pad in mapping.items():
        u1.FindPadByNumber(str(pad)).SetNet(B.net(net))
    n_rows = sum(1 for n in nets if n.startswith("ROW"))
    n_cols = sum(1 for n in nets if n.startswith("COL"))
    rows = [nrf_pin(mapping["ROW%d" % r]) for r in range(n_rows)]
    cols = [nrf_pin(mapping["COL%d" % c]) for c in range(n_cols)]
    gpio = {str(pad): net for net, pad in mapping.items()}
    return rows, cols, gpio


def escape_inner_pads(B, u1):
    """Dog-bone escape for the module pads under its body: short track towards the module centre + via, so the
    connection continues on the top layer (the autorouter cannot find these on its own)."""
    import pcbnew
    cx, cy = pcbnew.ToMM(u1.GetPosition().x), pcbnew.ToMM(u1.GetPosition().y)
    for n in sorted(E73_INNER_GPIO):
        pad = u1.FindPadByNumber(str(n))
        if not pad.GetNetname():
            continue
        x, y = pad_xy(u1, n)
        half = pcbnew.ToMM(pad.GetBoundingBox().GetWidth()) / 2
        reach = half + 0.55
        if abs(x - cx) > 4.1:  # inner column along the side: escape sideways, towards the module centre
            dx, dy = (1.0 if cx > x else -1.0), 0.0
        else:  # inner row at the front end: escape lengthwise, into the module body
            dx, dy = 0.0, (1.0 if cy > y else -1.0)
        stub(B, pad.GetNetname(), x, y, x + dx * reach, y + dy * reach)


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


def label(B, text, x, y, size=0.9):
    """Bottom silkscreen text (mirrored, so it reads right from below)."""
    import pcbnew
    s = pcbnew.PCB_TEXT(B.b)
    s.SetText(text)
    s.SetLayer(pcbnew.B_SilkS)
    s.SetMirrored(True)
    s.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    s.SetTextThickness(pcbnew.FromMM(0.15 if size < 1.2 else 0.2))
    s.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
    s.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
    B.b.Add(s)


def labels(B, placed, top):
    """What a builder needs to read on the bottom: the SWD pads, the battery polarity, the jumpers, the LEDs, the
    power test points, the reset button, the headset jack and the board's name."""
    import pcbnew
    for ref, text in (("TP2", "CLK"), ("TP1", "DIO"), ("TP4", "GND"), ("TP3", "3V3"), ("TP5", "RST")):
        x, y = pad_centre(placed[ref])
        label(B, text, x + 2.3, y + 0.35, 0.8)
    x, y = pad_centre(placed["TP2"])
    label(B, "SWD", x, y - 2.0, 0.8)
    for ref, text in (("TP6", "VBUS"), ("TP7", "VBAT"), ("TP8", "VIN")):
        x, y = pad_centre(placed[ref])
        label(B, text, x, y + 2.3, 0.7)
    for ref, text in (("D102", "CHG"), ("D103", "CAPS")):
        x, y = pad_centre(placed[ref])
        label(B, text, x, y + 1.9, 0.7)
    for ref, text, dx, dy in (("JP1", "200mA", 0.0, 1.9), ("JP2", "SW BYP", -3.2, 0.0), ("JP3", "-6dB", 0.0, -1.9)):
        x, y = pad_centre(placed[ref])
        label(B, text, x + dx, y + dy, 0.7)
    x, y = pad_centre(placed["SW102"])
    label(B, "RESET", x, y + 3.6, 0.8)
    x, y = pad_centre(placed["J3"])
    label(B, "HEADSET (CTIA)", x - 1.0, y + 7.3, 0.8)
    j2 = placed["J2"]
    for num, text in (("1", "+"), ("2", "-")):
        p = j2.FindPadByNumber(num).GetPosition()
        label(B, text, pcbnew.ToMM(p.x), pcbnew.ToMM(p.y) + 3.0, 1.2)
    label(B, "LIRA  rev A", 168.0, top + 4.0, 1.5)
