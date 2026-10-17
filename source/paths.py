"""Where the files go: the working files in source/build/, the finished files to use (order, print, flash) published by
publish.py into ../production/."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # source/
BUILD = ROOT / "build"  # working files
PUBLISH = ROOT.parent / "production"  # what the user takes to JLCPCB, to the printer, to the keyboard
