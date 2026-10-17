"""Writes the KiCad schematic of the board from pcb/circuit.py (and the matrix pin map chosen by gen_pcb.py).

    $KPY pcb/gen_schematic.py     -> build/sch/lira.kicad_sch (+ .kicad_pro)

Every pin carries a global label with its net name (no wires between parts), which is what the ERC, the netlist
export and the checks need; symbols come from KiCad's own libraries (embedded) except the module, the charger and
the reset button, drawn as plain boxes. The deviations from the reference design are printed on the sheet.
"""
import datetime
import json
import re
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import circuit  # noqa: E402
import kicad_sym  # noqa: E402
import layout as L  # noqa: E402
from paths import BUILD  # noqa: E402

G = 1.27  # schematic grid (mm)
REVISION = "B"  # the board revision, in the title block (and on the PCB's silkscreen, pcb/electronics.py)
FONT = "(effects (font (size 1.27 1.27)))"


def uid():
    return str(uuid.uuid4())


def snap(v):
    return round(round(v / G) * G, 2)


# ------------------------------------------------------------------------------------------ custom symbols

def box_symbol(name, left, right, width=20.32, pin_len=3.81, ref="U"):
    """A rectangle with pins: left/right = [(number, pin_name, electrical type)], top to bottom."""
    n = max(len(left), len(right))
    h = (n + 1) * 2.54
    half_w, half_h = width / 2, h / 2
    out = ['(symbol "%s" (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)' % name,
           '  (property "Reference" "%s" (at %g %g 0) %s)' % (ref, -half_w, half_h + 1.27, FONT),
           '  (property "Value" "%s" (at %g %g 0) %s)' % (name, -half_w, -half_h - 1.27, FONT),
           '  (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           '  (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))',
           '  (symbol "%s_0_1" (rectangle (start %g %g) (end %g %g) (stroke (width 0.254) (type default)) '
           '(fill (type background))))' % (name, -half_w, half_h, half_w, -half_h),
           '  (symbol "%s_1_1"' % name]
    pins = {}
    for side, items in (("L", left), ("R", right)):
        for i, (num, pname, ptype) in enumerate(items):
            y = half_h - 2.54 * (i + 1)
            if side == "L":
                x, angle = -half_w - pin_len, 0
            else:
                x, angle = half_w + pin_len, 180
            out.append('    (pin %s line (at %g %g %d) (length %g) (name "%s" %s) (number "%s" %s))' % (
                ptype, x, y, angle, pin_len, pname, FONT, num, FONT))
            pins[str(num)] = (x, y, angle)
    out.append("  ))")
    return "\n".join(out), pins


def e73_symbol():
    fixed_left = [(27, "VBUS", "power_in"), (19, "VDD", "power_in"), (23, "VDDH", "power_in"), (25, "DCCH", "passive"),
                  (5, "GND", "power_in"), (21, "GND", "passive"), (24, "GND", "passive"),
                  (31, "D+", "bidirectional"), (29, "D-", "bidirectional"), (26, "P0.18/RESET", "input"),
                  (37, "SWDIO", "bidirectional"), (39, "SWDCLK", "input"), (11, "P0.00/XL1", "passive"),
                  (13, "P0.01/XL2", "passive"), (9, "P0.31/AIN7", "bidirectional"), (40, "P1.04", "bidirectional"),
                  (41, "P0.09/NFC1", "bidirectional"), (43, "P0.10/NFC2", "bidirectional")]
    gpio = [(p, circuit.E73_PINS[p], "bidirectional") for p in circuit.E73_GPIO]
    return box_symbol("E73", fixed_left, gpio, width=33.02)


def mcp73831_symbol():
    return box_symbol("MCP73831", [(4, "VDD", "power_in"), (1, "STAT", "tri_state"), (2, "VSS", "power_in")],
                      [(3, "VBAT", "power_out"), (5, "PROG", "passive")], width=15.24)


