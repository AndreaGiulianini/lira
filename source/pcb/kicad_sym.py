"""Read symbols from KiCad's .kicad_sym libraries (to embed them in a generated schematic) and list their pins.

    python3 pcb/kicad_sym.py Device:R Regulator_Linear:AP2112K-3.3     -> prints the pins of each symbol
"""
import re
import sys
from pathlib import Path

KICAD = next(p for p in Path.home().glob("Applications/KiCad/KiCad.app/Contents"))
SYMBOLS = KICAD / "SharedSupport" / "symbols"


def tokenize(s):
    return re.findall(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+', s)


def parse(tokens):
    """s-expression -> nested lists (strings keep their quotes stripped)."""
    stack = [[]]
    for t in tokens:
        if t == "(":
            stack.append([])
        elif t == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(t[1:-1] if t.startswith('"') else t)
    return stack[0]


def symbol_text(lib, name):
    """The raw `(symbol "name" ...)` block of a library symbol, balanced parentheses included."""
    text = (SYMBOLS / (lib + ".kicad_sym")).read_text(encoding="utf-8")
    i = text.index('(symbol "%s"' % name)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
    raise ValueError(name)


def resolve_extends(lib, name, block):
    """Symbols that `extends` another one are flattened: KiCad needs the parent's drawing in lib_symbols too."""
    m = re.search(r'\(extends "([^"]+)"\)', block)
    if not m:
        return block, None
    parent = symbol_text(lib, m.group(1))
    return block, parent


def pins(block):
    """[(number, name, type, x, y, angle)] of a symbol block, units merged."""
    tree = parse(tokenize(block))[0]
    out = []

    def walk(node):
        for n in node:
            if isinstance(n, list):
                if n and n[0] == "pin":
                    ptype = n[1]
                    at = next(x for x in n if isinstance(x, list) and x[0] == "at")
                    name = next(x for x in n if isinstance(x, list) and x[0] == "name")[1]
                    num = next(x for x in n if isinstance(x, list) and x[0] == "number")[1]
                    out.append((num, name, ptype, float(at[1]), float(at[2]), float(at[3]) if len(at) > 3 else 0.0))
                else:
                    walk(n)
    walk(tree)
    return out


if __name__ == "__main__":
    for spec in sys.argv[1:]:
        lib, name = spec.split(":")
        block, parent = resolve_extends(lib, name, symbol_text(lib, name))
        print("==", spec, "(extends)" if parent else "")
        for p in pins(parent if parent else block):
            print("   %-4s %-10s %-12s at %6.2f %6.2f rot %g" % p)
