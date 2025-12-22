#!/usr/bin/env python3
"""
Entry point for the GUI voice recorder.

Usage:
  python voice_gui.py
"""

import sys
from pathlib import Path

# Ensure repo root is importable regardless of CWD
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_gui_app import main


if __name__ == "__main__":
    raise SystemExit(main())
