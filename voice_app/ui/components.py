"""UI component builders for the Voice Issue Recorder."""

from __future__ import annotations

from tkinter import BOTH, LEFT, RIGHT, DISABLED, Canvas, Listbox, Tk
from tkinter import scrolledtext, ttk
from typing import TYPE_CHECKING

from . import styles

if TYPE_CHECKING:  # pragma: no cover
    from ..app import VoiceApp


class VoiceUIComponents:
    def __init__(self, app: "VoiceApp") -> None:
        self.app = app

    def build_header(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Voice Issue Recorder", font=styles.FONTS["header"]).pack(anchor="w")

    def build_status_label(self, parent: ttk.Frame) -> None:
        self.app.status_var = ttk.Label(parent, text="Ready")
        self.app.status_var.pack(anchor="w", **styles.DEFAULT_PAD)

    def build_log_block(self, parent: Tk) -> None:
        log_frame = ttk.Frame(parent)
        log_frame.pack(fill=BOTH, expand=False, padx=10, pady=(0, 10))
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.app.log_widget = scrolledtext.ScrolledText(log_frame, height=styles.LOG_HEIGHT, state=DISABLED)
        self.app.log_widget.pack(fill=BOTH, expand=False, pady=(2, 0))
        self.app._log("Ready. Select mic, use 'Test Selected Mic' to monitor, then Start Recording.")
        self.app._flush_bootstrap_logs()

    def build_issues_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, padding=styles.ISSUE_PANEL_PADDING)
        panel.pack(fill=BOTH, expand=True)
        self._build_move_buttons(panel)

        lists_row = ttk.Frame(panel)
        lists_row.pack(fill=BOTH, expand=True)

        self._build_issue_column(lists_row, "Pending issues:", "pending")
        self._build_issue_column(lists_row, "Completed issues:", "done")
        self._build_issue_column(lists_row, "Waitlist issues:", "wait")

    def _build_move_buttons(self, parent: ttk.Frame) -> None:
        move_all_row = ttk.Frame(parent)
        move_all_row.pack(fill=BOTH, expand=False, pady=(0, 4))
        ttk.Label(move_all_row, text="Move selected to:").pack(side=LEFT, padx=(0, 6))
        ttk.Button(move_all_row, text="Pending", command=self.app._mark_any_pending).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Completed", command=self.app._mark_any_completed).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Waitlist", command=self.app._mark_any_waitlist).pack(side=LEFT, padx=(0, 4))
        ttk.Checkbutton(
            move_all_row,
            text="Skip delete confirmation",
            variable=self.app.skip_delete_confirm,
        ).pack(side=LEFT, padx=(4, 0))

    def _build_issue_column(self, parent: ttk.Frame, label: str, bucket: str) -> None:
        column = ttk.Frame(parent, padding=(4, 0, 0, 0))
        column.pack(side=LEFT, fill=BOTH, expand=True)
        column.columnconfigure(0, weight=1)
        column.rowconfigure(1, weight=1)
        base_label = f"{label.strip(':')}:"
        header = ttk.Label(column, text=f"{base_label} [0]")
        header.grid(row=0, column=0, sticky="w")
        listbox = Listbox(
            column,
            height=styles.LISTBOX_HEIGHT,
            selectmode="extended",
            exportselection=False,
        )
        listbox.grid(row=1, column=0, sticky="nsew", pady=(2, 4))
        if bucket == "pending":
            self.app.issue_listbox = listbox
            listbox.bind("<<ListboxSelect>>", self.app._on_pending_select)
        elif bucket == "done":
            self.app.issue_listbox_done = listbox
            listbox.bind("<<ListboxSelect>>", self.app._on_done_select)
        else:
            self.app.issue_listbox_wait = listbox
            listbox.bind("<<ListboxSelect>>", lambda e: self.app._on_wait_select())
        self.app.issue_header_labels[bucket] = (header, base_label)
        listbox.bind("<ButtonPress-1>", lambda e, b=bucket: self.app._start_drag(e, b))
        listbox.bind("<ButtonRelease-1>", lambda e, b=bucket: self.app._finish_drag(e, b))
        listbox.bind("<Double-Button-1>", lambda e, b=bucket: self.app._on_issue_double_click(e, b))

        btn_row = ttk.Frame(column)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        if bucket == "pending":
            ttk.Button(btn_row, text="Select all", command=self.app._select_all_pending).pack(side=LEFT, padx=(0, 4))
            ttk.Button(btn_row, text="Delete selected", command=self.app._delete_selected_pending).pack(side=LEFT)
            move_row = ttk.Frame(column)
            move_row.grid(row=3, column=0, sticky="ew", pady=(0, 2))
            ttk.Button(move_row, text="Move up", command=lambda: self.app._move_pending_selection(-1)).pack(
                side=LEFT, padx=(0, 4)
            )
            ttk.Button(move_row, text="Move down", command=lambda: self.app._move_pending_selection(1)).pack(side=LEFT)
        elif bucket == "done":
            ttk.Button(btn_row, text="Select all", command=self.app._select_all_done).pack(side=LEFT, padx=(0, 4))
            ttk.Button(btn_row, text="Delete selected", command=self.app._delete_selected_done).pack(side=LEFT)
        else:
            ttk.Button(btn_row, text="Select all", command=lambda: self.app._select_all_list(self.app.issue_listbox_wait)).pack(
                side=LEFT, padx=(0, 4)
            )
            ttk.Button(btn_row, text="Delete selected", command=self.app._delete_selected_wait).pack(side=LEFT)

    def build_settings_panel(self, parent: ttk.Frame) -> None:
        self.app.test_cta_btn = ttk.Button(parent, text="Test Selected Mic", command=self.app.toggle_mic_test)
        self.app.test_cta_btn.pack(fill=BOTH, padx=10, pady=(4, 4))

        columns = ttk.Frame(parent)
        columns.pack(fill=BOTH, expand=True, **styles.DEFAULT_PAD)
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)

        left_col = ttk.Frame(columns)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right_col = ttk.Frame(columns)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right_col.columnconfigure(0, weight=1)

        self._build_hotkey_row(left_col)
        self._build_repo_rows(left_col)
        self._build_issue_rows(left_col)
        self._build_device_row(left_col)

        self.app.hotkey_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.app.hotkey_info_label.pack(fill="x", padx=(6, 4), pady=(2, 1))
        self.app.repo_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.app.repo_info_label.pack(fill="x", padx=(6, 4), pady=(0, 1))
        self.app.issues_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.app.issues_info_label.pack(fill="x", padx=(6, 4), pady=(0, 1))
        self.app._refresh_static_info()

    def _build_hotkey_row(self, parent: ttk.Frame) -> None:
        hk_row = ttk.Frame(parent, padding=styles.INFO_ROW_PADDING)
        hk_row.pack(fill=BOTH, **styles.DEFAULT_PAD)
        ttk.Label(hk_row, text="Hotkey toggle:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.app.hotkey_toggle_var, width=16).pack(side=LEFT, padx=(0, 10))
        ttk.Label(hk_row, text="Hotkey quit:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.app.hotkey_quit_var, width=16).pack(side=LEFT, padx=(0, 10))

    def _build_repo_rows(self, parent: ttk.Frame) -> None:
        path_row = ttk.Frame(parent, padding=styles.INFO_ROW_PADDING)
        path_row.pack(fill=BOTH, **styles.DEFAULT_PAD)
        ttk.Label(path_row, text="Repo path:").pack(side=LEFT, padx=(0, 6))
        repo_values = list(self.app.repo_history)
        current_repo = str(self.app.repo_cfg.repo_path)
        if repo_values and repo_values[0] == current_repo:
            combo_values = repo_values
        else:
            combo_values = [current_repo] + [v for v in repo_values if v != current_repo]
        self.app.repo_combo = ttk.Combobox(
            path_row,
            textvariable=self.app.repo_path_var,
            values=combo_values,
            state="normal",
            width=70,
        )
        self.app.repo_combo.pack(side=LEFT, padx=(0, 10))
        ttk.Button(path_row, text="Browse...", width=8, command=self.app._browse_repo_path).pack(side=LEFT, padx=(0, 6))
        self.app._update_repo_combo_values(current_repo=self.app.repo_cfg.repo_path)

    def _build_issue_rows(self, parent: ttk.Frame) -> None:
        issue_path_row = ttk.Frame(parent, padding=styles.INFO_ROW_PADDING)
        issue_path_row.pack(fill=BOTH, **styles.DEFAULT_PAD)
        ttk.Label(issue_path_row, text="Issues file:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(issue_path_row, textvariable=self.app.issues_path_var, width=70).pack(side=LEFT, padx=(0, 10))
        ttk.Button(
            issue_path_row,
            text="Create voice file",
            width=16,
            command=self.app._create_voice_file_for_selected_repo,
        ).pack(side=LEFT, padx=(0, 6))

        apply_btn = ttk.Button(parent, text="Apply settings", command=self.app._apply_settings, width=18)
        apply_btn.pack(anchor="w", padx=10, pady=(0, 6))

    def _build_device_row(self, parent: ttk.Frame) -> None:
        device_row = ttk.Frame(parent, padding=styles.DEVICE_ROW_PADDING)
        device_row.pack(fill="x", expand=False, padx=8, pady=(0, 4))
        device_row.columnconfigure(0, weight=0)
        device_row.columnconfigure(1, weight=4)
        device_row.columnconfigure(2, weight=1)
        ttk.Label(device_row, text="Input device:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        values = [f"{d['id']}: {d['name']}" for d in self.app.device_list]
        self.app.device_combo = ttk.Combobox(
            device_row,
            values=values,
            state="readonly",
            width=32,
        )
        self.app.device_combo.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        if self.app.device_list:
            self.app.device_combo.current(0)
            self.app.device_combo.bind("<<ComboboxSelected>>", self.app.on_device_change)
        ttk.Button(device_row, text="Refresh", command=self.app.refresh_devices).grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.app.live_indicator = ttk.Label(device_row, **styles.LIVE_INDICATOR)
        self.app.live_indicator.grid(row=0, column=3, sticky="e", padx=(0, 0))

    def build_live_panel(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        live_output_frame = ttk.Frame(parent, padding=styles.LIVE_OUTPUT_PADDING)
        live_output_frame.grid(row=0, column=0, sticky="nsew")
        live_output_frame.columnconfigure(0, weight=1)
        ttk.Label(live_output_frame, text="Live speech output:").pack(anchor="w")
        self.app.live_transcript_widget = scrolledtext.ScrolledText(
            live_output_frame, height=styles.LIVE_TRANSCRIPT_HEIGHT, state=DISABLED
        )
        self.app.live_transcript_widget.pack(fill=BOTH, expand=True, pady=(2, 0))

    def build_audio_panel(self, parent: ttk.Frame) -> None:
        wf_header = ttk.Frame(parent)
        wf_header.pack(fill=BOTH, padx=10, pady=(4, 0))
        ttk.Label(wf_header, text="Microphone waterfall").pack(side=LEFT)
        self.app.waterfall_status = ttk.Label(wf_header, text="Waterfall: idle")
        self.app.waterfall_status.pack(side=LEFT, padx=(8, 0))
        self.app.test_canvas = Canvas(
            parent,
            height=styles.WATERFALL["height"],
            bg=styles.WATERFALL["background"],
            highlightthickness=styles.WATERFALL["highlightthickness"],
        )
        self.app.test_canvas.pack(fill=BOTH, expand=True, padx=10, pady=(0, 5))

    def build_action_buttons(self, parent: ttk.Frame) -> None:
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=BOTH, **styles.DEFAULT_PAD)
        self.app.start_btn = ttk.Button(btn_row, text="Start Recording", command=self.app.start_recording)
        self.app.start_btn.pack(side=LEFT, expand=True, fill=BOTH, padx=(0, 5))
        self.app.stop_btn = ttk.Button(btn_row, text="Stop & Transcribe", command=self.app.stop_recording, state=DISABLED)
        self.app.stop_btn.pack(side=RIGHT, expand=True, fill=BOTH, padx=(5, 0))


__all__ = ["VoiceUIComponents"]
