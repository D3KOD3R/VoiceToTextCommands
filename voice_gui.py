#!/usr/bin/env python3
"""
Entry point for the GUI voice recorder.

Usage:
  python voice_gui.py
"""

import atexit
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Ensure repo root is importable regardless of CWD
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_gui_app import main


LOG_DIR = ROOT / ".tmp"
STARTUP_LOG = LOG_DIR / "voice_gui_startup.log"
CRASH_LOG = LOG_DIR / "voice_gui_crash.log"


def _write_log(path: Path, message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path.write_text(f"{stamp} {message}\n", encoding="utf-8", errors="ignore")
    except Exception:
        pass


def _append_log(path: Path, message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8", errors="ignore") as handle:
            handle.write(f"{stamp} {message}\n")
    except Exception:
        pass


if __name__ == "__main__":
    _write_log(
        STARTUP_LOG,
        f"start exe={sys.executable} argv={sys.argv} cwd={Path.cwd()}",
    )

    def _on_exit() -> None:
        _append_log(STARTUP_LOG, "exit")

    atexit.register(_on_exit)
    try:
        raise SystemExit(main())
    except Exception:
        _append_log(CRASH_LOG, traceback.format_exc().strip())
        raise
