"""Builds firmware/rmk-patched/: RMK 0.9.0 with two changes this board needs (the RMK project uses it through
[patch.crates-io] in rmk/Cargo.toml; `make firmware` runs this first).

    python3 firmware/patch_rmk.py

1. Matrix: after a column is driven low again, wait (up to 50 us) until every row reads low before the next column
   is driven. RMK reads a column 1 us after driving it and goes straight on to the next one; on the RP2040 a row is
   held low only by the internal pull-down (50-80 kOhm, RP2040 datasheet) and the rows of this board are 400-480 mm
   long (~45 pF), so a row lifted by a key takes 2.5-5 us to fall: without the wait, a held key could also show up in
   the next column. (On the nRF52840 the timer tick is 30.5 us and the pull-down 13 kOhm, so there it cannot happen.)
2. USB: ask for 100 mA instead of RMK's fixed 450 mA. The RP2040 with its flash and LED draws about 40 mA; the rest of
   the board (hub, sound card) declares its own power.

The crate comes from Cargo's cache, or from crates.io; either way its SHA-256 must be the one in Cargo.lock's history
(the published 0.9.0), and every change must apply exactly once, or nothing is built.
"""
import hashlib
import io
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "rmk-patched"
CRATE = "rmk-0.9.0"
SHA256 = "b6e673c9d3f508dfed96a3eba93de67b7b5ad3de8b48068fdeb73334b4de06ec"
URL = "https://static.crates.io/crates/rmk/%s.crate" % CRATE
STAMP = OUT / ".lira-patch"
VERSION = "1"  # bump when the changes below change

CHANGES = [
    ("src/matrix.rs",
     """                // Pull it back to low
                if let Some(out_pin) = self.get_output_pins_mut().get_mut(out_idx) {
                    out_pin.set_low().ok();
                }
            }
""",
     """                // Pull it back to low
                if let Some(out_pin) = self.get_output_pins_mut().get_mut(out_idx) {
                    out_pin.set_low().ok();
                }
                // Lira: let the rows fall (weak pull-downs, long rows) before the next column is driven
                for _ in 0..50 {
                    if !self.get_input_pins_mut().iter_mut().any(|p| p.is_high().ok().unwrap_or_default()) {
                        break;
                    }
                    Timer::after_micros(1).await;
                }
            }
"""),
    ("src/usb/mod.rs",
     "    usb_config.max_power = 450;\n",
     "    usb_config.max_power = 100; // Lira: the RP2040 board draws ~40 mA (the hub and sound card declare their own)\n"),
]


def crate_bytes():
    cached = sorted(Path.home().glob(".cargo/registry/cache/*/%s.crate" % CRATE))
    data = cached[0].read_bytes() if cached else urllib.request.urlopen(URL, timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != SHA256:
        raise SystemExit("%s: SHA-256 %s, expected %s" % (CRATE, digest, SHA256))
    return data


def main():
    if STAMP.exists() and STAMP.read_text() == VERSION:
        return
    if OUT.exists():
        shutil.rmtree(OUT)
    tmp = HERE / (OUT.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    with tarfile.open(fileobj=io.BytesIO(crate_bytes()), mode="r:gz") as tar:
        tar.extractall(tmp)
    src = tmp / CRATE
    for rel, old, new in CHANGES:
        p = src / rel
        text = p.read_text()
        if text.count(old) != 1:
            raise SystemExit("%s: the text to change is not there exactly once (RMK changed?)" % rel)
        p.write_text(text.replace(old, new))
    src.rename(OUT)
    shutil.rmtree(tmp)
    STAMP.write_text(VERSION)
    print("wrote %s: %s with %d changes" % (OUT.relative_to(HERE.parent), CRATE, len(CHANGES)))


if __name__ == "__main__":
    sys.exit(main())
