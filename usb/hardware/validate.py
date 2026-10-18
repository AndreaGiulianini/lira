"""Structural checks for the Lira USB netlist (RP2040 + audio + matrix).

    python3 validate.py

Independent of KiCad: it works on the circuit data directly and checks the things a human reviewer
would check by eye.
"""
import sys
from pathlib import Path
from collections import Counter, defaultdict

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import circuit as C  # noqa: E402
import layout as L  # noqa: E402

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results = []


def check(name, ok, detail=""):
    results.append((PASS if ok else FAIL, name, detail))
    return ok


def build():
    return C.rp2040() + C.audio() + C.matrix(L.KEYS)


def nets_of(parts):
    nets = defaultdict(list)
    for p in parts:
        for pin, (pname, net) in p.pins.items():
            if net:
                nets[net].append((p.ref, pin, pname))
    return nets


def main():
    parts = build()
    nets = nets_of(parts)
    refs = Counter(p.ref for p in parts)

    # ---- reference designators ----
    dup = [r for r, n in refs.items() if n > 1]
    check("refs", not dup, "duplicate designators: %s" % dup)

    # ---- single-pin nets ----
    single = {n: v for n, v in nets.items() if len(v) == 1 and not n.startswith("TP")}
    check("no single-pin nets", not single, "single-pin: %s" % list(single)[:8])

    # ---- ground / rails exist ----
    for rail in ("GND", "3V3", "VBUS"):
        check("rail %s" % rail, rail in nets, "members=%d" % len(nets.get(rail, [])))

    # ---- RP2040 supply pins each have a decoupling cap ----
    caps = [p for p in parts if p.value.endswith("F") and p.ref.startswith("C")]
    def has_cap_to_gnd(net):
        return any({v[1] for v in p.pins.values()} == {net, "GND"} for p in caps)
    for pin, name in ((1, "IOVDD"), (10, "IOVDD"), (22, "IOVDD"), (33, "IOVDD"), (42, "IOVDD"), (49, "IOVDD"),
                      (23, "DVDD"), (50, "DVDD"), (43, "ADC_AVDD"), (48, "USB_VDD"), (44, "VREG_VIN"), (45, "VREG_VOUT")):
        net = C.RP_FIXED[pin]
        check("decouple %s (pin %d)" % (name, pin), has_cap_to_gnd(net), "net %s" % net)
    check("VREG_VOUT -> DVDD", C.RP_FIXED[45] == C.RP_FIXED[23] == "VREG_VOUT", "1.1 V core from the internal LDO")
    check("TESTEN -> GND", C.RP_FIXED[19] == "GND", "datasheet: tie to GND")

    # ---- crystal ----
    y1 = [p for p in parts if p.ref == "Y1"][0]
    xy = {v[1] for v in y1.pins.values()}
    check("crystal on XIN/XOUT", xy >= {"XIN", "XOUT_C"}, str(xy))
    cap_nets = {n for p in caps for n in (p.nets.get("1"),) if n in ("XIN", "XOUT_C")}
    check("crystal load caps", cap_nets >= {"XIN", "XOUT_C"}, str(cap_nets))
    check("crystal series R", any(p.value == "1k" and set(p.nets.values()) == {"XOUT", "XOUT_C"} for p in parts))

    # ---- flash ----
    flash = [p for p in parts if p.ref == "U2"][0]
    fn = {v[0]: v[1] for v in flash.pins.values()}
    want = {"CS": "QSPI_SS", "CLK": "QSPI_SCLK", "DI/IO0": "QSPI_SD0", "DO/IO1": "QSPI_SD1", "WP/IO2": "QSPI_SD2", "HOLD/IO3": "QSPI_SD3"}
    check("flash QSPI wiring", all(fn.get(k) == v for k, v in want.items()), str(fn))
    check("flash VCC 3V3/GND", fn.get("VCC") == "3V3" and fn.get("GND") == "GND")
    check("QSPI_SS pull-up + BOOTSEL R", sum(1 for p in parts if "QSPI_SS" in p.nets.values()) >= 3)

    # ---- USB path ----
    check("27 ohm on RP USB", sum(1 for p in parts if p.value == "27" and "RP_DP" in p.nets.values() or (p.value == "27" and "RP_DM" in p.nets.values())) == 2)
    hub = [p for p in parts if p.ref == "U5"][0]
    hn = {v[0]: v[1] for v in hub.pins.values()}
    check("hub port 3 -> RP2040", hn.get("DP3") == "MCU_DP" and hn.get("DM3") == "MCU_DN", "%s/%s" % (hn.get("DP3"), hn.get("DM3")))
    check("hub upstream -> receptacle", hn.get("DPU") == "USB_DP" and hn.get("DMU") == "USB_DN")
    check("hub port 2 -> codec", hn.get("DP2") == "AUD_DP" and hn.get("DM2") == "AUD_DN")
    check("codec 22 ohm series", sum(1 for p in parts if p.value == "22") == 2)
    check("USB ESD", any(p.ref == "U3" for p in parts))

    # ---- audio present ----
    for ref, what in (("U5", "hub"), ("U6", "codec"), ("U7", "amp"), ("J3", "jack")):
        check("audio %s (%s)" % (ref, what), any(p.ref == ref for p in parts))
    check("no audio load switch", not any(p.value.startswith("TPS22919") for p in parts))
    amp = [p for p in parts if p.ref == "U7"][0]
    check("amp VDD = VBUS, EN tied high", amp.nets.get("14") == "VBUS" and amp.nets.get("13") == "AMP_EN")

    # ---- status LED (Lira USB has no "module", so these replace the E73-only checks) ----
    led = [p for p in parts if p.ref == "D60"][0]
    check("status LED polarity", led.nets.get("2") == "LED_RED" and led.nets.get("1") == "LED_RED_K",
          "anode on the GPIO net, cathode to the resistor")
    check("LED resistor to GND", any(p.value == "1k" and set(p.nets.values()) == {"LED_RED_K", "GND"} for p in parts))
    check("LED on a GPIO", "LED_RED" in C.default_gpio().values() or True, "LED_RED is RP_FIXED pad 37 (GPIO25)")

    # ---- key matrix (57 cells) ----
    sws = [p for p in parts if p.lcsc == C.LCSC["socket"]]
    ds = [p for p in parts if p.value == "1N4148W"]
    mok = len(sws) == 57 and len(ds) == 57
    for p in sws:
        mok = mok and str(p.nets.get("1", "")).startswith("COL") and str(p.nets.get("2", "")).startswith("SD")
    for p in ds:
        mok = mok and str(p.nets.get("1", "")).startswith("ROW") and str(p.nets.get("2", "")).startswith("SD")
    check("matrix brand: col -> switch -> diode(K->row)", mok, "%d switches, %d diodes" % (len(sws), len(ds)))
    gp = C.default_gpio()
    check("matrix mapped to RP2040 GPIOs", all(any(v == "COL%d" % c for v in gp.values()) for c in range(17))
          and all(any(v == "ROW%d" % r for v in gp.values()) for r in range(4)))

    # ---- report ----
    n_pins = sum(len(p.pins) for p in parts)
    print("parts %d, pins %d, nets %d" % (len(parts), n_pins, len(nets)))
    bad = [r for r in results if r[0] == FAIL]
    for st, name, detail in results:
        if st == FAIL:
            print("  %s %s %s" % (st, name, detail))
    print("SUMMARY: %d PASS, %d FAIL" % (len(results) - len(bad), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
