"""Proves that the three descriptions of the circuit agree, pin by pin:

    circuit.py (the intended connectivity)  ==  the PCB (what pcbnew will send to JLCPCB)  ==  the schematic

and writes build/netlist.json, the netlist the independent checks read.

    $KPY pcb/verify_netlist.py        (exit code 1 on any difference)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import pcbnew  # noqa: E402

import circuit  # noqa: E402
import layout as L  # noqa: E402
from paths import BUILD  # noqa: E402

PCB_ONLY_PREFIX = ("H", "ST")  # mounting holes, stabilizers: no electrical meaning


def circuit_pins(parts):
    return {(p.ref, num): net for p in parts for num, (name, net) in p.pins.items()}


def pcb_pins(board_file):
    """{(ref, pad): net or None} of every pad of every footprint on the board (duplicate pad numbers collapse)."""
    b = pcbnew.LoadBoard(str(board_file))
    out = {}
    for fp in b.GetFootprints():
        ref = fp.GetReference()
        if ref.startswith(PCB_ONLY_PREFIX):
            continue
        for p in fp.Pads():
            num = p.GetNumber()
            if not num:
                continue  # unnumbered mechanical pads
            net = p.GetNetname() or None
            key = (ref, num)
            if key in out and out[key] != net:
                print("PCB: pad %s.%s has two nets (%s, %s)" % (ref, num, out[key], net))
            out[key] = net
    return out


def schematic_pins(net_file):
    """{(ref, pin): net or None} from the netlist exported by kicad-cli (nets are named by the global labels)."""
    import kicad_sym
    tree = kicad_sym.parse(kicad_sym.tokenize(net_file.read_text(encoding="utf-8", errors="replace")))[0]
    nets = next(n for n in tree if isinstance(n, list) and n and n[0] == "nets")
    out = {}
    for net in nets[1:]:
        name = next(x[1] for x in net if isinstance(x, list) and x[0] == "name")
        value = None if name.startswith("unconnected-") else name
        for node in net:
            if isinstance(node, list) and node and node[0] == "node":
                ref = next(x[1] for x in node if isinstance(x, list) and x[0] == "ref")
                pin = next(x[1] for x in node if isinstance(x, list) and x[0] == "pin")
                if not ref.startswith("#"):
                    out[(ref, pin)] = value
    return out


def compare(what, expected, actual, allow_missing_in_actual=()):
    errors = []
    for key, net in sorted(expected.items()):
        if key not in actual:
            if key[0].startswith(allow_missing_in_actual) or net is None:
                continue  # mechanical pads (no net) need not exist in the schematic symbol
            errors.append("%s: %s.%s (%s) missing" % (what, key[0], key[1], net))
        elif actual[key] != net:
            errors.append("%s: %s.%s is on %s, circuit says %s" % (what, key[0], key[1], actual[key], net))
    for key, net in sorted(actual.items()):
        if key not in expected and net:
            errors.append("%s: %s.%s on %s is not in the circuit" % (what, key[0], key[1], net))
    return errors


def main():
    iface = json.loads((BUILD / "pcb/interface.json").read_text())
    gpio = {int(k): v for k, v in iface["gpio"].items()}
    parts = circuit.electronics(gpio) + circuit.matrix(L.KEYS)
    expected = circuit_pins(parts)
    errors = []
    board = BUILD / "pcb/lira.kicad_pcb"
    if not board.exists():
        board = BUILD / "pcb/lira-placed.kicad_pcb"
    errors += compare("PCB", expected, pcb_pins(board))
    net_file = BUILD / "sch/netlist.net"
    if net_file.exists():
        sch = schematic_pins(net_file)
        # a net that is only a label name in the schematic but unconnected on a single pin shows as unconnected
        errors += compare("schematic", expected, sch)
    else:
        errors.append("schematic netlist %s not found" % net_file)
    data = circuit.to_json(parts, {"design": "Lira", "matrix": iface["matrix"], "gpio": iface["gpio"],
                                   "deviations_from_bluemicro840": circuit.DEVIATIONS})
    (BUILD / "netlist.json").write_text(json.dumps(data, indent=1))
    for e in errors:
        print(e)
    n_pins = sum(1 for v in expected.values() if v)
    print("%d parts, %d connected pins, %d nets — %s" % (
        len(parts), n_pins, len(data["nets"]), "PCB and schematic match the circuit" if not errors
        else "%d DIFFERENCES" % len(errors)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