def tps22919_symbol():
    return box_symbol("TPS22919", [(1, "IN", "power_in"), (3, "ON", "input"), (2, "GND", "power_in")],
                      [(6, "VOUT", "power_out"), (5, "QOD", "passive"), (4, "NC", "no_connect")], width=15.24)


def tps7a02_symbol():
    return box_symbol("TPS7A02", [(1, "IN", "power_in"), (3, "EN", "input"), (2, "GND", "power_in")],
                      [(5, "OUT", "power_out"), (4, "NC", "no_connect")], width=12.7)


def tpa6132a2_symbol():
    left = [(14, "VDD", "power_in"), (13, "EN", "input"), (6, "G0", "input"), (7, "G1", "input"), (1, "INL-", "input"),
            (2, "INL+", "input"), (3, "INR+", "input"), (4, "INR-", "input"), (10, "PGND", "power_in"),
            (17, "EP", "passive")]
    right = [(16, "OUTL", "output"), (5, "OUTR", "output"), (15, "SGND", "passive"), (12, "HPVDD", "power_out"),
             (8, "HPVSS", "power_out"), (11, "CPP", "passive"), (9, "CPN", "passive")]
    return box_symbol("TPA6132A2", left, right, width=20.32)


def sw_push_4_symbol():
    return box_symbol("SW_PUSH_4", [(1, "1", "passive"), (2, "2", "passive")], [(4, "4", "passive"), (3, "3", "passive")],
                      width=10.16, ref="SW")


def ch334p_symbol():
    left = [(15, "V5", "power_in"), (16, "VDD33", "power_in"), (2, "XI", "input"), (1, "XO", "output"),
            (13, "RESET#/CDP", "input"), (14, "PGANG", "bidirectional"), (17, "GND", "power_in")]
    right = [(12, "DPU", "bidirectional"), (11, "DMU", "bidirectional"), (10, "DP1", "bidirectional"),
             (9, "DM1", "bidirectional"), (8, "DP2", "bidirectional"), (7, "DM2", "bidirectional"),
             (6, "DP3", "bidirectional"), (5, "DM3", "bidirectional"), (4, "DP4", "bidirectional"),
             (3, "DM4", "bidirectional")]
    return box_symbol("CH334P", left, right, width=22.86)


def cm108b_symbol():
    left = [(29, "AVDD", "power_in"), (34, "AVDD", "power_in"), (35, "DVDD", "power_in"), (8, "DREG18", "power_out"),
            (9, "DREG33", "power_out"), (37, "AREG36", "power_out"), (26, "VREF", "passive"), (31, "LOBS", "output"),
            (41, "USBDP", "bidirectional"), (42, "USBDM", "bidirectional"), (23, "TEST", "input"),
            (14, "DVSS", "power_in"), (36, "DVSS", "passive"), (24, "AVSS", "passive"), (33, "AVSS", "passive"),
            (7, "PWRSEL", "input"), (10, "MODE", "input"), (22, "ADSEL", "input"), (38, "MSEL", "input"),
            (6, "MUTER", "input"), (18, "MUTEP", "input"), (39, "VOLUP", "input"), (48, "VOLDN", "input"),
            (40, "PDSW", "open_collector")]
    right = [(30, "LOL", "output"), (32, "LOR", "output"), (25, "VBIAS", "output"), (27, "MICIN", "input"),
             (1, "SPDIFO", "output"), (2, "DR", "input"), (3, "DW", "output"), (4, "SK", "output"), (5, "CS", "output"),
             (12, "LEDO", "output"), (21, "LEDR", "output"), (13, "GPIO3", "bidirectional"),
             (15, "GPIO4", "bidirectional"), (43, "GPIO1", "bidirectional"), (16, "SDIN", "input"),
             (17, "ADSCLK", "output"), (19, "ADLRCK", "output"), (20, "ADMCLK", "output"), (44, "SDOUT", "output"),
             (45, "DAMCLK", "output"), (46, "DALRCK", "output"), (47, "DASCLK", "output"), (11, "NC", "no_connect"),
             (28, "NC", "no_connect")]
    return box_symbol("CM108B", left, right, width=25.4)


