"""Shared style tokens for the Voice Issue Recorder UI."""

from __future__ import annotations

DEFAULT_PAD = {"padx": 8, "pady": 4}

WINDOW = {
    "title": "Voice Issue Recorder",
    "geometry": "1340x800",
    "min_width": 1120,
    "min_height": 760,
}

FONTS = {
    "header": ("Segoe UI", 12, "bold"),
}

LISTBOX_HEIGHT = 16
LOG_HEIGHT = 8
LIVE_TRANSCRIPT_HEIGHT = 5

LIVE_INDICATOR = {
    "text": "Idle",
    "foreground": "white",
    "background": "#666666",
    "padding": 6,
}

WATERFALL = {
    "height": 280,
    "background": "#1e1e1e",
    "highlightthickness": 0,
}

ISSUE_PANEL_PADDING = (8, 0, 0, 0)
LIVE_OUTPUT_PADDING = (6, 4, 6, 4)
INFO_ROW_PADDING = (6, 2, 6, 2)
DEVICE_ROW_PADDING = (2, 1, 2, 1)
