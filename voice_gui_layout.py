#!/usr/bin/env python3
"""
GUI layout helper for Voice Issue Recorder.

This module owns the top-level arrangement so edits to the visual structure can
be made in a single place without touching the behavior in voice_gui_app.py.
"""

from __future__ import annotations

from tkinter import BOTH, LEFT
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from voice_gui_app import VoiceGUI


DEFAULT_PAD = {"padx": 8, "pady": 4}


def build_layout_structure(gui: "VoiceGUI") -> None:
    """
    Compose the Voice Issue Recorder layout using the component builders exposed
    by the GUI class. The left column hosts configuration controls, the right
    column shows the issue buckets, and the microphone waterfall spans the full
    width of the window beneath those controls.
    """

    pad = DEFAULT_PAD
    controls_frame = gui.controls_frame
    controls_frame.pack(fill=BOTH, expand=True)
    controls_frame.columnconfigure(0, weight=3)
    controls_frame.columnconfigure(1, weight=2)
    controls_frame.rowconfigure(1, weight=1)
    controls_frame.rowconfigure(2, weight=2)

    header = ttk.Frame(controls_frame)
    header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=pad["padx"], pady=pad["pady"])
    gui._build_header(header)

    body = ttk.Frame(controls_frame)
    body.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    body.columnconfigure(0, weight=3)
    body.columnconfigure(1, weight=2)

    left_column = ttk.Frame(body)
    left_column.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

    right_column = ttk.Frame(body, width=420)
    right_column.grid(row=0, column=1, sticky="ns")

    gui._build_settings_panel(left_column, pad)
    gui._build_action_buttons(left_column, pad)
    gui._build_status_label(left_column, pad)

    gui._build_issues_panel(right_column)

    audio_section = ttk.Frame(controls_frame)
    audio_section.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 6))
    audio_section.columnconfigure(0, weight=1)
    gui._build_audio_panel(audio_section, pad)

    transcript_section = ttk.Frame(controls_frame)
    transcript_section.grid(row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
    gui._build_transcript_panel(transcript_section)

    gui._build_log_block(gui.root)
