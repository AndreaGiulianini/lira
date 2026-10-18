"""Paths for the Lira USB generator (a minimal stand-in for ../lira/source/paths.py)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
BUILD.mkdir(parents=True, exist_ok=True)
