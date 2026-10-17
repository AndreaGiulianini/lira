"""Make the generated files reproducible: pin every build timestamp to a fixed instant.

The exporters used here (KiCad's ERC/DRC/plot/gerber writers, OpenCASCADE's STEP writer, zip) stamp the
current wall clock into their output, so building the same sources twice produces different bytes. This
step rewrites the known timestamp fields to NEUTRAL_DATE at 00:00:00, so a rebuild is byte-identical:

  * ISO 8601 date-times       YYYY-MM-DDTHH:MM:SS / YYYY-MM-DD HH:MM:SS   (ERC, gerbers, STEP, SVG)
  * PDF /CreationDate         D:YYYY:MM:DD:HH:MM:SS
  * EXIF date                 YYYY:MM:DD HH:MM:SS
  * KiCad title-block date    (date "YYYY-MM-DD")

Zip entries get a fixed entry time as well. Every replacement keeps the original length, so PDF
cross-reference tables and binary layouts stay valid.

    python3 sanitize.py [--mtime] [root ...]      # default roots: build ../production
"""

import io
import os
import re
import sys
import time
import zipfile
from pathlib import Path

DATE = os.environ.get("NEUTRAL_DATE", "2026-10-15")  # YYYY-MM-DD; the pinned build instant is DATE 00:00:00
Y, M, D = (int(x) for x in DATE.split("-"))
ISO = DATE.encode()
PDF = ("D:%04d:%02d:%02d:00:00:00" % (Y, M, D)).encode()
EXIF = ("%04d:%02d:%02d 00:00:00" % (Y, M, D)).encode()
KDATE = ('(date "%s")' % DATE).encode()

# same-length substitutions: (pattern, replacement)
SUBS = [
    (re.compile(rb"D:\d{4}:\d{2}:\d{2}:\d{2}:\d{2}:\d{2}"), PDF),
    (re.compile(rb"\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}"), EXIF),
    (re.compile(rb"\d{4}-\d{2}-\d{2}(?=[T ]\d{2}:\d{2}:\d{2})"), ISO),
    (re.compile(rb"(?<=\d{4}-\d{2}-\d{2}[T ])\d{2}:\d{2}:\d{2}"), b"00:00:00"),
    (re.compile(rb'\(date "\d{4}-\d{2}-\d{2}"\)'), KDATE),
    (re.compile(rb'Date: \d{4}-\d{2}-\d{2}'), b"Date: " + ISO),  # KiCad title-block date in plotted SVG/PDF
]
HAS_TIME = re.compile(rb"\d{2}:\d{2}:\d{2}")
SKIP = ("/.git/", "/.venv/", "/target/", "/__pycache__/")
# only these can carry a timestamp field; skipping the rest keeps the walk over build/ fast
EXTS = {".txt", ".rpt", ".svg", ".step", ".stp", ".pdf", ".zip", ".gbr", ".gtl", ".gbl", ".gts", ".gbs",
        ".gto", ".gbo", ".gtp", ".gbp", ".gm1", ".drl", ".gbrjob", ".dsn", ".ses", ".json", ".csv",
        ".toml", ".md", ".net", ".xml", ".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_prl", ".dxf"}


def scrub(data):
    out = data
    for rx, rep in SUBS:
        out = rx.sub(rep, out)
    return out


def process(path, set_mtime):
    if path.suffix.lower() not in EXTS:
        return False
    data = path.read_bytes()
    # a zip's timestamps are inside the (compressed) entries, so never pre-filter zips
    if path.suffix.lower() != ".zip" and not (HAS_TIME.search(data) or b'(date "' in data or b"Date: " in data):
        return False
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as zin:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    info.date_time = (Y, M, D, 0, 0, 0)
                    info.extra = b""  # drop the NTFS/UT extended timestamps, which would leak the real hour
                    zout.writestr(info, scrub(zin.read(info.filename)))
            new = buf.getvalue()
    else:
        new = scrub(data)
    if new != data:
        path.write_bytes(new)
        if set_mtime:
            os.utime(path, (mtime, mtime))
        return True
    return False


def main(argv):
    set_mtime = "--mtime" in argv
    roots = [a for a in argv if a != "--mtime"] or ["build", "../production"]
    changed = 0
    for root in roots:
        for dp, _, fns in os.walk(root):
            if any(s in dp + "/" for s in SKIP):
                continue
            for fn in fns:
                p = Path(dp) / fn
                try:
                    changed += process(p, set_mtime)
                except (OSError, zipfile.BadZipFile):
                    pass
    print("sanitize: %d file(s) rewritten to %s 00:00:00" % (changed, DATE))


if __name__ == "__main__":
    mtime = time.mktime((Y, M, D, 0, 0, 0, 0, 0, -1))
    main(sys.argv[1:])