CUSTOM = {"lira:E73": e73_symbol, "lira:MCP73831": mcp73831_symbol, "lira:SW_PUSH_4": sw_push_4_symbol,
          "lira:TPS22919": tps22919_symbol, "lira:TPA6132A2": tpa6132a2_symbol, "lira:TPS7A02": tps7a02_symbol,
          "lira:CH334P": ch334p_symbol, "lira:CM108B": cm108b_symbol}


def sexpr_end(text, start):
    """Index just past the S-expression that opens at text[start]."""
    depth, i, quoted = 0, start, False
    while True:
        c = text[i]
        if quoted:
            if c == "\\":
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1


def library_symbol(spec):
    """(lib_symbols entry text, {pin number: (x, y, angle)}) of a KiCad library symbol, flattened and renamed
    'Lib:Name' as a schematic embeds it."""
    lib, name = spec.split(":")
    block = kicad_sym.symbol_text(lib, name)
    m = re.search(r'\(extends "([^"]+)"\)', block)
    if m:
        parent = m.group(1)
        pblock = kicad_sym.symbol_text(lib, parent)
        # the derived symbol only redefines properties: take the parent's drawing with every property the derived
        # one sets (value, footprint, datasheet, description, keywords, footprint filters), so that the embedded copy
        # matches the library's (ERC: lib_symbol_mismatch)
        props = dict(re.findall(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', block))
        for k, v in props.items():
            if '(property "%s" ' % k in pblock:
                pblock = re.sub(r'\(property "%s" "(?:[^"\\]|\\.)*"' % re.escape(k),
                                lambda _m: '(property "%s" "%s"' % (k, v), pblock, count=1)
            else:  # a property only the derived symbol has (ki_fp_filters): copied whole after the parent's last one
                at = pblock.rindex("(property ")
                end = sexpr_end(pblock, at)
                pblock = pblock[:end] + " " + block[block.index('(property "%s" ' % k):sexpr_end(block, block.index(
                    '(property "%s" ' % k))] + pblock[end:]
        block = pblock.replace('(symbol "%s_' % parent, '(symbol "%s_' % name)
        block = block.replace('(symbol "%s"' % parent, '(symbol "%s"' % name, 1)
    pins = {num: (x, y, angle) for num, _, _, x, y, angle in kicad_sym.pins(block)}
    block = block.replace('(symbol "%s"' % name, '(symbol "%s"' % spec, 1)
    return block, pins


# ------------------------------------------------------------------------------------------------ the sheet

class Sheet:
    def __init__(self, title):
        self.title = title
        self.root = uid()
        self.libs = {}  # symbol spec -> (text, pins)
        self.items = []
        self.dy = 0  # added to every y from then on (room for the list of differences above the circuit)

    def symbol(self, spec):
        if spec not in self.libs:
            if spec in CUSTOM:
                text, pins = CUSTOM[spec]()
                name = spec.split(":")[1]
                self.libs[spec] = (text.replace('(symbol "%s"' % name, '(symbol "%s"' % spec, 1), pins)
            else:
                self.libs[spec] = library_symbol(spec)
        return self.libs[spec]

    def text(self, s, x, y, size=1.27, bold=False):
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        y += self.dy
        self.items.append('(text "%s" (exclude_from_sim no) (at %g %g 0) (effects (font (size %g %g)%s) '
                          '(justify left bottom)) (uuid "%s"))' % (s, x, y, size, size, " (bold yes)" if bold else "", uid()))

    def label(self, net, x, y, angle):
        just = "left" if angle in (0, 90) else "right"
        self.items.append('(global_label "%s" (shape passive) (at %g %g %d) (fields_autoplaced yes) '
                          '(effects (font (size 1.27 1.27)) (justify %s)) (uuid "%s") '
                          '(property "Intersheetrefs" "${INTERSHEET_REFS}" (at %g %g 0) '
                          '(effects (font (size 1.27 1.27)) (hide yes))))' % (net, x, y, angle, just, uid(), x, y))

    def wire(self, x1, y1, x2, y2):
        self.items.append('(wire (pts (xy %g %g) (xy %g %g)) (stroke (width 0) (type default)) (uuid "%s"))' % (
            x1, y1, x2, y2, uid()))

    def no_connect(self, x, y):
        self.items.append('(no_connect (at %g %g) (uuid "%s"))' % (x, y, uid()))

    def lead(self, net, x, y, angle):
        """Connect the pin end (x, y) whose pin points in `angle` towards its body to a global label:
        sideways pins get the label directly, vertical pins a short L-shaped wire and a horizontal label."""
        if angle == 0:  # pin on the left side of the body
            self.label(net, x, y, 180)
        elif angle == 180:
            self.label(net, x, y, 0)
        else:
            dy = -2.54 if angle == 270 else 2.54  # 270: pin on top (goes up), 90: pin at the bottom
            self.wire(x, y, x, y + dy)
            self.wire(x, y + dy, x + 2.54, y + dy)
            self.label(net, x + 2.54, y + dy, 0)

    def place(self, part, x, y, show_value=True):
        """Symbol instance of a circuit.Part at (x, y) (rotation 0) with a label or no-connect on every pin."""
        self.placed = getattr(self, "placed", set()) | {part.ref}
        text, pins = self.symbol(part.symbol)
        x, y = snap(x), snap(y + self.dy)
        # reference above the symbol, value below it (the pins' extent approximates the body)
        top = y - max(py for _, py, _ in pins.values()) - 1.5
        bottom = y - min(py for _, py, _ in pins.values()) + 3.0
        left = x + min(px for px, _, _ in pins.values())
        right = x + max(px for px, _, _ in pins.values()) + 1.27
        # the value goes where no label is: right of the body for parts with vertical pins, below it otherwise
        vertical = any(a in (90, 270) for _, _, a in pins.values())
        vx, vy = (right, y + 0.6) if vertical and len(pins) <= 2 else (left, bottom)
        props = [('Reference', part.ref, False, left, top), ('Value', part.value if show_value else "", not show_value, vx, vy),
                 ('Footprint', part.footprint, True, x, y), ('Datasheet', "", True, x, y), ('Description', part.note, True, x, y)]
        if part.lcsc:
            props.append(("LCSC", part.lcsc, True, x, y))
        prop_text = "\n".join('    (property "%s" "%s" (at %g %g 0) (effects (font (size 1.27 1.27))%s))' % (
            k, v.replace("\\", "\\\\").replace('"', '\\"'), px, py, " (hide yes)" if hide else " (justify left)")
            for k, v, hide, px, py in props)
        pin_text = "\n".join('    (pin "%s" (uuid "%s"))' % (num, uid()) for num in pins)
        self.items.append(
            '(symbol (lib_id "%s") (at %g %g 0) (unit 1) (exclude_from_sim no) (in_bom %s) (on_board yes) (dnp %s) '
            '(uuid "%s")\n%s\n%s\n    (instances (project "lira" (path "/%s" (reference "%s") (unit 1)))))'
            % (part.symbol, x, y, "yes" if part.lcsc else "no", "yes" if part.dnp else "no", uid(), prop_text,
               pin_text, self.root, part.ref))
        for num, (px, py, angle) in pins.items():
            ex, ey = round(x + px, 2), round(y - py, 2)  # symbol y points up, sheet y points down
            net = part.pins.get(num, (None, None))[1] if num in part.pins else None
            if net:
                self.lead(net, ex, ey, angle)
            else:
                self.no_connect(ex, ey)

    def power_flag(self, net, x, y):
        text, pins = self.symbol("power:PWR_FLAG")
        x, y = snap(x), snap(y + self.dy)
        self.flags = getattr(self, "flags", 0) + 1
        n = self.flags
        self.items.append(
            '(symbol (lib_id "power:PWR_FLAG") (at %g %g 0) (unit 1) (exclude_from_sim no) (in_bom yes) '
            '(on_board yes) (dnp no) (uuid "%s")\n'
            '    (property "Reference" "#FLG%d" (at %g %g 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '    (property "Value" "PWR_FLAG" (at %g %g 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
            '    (pin "1" (uuid "%s"))\n'
            '    (instances (project "lira" (path "/%s" (reference "#FLG%d") (unit 1)))))'
            % (x, y, uid(), n, x, y - 5, x, y - 7.5, uid(), self.root, n))
        self.lead(net, x, y, 90)

    def write(self, path, paper="A1"):
        libs = "\n".join(t for t, _ in self.libs.values())
        out = ['(kicad_sch', '  (version 20250114)', '  (generator "eeschema")', '  (generator_version "9.0")',
               '  (uuid "%s")' % self.root, '  (paper "%s")' % paper,
               '  (title_block (title "%s") (date "%s") (rev "%s") (company "generated by source/pcb/gen_schematic.py"))'
               % (self.title, datetime.date.today().isoformat(), REVISION),
               '  (lib_symbols', libs, '  )'] + self.items + [
               '  (sheet_instances (path "/" (page "1")))', '  (embedded_fonts no)', ')']
        path.write_text("\n".join(out), encoding="utf-8")


# ------------------------------------------------------------------------------------------------- layout

def build():
    iface = json.loads((BUILD / "pcb/interface.json").read_text())
    gpio = {int(k): v for k, v in iface["gpio"].items()}
    parts = {p.ref: p for p in circuit.electronics(gpio) + circuit.matrix(L.KEYS)}
    sh = Sheet("Lira")
    sh.text("Lira: nRF52840 (Ebyte E73-2G4M08S1C), USB-C + Li-Po, %d keys, built-in USB sound card" % len(L.SWITCHES),
            20, 18, 2.54, True)
    sh.text("Power / USB / programming copied from the BlueMicro840 (jpconstantineau/NRF52-Board), a board built with this "
            "module, assembled by JLCPCB and sold. Differences from it:", 20, 23)
    for i, d in enumerate(circuit.DEVIATIONS):
        sh.text("%d. %s" % (i + 1, d), 22, 27 + 3.2 * i)
    # everything below starts 6 mm under the last difference (the layout was drawn for a list ending at y 56)
    sh.dy = max(0.0, snap(27 + 3.2 * (len(circuit.DEVIATIONS) - 1) + 6 - 62))

    def block(title, x, y):
        sh.text(title, x, y, 1.778, True)

    # --- USB and ESD
    block("USB-C (sink: 5.1k on each CC) and ESD protection", 20, 62)
    sh.place(parts["J1"], 45, 95)
    sh.place(parts["R108"], 82, 80)
    sh.place(parts["R109"], 97, 80)
    sh.place(parts["R101"], 112, 80)
    sh.place(parts["U4"], 92, 108)
    sh.place(parts["R126"], 112, 110)
    sh.place(parts["C107"], 121, 110)
    sh.place(parts["D108"], 72, 122)
    sh.text("C107: VBUS bypass (deviation 10), damped by R126 (deviation 17)", 100, 125)
    sh.text("R101: VBUS bleeder (BlueMicro840 R3)", 100, 92)
    # --- power path, charger, battery
    block("Power path: USB through the Schottky, battery through the P-MOSFET (off while VBUS is present)", 130, 62)
    sh.place(parts["D101"], 152, 72)
    sh.place(parts["Q1"], 185, 72)
    sh.place(parts["C102"], 212, 75)
    sh.place(parts["C101"], 228, 75)
    sh.place(parts["TP8"], 244, 72)
    sh.place(parts["TP7"], 258, 72)
    block("Charger MCP73831 (BlueMicro840 U4 is a TP4054, same pins): 100 mA, 200 mA with JP1 closed; white LED "
          "on while charging", 130, 95)
    sh.place(parts["U2"], 152, 110)
    sh.place(parts["R103"], 180, 110)
    sh.place(parts["JP1"], 197, 110)
    sh.place(parts["R104"], 215, 110)
    sh.place(parts["D102"], 238, 110)
    sh.place(parts["R102"], 255, 110)
    sh.place(parts["TP6"], 268, 107)
    block("Battery: JST-PH, power switch (JP2 bypasses it), divider 10M / 10M + 10nF into P0.31 (BlueMicro840 R4 R6 C6: 806k / 2M + 1nF)", 130, 128)
    sh.place(parts["J2"], 136, 140)
    sh.place(parts["Q2"], 162, 140)
    sh.place(parts["SW101"], 184, 140)
    sh.place(parts["JP2"], 203, 140)
    sh.place(parts["R105"], 220, 140)
    sh.place(parts["R106"], 235, 140)
    sh.place(parts["C104"], 250, 140)
    # --- 3.3 V and crystal
    block("3.3 V regulator (BlueMicro840 U3, EN tied to VIN) and 32.768 kHz crystal (BlueMicro840 Y2 C1 C2)", 130, 160)
    sh.place(parts["U3"], 155, 175)
    sh.place(parts["C108"], 182, 175)
    sh.place(parts["TP3"], 196, 172)
    sh.place(parts["Y1"], 222, 172)
    sh.place(parts["C105"], 242, 175)
    sh.place(parts["C106"], 257, 175)
    # --- module, reset, LED, SWD
    block("nRF52840 module, normal-voltage mode (VDD = VDDH = 3.3 V); reset button; status LED on P1.04 (bootloader LED); SWD pads", 280, 62)
    sh.place(parts["U1"], 320, 120)
    sh.place(parts["SW102"], 395, 80)
    sh.place(parts["D103"], 395, 102)
    sh.place(parts["R107"], 415, 102)
    for i, ref in enumerate(("TP1", "TP2", "TP5", "TP4")):
        sh.place(parts[ref], 390 + 14 * i, 125)
    sh.place(parts["C103"], 395, 148)
    sh.place(parts["C109"], 410, 148)
    sh.text("C103, C109: at the module's VDD / VDDH pins", 388, 160)
    # --- power flags, so the ERC knows where the supplies come from
    block("Supplies: VBUS from the receptacle, BAT+ from the cell, VIN from the power path, codec supplies from "
          "VBUS through ferrite beads", 280, 160)
    for i, net in enumerate(("GND", "VBUS", "BAT+", "VIN", "AUD_AVDD", "AUD_DVDD")):
        sh.power_flag(net, 290 + 18 * i, 172)
    # --- USB hub (left, under the USB block) and sound card (right of the module)
    block("USB hub CH334P (datasheet V2.91)", 20, 135)
    sh.text("upstream from the receptacle, port 3 -> module, port 2 -> codec", 20, 139)
    sh.text("V5 = VDD33 = 3.3 V from U9, only with VBUS (datasheet 6.4)", 20, 143)
    sh.place(parts["U5"], 50, 172)
    sh.place(parts["Y2"], 100, 150)
    for i, ref in enumerate(("C110", "C111", "C112")):
        sh.place(parts[ref], 85 + 15 * i, 178)
    sh.place(parts["U9"], 104, 192)
    sh.text("12 MHz crystal without load capacitors (inside the CH334)", 20, 200)
    sh.text("RESET#, PGANG and ports 1 / 4 left open", 20, 204)
    block("Sound card CM108B (C-Media demo board v1.33 sheet 4, app notes v1.50); headset jack, CTIA", 440, 72)
    sh.text("Open pins: internal pulls select headset mode (MODE low), 100 mA bus power (PWRSEL high),", 440, 76)
    sh.text("internal ADC (ADSEL low), mixer on (MSEL high); R120-R123 strap them (10k). Jack: tip L, ring 1 R, ring 2 GND, sleeve mic.", 440, 79.5)
    sh.place(parts["U6"], 478, 122)
    audio = ("C118", "C119", "C138", "C139", "R120", "R121", "R122", "R123", "C120", "C121", "C122", "C117", "C115", "C116", "L101", "L102",
             "R110", "R111", "R114", "C127", "R115", "C128", "R116", "C129")
    for i, ref in enumerate(audio):
        col, row = divmod(i, 6)
        sh.place(parts[ref], 508 + 15 * col, 90 + 17 * row)
    # --- the sound card's supply switch, headphone amplifier and jack (under the key matrix)
    y1 = 300
    block("Sound card supply: TPS22919 load switch, on only in USB mode (P1.02); headphone amplifier TPA6132A2 "
          "(DirectPath, 0 dB; -6 dB with JP3 closed); headset jack, CTIA", 20, y1)
    sh.place(parts["U8"], 45, y1 + 30)
    for i, ref in enumerate(("C130", "R117", "R118", "C113", "C114")):
        sh.place(parts[ref], 75 + 15 * i, y1 + 30)
    sh.place(parts["U7"], 175, y1 + 40)
    amp = ("C123", "C126", "C133", "C134", "C135", "C136", "R112", "R113", "C137", "R124", "R125", "C124", "L103",
           "L104", "C125")
    for i, ref in enumerate(amp):
        col, row = divmod(i, 4)
        sh.place(parts[ref], 225 + 16 * col, y1 + 15 + 17 * row)
    sh.place(parts["JP3"], 305, y1 + 20)  # horizontal symbols, with room for their labels on both sides
    sh.place(parts["D104"], 305, y1 + 45)
    sh.place(parts["Q3"], 305, y1 + 62)
    sh.place(parts["J3"], 345, y1 + 30)
    for i, ref in enumerate(("D105", "D106", "D107")):
        sh.place(parts[ref], 390, y1 + 20 + 10 * i)
    import textwrap
    lines = ["Differences from the C-Media demo board:"]
    for i, d in enumerate(circuit.AUDIO_DEVIATIONS):
        lines += textwrap.wrap("%d. %s" % (i + 1, d), 150, subsequent_indent="   ")
    for i, line in enumerate(lines):
        sh.text(line, 20, y1 + 76 + 3.3 * i)
    # --- key matrix
    y0 = 215
    block("Key matrix, col2row: column -> switch -> diode (cathode on the row). Labels: (row,col) of each key.", 20, y0 - 5)
    keys = sorted(L.KEYS, key=lambda k: (k.row, k.col))
    for i, k in enumerate(keys, start=1):
        x = 30 + 29.21 * k.col
        y = y0 + 20.32 * k.row
        sh.place(parts["SW%d" % i], x, y)
        sh.place(parts["D%d" % i], x + 13.97, y + 7.62)
    out = BUILD / "sch"
    out.mkdir(parents=True, exist_ok=True)
    unplaced = sorted(r for r in parts if r not in sh.placed and not getattr(parts[r], "pcb_only", False))
    assert not unplaced, "parts with no place in the schematic: %s" % unplaced
    sh.write(out / "lira.kicad_sch")
    libs = sorted(p.stem for p in (HERE.parent / "lib").glob("*.pretty"))
    (out / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n%s\n)\n" % "\n".join(
        '  (lib (name "%s") (type "KiCad") (uri "${KIPRJMOD}/../../lib/%s.pretty") (options "") (descr ""))' % (n, n)
        for n in libs))
    custom = "\n".join(CUSTOM[k]()[0] for k in CUSTOM)
    (out / "lira.kicad_sym").write_text('(kicad_symbol_lib (version 20241209) (generator "gen_schematic")\n%s\n)\n' % custom)
    (out / "sym-lib-table").write_text('(sym_lib_table\n  (version 7)\n  (lib (name "lira") (type "KiCad") '
                                       '(uri "${KIPRJMOD}/lira.kicad_sym") (options "") (descr ""))\n)\n')
    (out / "lira.kicad_pro").write_text(json.dumps({"meta": {"filename": "lira.kicad_pro", "version": 3},
                                                          "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []}}))
    print("wrote %s: %d parts" % (out / "lira.kicad_sch", len(parts)))


if __name__ == "__main__":
    build()
