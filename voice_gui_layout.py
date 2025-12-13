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
    by the GUI class. The issue buckets occupy the full top row, control
    settings sit beneath them, the level/live-output span follows, and the
    waterfall/transcript/log flow keeps their placement consistent with the mock.
    """

    pad = DEFAULT_PAD
    controls_frame = gui.controls_frame
    controls_frame.pack(fill=BOTH, expand=True)
    controls_frame.columnconfigure(0, weight=1)
    controls_frame.rowconfigure(1, weight=2)
    controls_frame.rowconfigure(2, weight=1)
    controls_frame.rowconfigure(3, weight=1)
    controls_frame.rowconfigure(4, weight=0)
    controls_frame.rowconfigure(5, weight=2)
    controls_frame.rowconfigure(6, weight=0)

    header = ttk.Frame(controls_frame)
    header.grid(row=0, column=0, sticky="ew", padx=pad["padx"], pady=pad["pady"])
    gui._build_header(header)

    issues_section = ttk.Frame(controls_frame)
    issues_section.grid(row=1, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    issues_section.columnconfigure(0, weight=1)
    gui._build_issues_panel(issues_section)

    settings_section = ttk.Frame(controls_frame)
    settings_section.grid(row=2, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    settings_section.columnconfigure(0, weight=1)
    gui._build_settings_panel(settings_section, pad)

    live_section = ttk.Frame(controls_frame)
    live_section.grid(row=3, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    live_section.columnconfigure(0, weight=1)
    live_section.columnconfigure(1, weight=2)
    gui._build_live_panel(live_section, pad)

    action_section = ttk.Frame(controls_frame)
    action_section.grid(row=4, column=0, sticky="ew", padx=pad["padx"], pady=(0, pad["pady"]))
    action_section.columnconfigure(0, weight=1)
    gui._build_action_buttons(action_section, pad)
    gui._build_status_label(action_section, pad)

    audio_section = ttk.Frame(controls_frame)
    audio_section.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 6))
    audio_section.columnconfigure(0, weight=1)
    gui._build_audio_panel(audio_section, pad)

    transcript_section = ttk.Frame(controls_frame)
    transcript_section.grid(row=6, column=0, sticky="ew", padx=10, pady=(0, 6))
    gui._build_transcript_panel(transcript_section)

    gui._build_log_block(gui.root)
