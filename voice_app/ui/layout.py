"""Layout composition for the Voice Issue Recorder UI."""

from __future__ import annotations

from tkinter import BOTH
from tkinter import ttk
from typing import TYPE_CHECKING

from . import styles

if TYPE_CHECKING:  # pragma: no cover
    from ..app import VoiceApp


def build_layout_structure(app: "VoiceApp") -> None:
    pad = styles.DEFAULT_PAD
    controls_frame = app.controls_frame
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
    app.ui.build_header(header)

    issues_section = ttk.Frame(controls_frame)
    issues_section.grid(row=1, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    issues_section.columnconfigure(0, weight=1)
    app.ui.build_issues_panel(issues_section)

    settings_section = ttk.Frame(controls_frame)
    settings_section.grid(row=2, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    settings_section.columnconfigure(0, weight=1)
    app.ui.build_settings_panel(settings_section)

    live_section = ttk.Frame(controls_frame)
    live_section.grid(row=3, column=0, sticky="nsew", padx=pad["padx"], pady=(0, pad["pady"]))
    live_section.columnconfigure(0, weight=1)
    live_section.columnconfigure(1, weight=2)
    app.ui.build_live_panel(live_section)

    action_section = ttk.Frame(controls_frame)
    action_section.grid(row=4, column=0, sticky="ew", padx=pad["padx"], pady=(0, pad["pady"]))
    action_section.columnconfigure(0, weight=1)
    app.ui.build_action_buttons(action_section)
    app.ui.build_status_label(action_section)

    audio_section = ttk.Frame(controls_frame)
    audio_section.grid(row=5, column=0, sticky="nsew", padx=10, pady=(0, 6))
    audio_section.columnconfigure(0, weight=1)
    app.ui.build_audio_panel(audio_section)

    app.ui.build_log_block(app.root)


__all__ = ["build_layout_structure"]
