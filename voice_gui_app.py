#!/usr/bin/env python3
"""
Simple desktop GUI to record via microphone, transcribe with whisper.cpp, and append
issues to the configured Markdown file.

Features:
- Select input device
- Start/stop recording with buttons
- Live input level meter while recording
- Transcribe with whisper.cpp using paths from .voice_config.json (repo-local)
- Append each detected issue immediately to .voice/voice-issues.md

Run:
  python voice_gui.py
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import textwrap
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
import subprocess
from pathlib import Path
from typing import Iterable
from tkinter import BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, Canvas, Listbox, StringVar, BooleanVar, Tk, Toplevel, messagebox, ttk, filedialog
from tkinter import scrolledtext

import numpy as np
import sounddevice as sd

try:
    import keyboard  # type: ignore
except Exception:  # noqa: BLE001
    keyboard = None

# Ensure repo root is importable regardless of CWD
ROOT = Path(__file__).resolve().parent
REPO_HISTORY_PATH = ROOT / ".voice" / "repo_history.json"
AGENT_VOICE_SOURCE = ROOT / "agents" / "AgentVoice.md"
VOICE_WORKFLOW_SOURCE = ROOT / "VOICE_ISSUE_WORKFLOW.md"
REPO_HISTORY_LIMIT = 12
PAST_REPOS_MD = ROOT / ".voice" / "past_repos.md"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_issue_daemon import (
    ConfigLoader,
    DEFAULT_CONFIG_PATH,
    IssueWriter,
    RepoConfig,
    WhisperCppProvider,
    append_issues_incremental,
    split_issues,
)
from voice_gui_layout import build_layout_structure


NOISY_NAMES = re.compile(r"(hands[- ]?free|hf audio|bthhfenum|telephony|communications|loopback|primary sound capture)", re.I)
WATERFALL_WINDOW = 50  # number of samples to display (~5s at 10 Hz poll)
WAIT_STATE_CHAR = "~"

LIGHT_THEME = {
    "root_bg": "#f3f5fb",
    "panel_bg": "#ffffff",
    "element_bg": "#eef2fa",
    "entry_bg": "#ffffff",
    "list_bg": "#ffffff",
    "canvas_bg": "#041a2d",
    "fg": "#111828",
    "accent": "#2274a5",
    "select_bg": "#2274a5",
    "select_fg": "#ffffff",
    "border": "#d0d7e6",
}

DARK_THEME = {
    "root_bg": "#080b10",
    "panel_bg": "#101828",
    "element_bg": "#1f2634",
    "entry_bg": "#1e2431",
    "list_bg": "#111827",
    "canvas_bg": "#03060f",
    "fg": "#f4f7fb",
    "accent": "#4caf50",
    "select_bg": "#33a7c5",
    "select_fg": "#ffffff",
    "border": "#2b3241",
}


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def hostapi_priority(idx: int | None, hostapis: list[dict] | None = None) -> int:
    hostapis = hostapis or sd.query_hostapis()
    if idx is None or idx >= len(hostapis):
        return 99
    name = hostapis[idx].get("name", "").lower()
    if "wasapi" in name:
        return 0
    if "mme" in name:
        return 1
    if "directsound" in name:
        return 2
    return 3


def apply_device_filters(devices: list[dict], allow: list[str] | None, deny: list[str] | None) -> list[dict]:
    if allow:
        allow_set = {a.lower() for a in allow}
        devices = [d for d in devices if d["name"].lower() in allow_set]
    if deny:
        deny_set = {d.lower() for d in deny}
        devices = [d for d in devices if d["name"].lower() not in deny_set]
    return devices


def list_input_devices(allow: list[str] | None = None, deny: list[str] | None = None) -> list[dict]:
    hostapis = sd.query_hostapis()
    devices = sd.query_devices()

    # Deduplicate by normalized name; keep the best hostapi according to priority.
    best: dict[str, dict] = {}
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        if NOISY_NAMES.search(name):
            continue
        priority = hostapi_priority(dev.get("hostapi"), hostapis)
        # Ignore lower-priority host APIs (e.g., WDM-KS) to reduce noise unless explicitly allowed
        if priority >= 3:
            continue
        norm = normalize_name(name)
        cand = {
            "id": idx,
            "name": name,
            "max_input_channels": dev.get("max_input_channels", 0),
            "hostapi": dev.get("hostapi"),
            "hostapi_priority": priority,
        }
        # If we already have a similar name, keep the higher-priority host API
        existing_key = None
        for k in best:
            if norm in k or k in norm:
                existing_key = k
                break
        if existing_key:
            existing = best[existing_key]
            if cand["hostapi_priority"] < existing["hostapi_priority"]:
                best[existing_key] = cand
        else:
            best[norm] = cand

    filtered = list(best.values())
    filtered.sort(key=lambda d: (d["hostapi_priority"], d["name"].lower()))
    return apply_device_filters(filtered, allow, deny)


def get_device_samplerate(device_id: int | None, fallback: int = 16000) -> int:
    if device_id is None:
        return fallback
    try:
        dev = sd.query_devices(device_id)
        sr = dev.get("default_samplerate")
        if sr and sr > 0:
            return int(sr)
    except Exception:
        pass
    return fallback


def get_device_channels(device_id: int | None, fallback: int = 1) -> int:
    if device_id is None:
        return fallback
    try:
        dev = sd.query_devices(device_id)
        ch = dev.get("max_input_channels", fallback)
        if ch and ch > 0:
            return int(ch)
    except Exception:
        pass
    return fallback


def find_working_samplerates(device_id: int | None) -> tuple[list[int], list[str]]:
    """
    Try a set of candidate sample rates and return those that pass check_input_settings.
    Collect warnings for diagnostics.
    """
    logs: list[str] = []
    default_sr = get_device_samplerate(device_id, fallback=44100)
    candidates = [default_sr, 48000, 44100, 32000, 22050, 16000, 96000]
    seen = set()
    ok: list[int] = []
    for sr in candidates:
        sr = int(sr)
        if sr <= 0 or sr in seen:
            continue
        seen.add(sr)
        try:
            sd.check_input_settings(device=device_id, samplerate=sr, dtype="int16", channels=1)
            ok.append(sr)
        except Exception as exc:  # noqa: BLE001
            logs.append(f"check failed {sr} Hz: {exc}")
    return ok, logs


def validate_recording(path: Path, max_age_seconds: int = 180) -> float:
    """
    Ensure the recorded WAV is present, recent, and has non-zero duration.
    Returns duration in seconds.
    """
    if not path.exists():
        raise RuntimeError(f"Recording missing at {path}")
    stat = path.stat()
    age = time.time() - stat.st_mtime
    if age > max_age_seconds:
        raise RuntimeError(f"Recording at {path} is stale (age {age:.1f}s)")
    if stat.st_size <= 44:  # smaller than WAV header implies empty
        raise RuntimeError(f"Recording at {path} is empty (size {stat.st_size} bytes)")
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        fr = wf.getframerate() or 1
        duration = frames / float(fr)
    if duration <= 0.05:
        raise RuntimeError(f"Recording at {path} has near-zero duration ({duration:.3f}s)")
    return duration


def hotkey_conflicts(combo: str) -> bool:
    bad = ["ctrl+alt+del", "alt+tab", "win+l", "win+d", "win+tab", "alt+f4"]
    lc = combo.lower().replace(" ", "")
    return any(b in lc for b in bad)


class Recorder:
    def __init__(self, samplerate: int = 16000, channels: int = 1, device: int | None = None):
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.stream = None
        self.wav_file = None
        self._level = 0.0
        self._lock = threading.Lock()

    @property
    def level(self) -> float:
        with self._lock:
            return self._level

    def start(self, output_path: Path, extra_settings=None) -> None:
        if self.stream:
            return
        self.wav_file = wave.open(str(output_path), "wb")
        self.wav_file.setnchannels(self.channels)
        self.wav_file.setsampwidth(2)  # int16
        self.wav_file.setframerate(self.samplerate)

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if status:
                # non-fatal warnings; surfaced in UI log when they happen
                pass
            self.wav_file.writeframes(indata.tobytes())
            # compute simple RMS level for UI meter
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            level = min(1.0, rms * 2.5 / 32768.0)  # boost visual meter to reach top more easily
            with self._lock:
                self._level = level

        stream_kwargs = dict(
            device=self.device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        if extra_settings is not None:
            stream_kwargs["extra_settings"] = extra_settings
        self.stream = sd.InputStream(**stream_kwargs)
        self.stream.start()

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        with self._lock:
            self._level = 0.0

    def is_recording(self) -> bool:
        return self.stream is not None


class MicTester:
    def __init__(self, samplerate: int = 16000, channels: int = 1, device: int | None = None):
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.stream = None
        self._level = 0.0
        self._lock = threading.Lock()
        self.level_history: list[float] = []
        self.above_since: float | None = None
        self.working = False
        self.threshold = 0.12  # approximate normal speech RMS fraction
        self.min_duration = 1.0  # seconds

    @property
    def level(self) -> float:
        with self._lock:
            return self._level

    def start(self, device: int | None, samplerate: int | None = None, channels: int | None = None) -> None:
        if self.stream:
            return
        self.device = device
        if samplerate:
            self.samplerate = samplerate
        if channels:
            self.channels = channels
        self.level_history = []
        self.above_since = None
        self.working = False

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if status:
                pass
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            level = min(1.0, rms / 32768.0)
            level = min(1.0, level * 2.5)  # visual boost to make peaks more visible
            now = time.monotonic()
            with self._lock:
                self._level = level
                self.level_history.append(level)
                self.level_history = self.level_history[-WATERFALL_WINDOW:]
                if level > self.threshold:
                    if self.above_since is None:
                        self.above_since = now
                    elif now - self.above_since >= self.min_duration:
                        self.working = True
                else:
                    self.above_since = None

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        self.stream.start()

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        with self._lock:
            self._level = 0.0

    def is_testing(self) -> bool:
        return self.stream is not None


def transcribe_with_whisper_cpp(audio_file: Path, config) -> str:
    provider = WhisperCppProvider(
        binary=Path(config.stt_binary or "main").expanduser(),
        model=Path(config.stt_model or "").expanduser(),
        language=config.stt_language,
    )
    return provider.transcribe_file(audio_file)


class TranscriptListener:
    """Background websocket listener to stream transcripts into the GUI."""

    def __init__(self, url: str, on_message, on_log) -> None:
        self.url = url
        self.on_message = on_message
        self.on_log = on_log
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread or not self.url:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        try:
            import websockets  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.on_log(f"[warn] Realtime disabled: websockets import failed ({exc})")
            return
        asyncio.run(self._listen(websockets))

    async def _listen(self, websockets) -> None:  # type: ignore[override]
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    self.on_log(f"[info] Connected to realtime server: {self.url}")
                    backoff = 1
                    while not self._stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        self.on_message(msg)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self.on_log(f"[warn] Realtime reconnecting in {backoff}s: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(10, backoff * 2)
class VoiceGUI:
    def __init__(self) -> None:
        self.config = ConfigLoader.load(DEFAULT_CONFIG_PATH)
        self.repo_cfg = ConfigLoader.select_repo(self.config, self.config.default_repo)
        self.root = Tk()
        self.root.title("Voice Issue Recorder")
        self.root.geometry("1340x800")
        self.root.minsize(1120, 760)

        self.recorder: Recorder | None = None
        self.tmp_wav: Path | None = None
        self.mic_tester = MicTester()
        self.device_list = list_input_devices(self.config.device_allowlist, self.config.device_denylist)
        self.selected_device_id: int | None = self.device_list[0]["id"] if self.device_list else None
        self.selected_device_name: str = self.device_list[0]["name"] if self.device_list else "None"
        self.selected_device_hostapi: int | None = self.device_list[0].get("hostapi") if self.device_list else None
        self.controls_frame = ttk.Frame(self.root)
        self.status_var: ttk.Label | None = None
        self.log_widget: scrolledtext.ScrolledText | None = None
        self.live_indicator: ttk.Label | None = None
        self.start_btn: ttk.Button | None = None
        self.stop_btn: ttk.Button | None = None
        self.test_cta_btn: ttk.Button | None = None
        self.live_transcript_widget: scrolledtext.ScrolledText | None = None
        self.test_btn: ttk.Button | None = None
        self.test_canvas: Canvas | None = None
        self.hotkey_indicator = None
        self.hotkey_registered = False
        self.device_label = None
        self.issue_listbox: Listbox | None = None
        self.issue_listbox_done: Listbox | None = None
        self.issue_listbox_wait: Listbox | None = None
        self.issue_entries_pending: list[tuple[list[int], str]] = []
        self.issue_entries_done: list[tuple[list[int], str]] = []
        self.issue_entries_wait: list[tuple[list[int], str]] = []
        self.issue_header_labels: dict[str, tuple[ttk.Label, str]] = {}
        self.pending_row_map: list[int] = []
        self.done_row_map: list[int] = []
        self.wait_row_map: list[int] = []
        self._listbox_select_guard = False
        self.waterfall_history: list[float] = []
        self.skip_delete_confirm = BooleanVar(value=False)
        self._drag_info: dict | None = None
        self.waterfall_status: ttk.Label | None = None
        self.transcript_listener: TranscriptListener | None = None
        self.hotkey_toggle_var = StringVar(value=self.config.hotkey_toggle)
        self.hotkey_quit_var = StringVar(value=self.config.hotkey_quit)
        self.repo_path_var = StringVar(value=str(self.repo_cfg.repo_path))
        self.issues_path_var = StringVar(value=str(self.repo_cfg.issues_file))
        self.repo_hint_var = StringVar(value="")
        self.repo_hint_label: ttk.Label | None = None
        self.hotkey_info_label: ttk.Label | None = None
        self.repo_info_label: ttk.Label | None = None
        self.issues_info_label: ttk.Label | None = None
        self.device_combo: ttk.Combobox | None = None
        self.repo_combo: ttk.Combobox | None = None
        self.repo_history: list[str] = self._load_repo_history()
        self.dark_mode_var = BooleanVar(value=False)
        self.style = ttk.Style(self.root)
        self.static_info_label: ttk.Label | None = None
        self._repo_path_trace_guard = False
        self.repo_path_var.trace_add("write", self._on_repo_path_value_changed)
        self.issues_path_var.trace_add("write", lambda *args: self._update_repo_hint())
        self._on_repo_path_value_changed()

        self._build_layout()
        self._update_theme()
        self._ensure_keyboard_module()
        self.root.after(100, self._poll_level)
        self._register_hotkeys()
        self._refresh_issue_list()
        self._start_transcript_listener()
        self._cleanup_tmp_dir()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        build_layout_structure(self)

    def _build_header(self, parent: ttk.Frame) -> None:
        """Render the app title in a consistent block."""
        ttk.Label(parent, text="Voice Issue Recorder", font=("Segoe UI", 12, "bold")).pack(anchor="w")

    def _build_status_label(self, parent: ttk.Frame, pad: dict[str, int]) -> None:
        self.status_var = ttk.Label(parent, text="Ready")
        self.status_var.pack(anchor="w", **pad)

    def _build_log_block(self, parent: Tk) -> None:
        log_frame = ttk.Frame(parent)
        log_frame.pack(fill=BOTH, expand=False, padx=10, pady=(0, 10))
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=8, state=DISABLED)
        self.log_widget.pack(fill=BOTH, expand=False, pady=(2, 0))
        self._log("Ready. Select mic, use 'Test Selected Mic' to monitor, then Start Recording.")

    def _build_move_buttons(self, parent: ttk.Frame) -> None:
        move_all_row = ttk.Frame(parent)
        move_all_row.pack(fill=BOTH, expand=False, pady=(0, 4))
        ttk.Label(move_all_row, text="Move selected to:").pack(side=LEFT, padx=(0, 6))
        ttk.Button(move_all_row, text="Pending", command=self._mark_any_pending).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Completed", command=self._mark_any_completed).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Waitlist", command=self._mark_any_waitlist).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Remove duplicates", command=self._remove_duplicate_issues).pack(side=LEFT, padx=(0, 4))
        ttk.Checkbutton(
            move_all_row,
            text="Skip delete confirmation",
            variable=self.skip_delete_confirm,
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
            height=16,
            selectmode="extended",
            exportselection=False,
        )
        listbox.grid(row=1, column=0, sticky="nsew", pady=(2, 4))
        if bucket == "pending":
            self.issue_listbox = listbox
            listbox.bind("<<ListboxSelect>>", self._on_pending_select)
        elif bucket == "done":
            self.issue_listbox_done = listbox
            listbox.bind("<<ListboxSelect>>", self._on_done_select)
        else:
            self.issue_listbox_wait = listbox
            listbox.bind("<<ListboxSelect>>", lambda e: self._on_wait_select())
        self.issue_header_labels[bucket] = (header, base_label)
        listbox.bind("<ButtonPress-1>", lambda e, b=bucket: self._start_drag(e, b))
        listbox.bind("<ButtonRelease-1>", lambda e, b=bucket: self._finish_drag(e, b))
        listbox.bind("<Double-Button-1>", lambda e, b=bucket: self._on_issue_double_click(e, b))

        btn_row = ttk.Frame(column)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        if bucket == "pending":
            ttk.Button(btn_row, text="Select all", command=self._select_all_pending).pack(side=LEFT, padx=(0, 4))
            ttk.Button(btn_row, text="Delete selected", command=self._delete_selected_pending).pack(side=LEFT)
            move_row = ttk.Frame(column)
            move_row.grid(row=3, column=0, sticky="ew", pady=(0, 2))
            ttk.Button(move_row, text="Move up", command=lambda: self._move_pending_selection(-1)).pack(side=LEFT, padx=(0, 4))
            ttk.Button(move_row, text="Move down", command=lambda: self._move_pending_selection(1)).pack(side=LEFT)
        elif bucket == "done":
            ttk.Button(btn_row, text="Select all", command=self._select_all_done).pack(side=LEFT, padx=(0, 4))
            ttk.Button(btn_row, text="Delete selected", command=self._delete_selected_done).pack(side=LEFT)
        else:
            ttk.Button(btn_row, text="Select all", command=lambda: self._select_all_list(self.issue_listbox_wait)).pack(
                side=LEFT, padx=(0, 4)
            )
            ttk.Button(btn_row, text="Delete selected", command=self._delete_selected_wait).pack(side=LEFT)

    def _build_settings_panel(self, parent: ttk.Frame, pad: dict[str, int]) -> None:
        self.test_cta_btn = ttk.Button(parent, text="Test Selected Mic", command=self.toggle_mic_test)
        self.test_cta_btn.pack(fill=BOTH, padx=10, pady=(4, 4))

        columns = ttk.Frame(parent)
        columns.pack(fill=BOTH, expand=True, **pad)
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)

        left_col = ttk.Frame(columns)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right_col = ttk.Frame(columns)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        right_col.columnconfigure(0, weight=1)

        hk_row = ttk.Frame(left_col, padding=(6, 2, 6, 2))
        hk_row.pack(fill=BOTH, **pad)
        ttk.Label(hk_row, text="Hotkey toggle:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.hotkey_toggle_var, width=16).pack(side=LEFT, padx=(0, 10))
        ttk.Label(hk_row, text="Hotkey quit:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.hotkey_quit_var, width=16).pack(side=LEFT, padx=(0, 10))

        path_row = ttk.Frame(left_col, padding=(6, 2, 6, 2))
        path_row.pack(fill=BOTH, **pad)
        ttk.Label(path_row, text="Repo path:").pack(side=LEFT, padx=(0, 6))
        repo_values = list(self.repo_history)
        current_repo = str(self.repo_cfg.repo_path)
        if repo_values and repo_values[0] == current_repo:
            combo_values = repo_values
        else:
            combo_values = [current_repo] + [v for v in repo_values if v != current_repo]
        self.repo_combo = ttk.Combobox(
            path_row,
            textvariable=self.repo_path_var,
            values=combo_values,
            state="normal",
            width=70,
        )
        self.repo_combo.pack(side=LEFT, padx=(0, 10))
        ttk.Button(path_row, text="Browse...", width=8, command=self._browse_repo_path).pack(side=LEFT, padx=(0, 6))
        self._update_repo_combo_values(current_repo=self.repo_cfg.repo_path)

        issue_path_row = ttk.Frame(left_col, padding=(6, 2, 6, 2))
        issue_path_row.pack(fill=BOTH, **pad)
        ttk.Label(issue_path_row, text="Issues file:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(issue_path_row, textvariable=self.issues_path_var, width=70).pack(side=LEFT, padx=(0, 10))
        ttk.Label(issue_path_row, text="🗣️", font=("Segoe UI Emoji", 12)).pack(side=LEFT, padx=(0, 4))
        ttk.Button(
            issue_path_row,
            text="Create voice file",
            width=16,
            command=self._create_voice_file_for_selected_repo,
        ).pack(side=LEFT, padx=(0, 6))

        hint_row = ttk.Frame(left_col, padding=(6, 0, 6, 2))
        hint_row.pack(fill="x", **pad)
        self.repo_hint_label = ttk.Label(
            hint_row,
            textvariable=self.repo_hint_var,
            wraplength=460,
            justify=LEFT,
        )
        self.repo_hint_label.pack(anchor="w")

        apply_btn = ttk.Button(left_col, text="Apply settings", command=self._apply_settings, width=18)
        apply_btn.pack(anchor="w", padx=10, pady=(0, 6))

        self.hotkey_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.hotkey_info_label.pack(fill="x", padx=(6, 4), pady=(2, 1))
        self.repo_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.repo_info_label.pack(fill="x", padx=(6, 4), pady=(0, 1))
        self.issues_info_label = ttk.Label(right_col, text="", justify=LEFT, anchor="w")
        self.issues_info_label.pack(fill="x", padx=(6, 4), pady=(0, 1))
        theme_row = ttk.Frame(right_col, padding=(6, 2, 6, 2))
        theme_row.pack(fill="x", padx=(6, 4), pady=(4, 0))
        ttk.Checkbutton(
            theme_row,
            text="Dark mode",
            variable=self.dark_mode_var,
            command=self._update_theme,
        ).pack(side=LEFT)

        device_row = ttk.Frame(left_col, padding=(2, 1, 2, 1))
        device_row.pack(fill="x", expand=False, padx=8, pady=(0, 4))
        device_row.columnconfigure(0, weight=0)
        device_row.columnconfigure(1, weight=4)
        device_row.columnconfigure(2, weight=1)
        ttk.Label(device_row, text="Input device:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        values = [f"{d['id']}: {d['name']}" for d in self.device_list]
        self.device_combo = ttk.Combobox(
            device_row,
            values=values,
            state="readonly",
            width=32,
        )
        self.device_combo.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        if self.device_list:
            self.device_combo.current(0)
            self.device_combo.bind("<<ComboboxSelected>>", self.on_device_change)
        ttk.Button(device_row, text="Refresh", command=self.refresh_devices).grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.live_indicator = ttk.Label(device_row, text="Idle", foreground="white", background="#666666", padding=6)
        self.live_indicator.grid(row=0, column=3, sticky="e", padx=(0, 0))
        self._refresh_static_info()
        self._update_theme()

    def _current_palette(self) -> dict[str, str]:
        return DARK_THEME if self.dark_mode_var.get() else LIGHT_THEME

    def _update_theme(self) -> None:
        palette = self._current_palette()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure("TFrame", background=palette["panel_bg"])
        self.style.configure("TLabel", background=palette["panel_bg"], foreground=palette["fg"])
        self.style.configure("TButton", background=palette["element_bg"], foreground=palette["fg"])
        self.style.configure("TCheckbutton", background=palette["panel_bg"], foreground=palette["fg"])
        self.style.configure("TEntry", fieldbackground=palette["entry_bg"], foreground=palette["fg"])
        self.style.configure("TCombobox", fieldbackground=palette["entry_bg"], foreground=palette["fg"])
        self.root.configure(background=palette["root_bg"])
        for lb in (self.issue_listbox, self.issue_listbox_done, self.issue_listbox_wait):
            if lb:
                lb.configure(
                    background=palette["list_bg"],
                    foreground=palette["fg"],
                    selectbackground=palette["select_bg"],
                    selectforeground=palette["select_fg"],
                    highlightbackground=palette["border"],
                    activestyle="none",
                )
        if self.log_widget:
            self.log_widget.configure(
                background=palette["list_bg"],
                foreground=palette["fg"],
                insertbackground=palette["fg"],
            )
        if self.live_indicator:
            self.live_indicator.config(background=palette["accent"], foreground="white")
        if self.test_canvas:
            self.test_canvas.configure(background=palette["canvas_bg"])
        if self.repo_hint_label:
            self.repo_hint_label.config(foreground=palette["accent"])
        self._draw_test_history(self.waterfall_history)

    def _waterfall_color(self, level: float, palette: dict[str, str]) -> str:
        val = max(0.0, min(level, 1.0))
        if val < 0.25:
            return "#1c4571"
        if val < 0.5:
            return "#1d88bc"
        if val < 0.75:
            return "#47c7ff"
        return palette["accent"]

    def _build_live_panel(self, parent: ttk.Frame, pad: dict[str, int]) -> None:
        parent.columnconfigure(0, weight=1)
        live_output_frame = ttk.Frame(parent, padding=(6, 4, 6, 4))
        live_output_frame.grid(row=0, column=0, sticky="nsew")
        live_output_frame.columnconfigure(0, weight=1)
        ttk.Label(live_output_frame, text="Live speech output:").pack(anchor="w")
        self.live_transcript_widget = scrolledtext.ScrolledText(live_output_frame, height=5, state=DISABLED)
        self.live_transcript_widget.pack(fill=BOTH, expand=True, pady=(2, 0))

    def _build_audio_panel(self, parent: ttk.Frame, pad: dict[str, int]) -> None:
        wf_header = ttk.Frame(parent)
        wf_header.pack(fill=BOTH, padx=10, pady=(4, 0))
        ttk.Label(wf_header, text="Microphone waterfall").pack(side=LEFT)
        self.waterfall_status = ttk.Label(wf_header, text="Waterfall: idle")
        self.waterfall_status.pack(side=LEFT, padx=(8, 0))
        self.test_canvas = Canvas(parent, height=280, bg="#1e1e1e", highlightthickness=0)
        self.test_canvas.pack(fill=BOTH, expand=True, padx=10, pady=(0, 5))

    def _build_action_buttons(self, parent: ttk.Frame, pad: dict[str, int]) -> None:
        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=BOTH, **pad)
        self.start_btn = ttk.Button(btn_row, text="Start Recording", command=self.start_recording)
        self.start_btn.pack(side=LEFT, expand=True, fill=BOTH, padx=(0, 5))
        self.stop_btn = ttk.Button(btn_row, text="Stop & Transcribe", command=self.stop_recording, state=DISABLED)
        self.stop_btn.pack(side=RIGHT, expand=True, fill=BOTH, padx=(5, 0))

    def _build_issues_panel(self, parent: ttk.Frame) -> None:
        panel = ttk.Frame(parent, padding=(8, 0, 0, 0))
        panel.pack(fill=BOTH, expand=True)
        self._build_move_buttons(panel)

        lists_row = ttk.Frame(panel)
        lists_row.pack(fill=BOTH, expand=True)

        self._build_issue_column(lists_row, "Pending issues:", "pending")
        self._build_issue_column(lists_row, "Completed issues:", "done")
        self._build_issue_column(lists_row, "Waitlist issues:", "wait")


    def _log(self, msg: str) -> None:
        if not self.log_widget:
            return
        self.log_widget.config(state=NORMAL)
        self.log_widget.insert(END, msg + "\n")
        self.log_widget.see(END)
        self.log_widget.config(state=DISABLED)

    def _handle_transcript_message(self, text: str) -> None:
        # Live transcript pane is reserved for future playback; ignore incoming text.
        return

    def _start_transcript_listener(self) -> None:
        if not self.config.realtime_ws_url:
            return
        self.transcript_listener = TranscriptListener(
            self.config.realtime_ws_url,
            on_message=self._handle_transcript_message,
            on_log=lambda m: self.root.after(0, lambda: self._log(m)),
        )
        self.transcript_listener.start()

    def _send_transcript_to_server(self, text: str) -> None:
        if not text or not self.config.realtime_post_url:
            return
        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            self.config.realtime_post_url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 300:
                    self._log(f"[warn] Realtime server returned {resp.status}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Failed to send transcript to server: {exc}")

    def _refresh_issue_list(self) -> None:
        try:
            lines = self._sanitize_issues_file()
            pending: list[tuple[list[int], str]] = []
            done: list[tuple[list[int], str]] = []
            wait: list[tuple[list[int], str]] = []
            for idx, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("- [") or stripped.startswith("* ["):
                    # Determine state by second char after '['
                    state_char = stripped[3:4] if len(stripped) > 3 else " "
                    if state_char.lower() == "x":
                        done.append(([idx], stripped))
                    elif state_char.lower() in (WAIT_STATE_CHAR, "w"):
                        wait.append(([idx], stripped))
                    else:
                        pending.append(([idx], stripped))
            self.issue_entries_pending = pending
            self.issue_entries_done = done
            self.issue_entries_wait = wait
            if self.issue_listbox:
                self.issue_listbox.delete(0, END)
                self.pending_row_map = []
                self._populate_issue_listbox(self.issue_listbox, pending, self.pending_row_map)
            if self.issue_listbox_done:
                self.issue_listbox_done.delete(0, END)
                self.done_row_map = []
                self._populate_issue_listbox(self.issue_listbox_done, done, self.done_row_map)
            if self.issue_listbox_wait:
                self.issue_listbox_wait.delete(0, END)
                self.wait_row_map = []
                self._populate_issue_listbox(self.issue_listbox_wait, wait, self.wait_row_map)
            self._update_issue_header("pending", len(pending))
            self._update_issue_header("done", len(done))
            self._update_issue_header("wait", len(wait))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Unable to read issues file {self.repo_cfg.issues_file}: {exc}")

    def _populate_issue_listbox(self, listbox: Listbox, entries: list[tuple[list[int], str]], row_map: list[int]) -> None:
        wrap_width = 70
        for idx, (_, text) in enumerate(entries):
            wrapped = textwrap.wrap(text, width=wrap_width) or [text]
            for j, line in enumerate(wrapped):
                if j == 0:
                    display = f"[{idx + 1}] {line}"
                else:
                    display = f"   {line}"
                listbox.insert(END, display)
                row_map.append(idx)

    def _update_issue_header(self, bucket: str, count: int) -> None:
        entry = self.issue_header_labels.get(bucket)
        if not entry:
            return
        widget, base_label = entry
        widget.config(text=f"{base_label} [{count}]")

    def _on_pending_select(self, event=None) -> None:  # type: ignore[override]
        self._expand_issue_selection(self.issue_listbox, self.pending_row_map)

    def _on_done_select(self, event=None) -> None:  # type: ignore[override]
        self._expand_issue_selection(self.issue_listbox_done, self.done_row_map)

    def _on_wait_select(self, event=None) -> None:  # type: ignore[override]
        self._expand_issue_selection(self.issue_listbox_wait, self.wait_row_map)

    def _start_drag(self, event, source: str) -> None:
        listbox = event.widget
        try:
            row = listbox.nearest(event.y)
        except Exception:
            return
        row_map = self._row_map_for_source(source)
        if row_map is None or row < 0 or row >= len(row_map):
            return
        entry_idx = row_map[row]
        self._drag_info = {"source": source, "entry_idx": entry_idx}

    def _finish_drag(self, event, target: str) -> None:
        """
        Complete a drag-drop move between listboxes. Target bucket is resolved from the widget under the cursor.
        """
        if not self._drag_info:
            return
        info = self._drag_info
        self._drag_info = None
        source = info.get("source")
        entry_idx = info.get("entry_idx")
        if entry_idx is None:
            return

        # Resolve drop target from the widget under the cursor to allow cross-list drags.
        drop_widget = self.root.winfo_containing(event.x_root, event.y_root)
        resolved_target = self._bucket_for_widget(drop_widget) or target
        if source == resolved_target:
            return

        entries = self._entries_for_source(source)
        if entries is None or not (0 <= entry_idx < len(entries)):
            return
        idx_list, _ = entries[entry_idx]
        targets = set(idx_list)
        state_char = self._state_char_for_target(resolved_target)
        if state_char is None:
            return
        try:
            lines = self._sanitize_issues_file()
            new_lines = []
            for i, line in enumerate(lines):
                if i in targets:
                    new_lines.append(self._set_issue_state(line, state_char))
                else:
                    new_lines.append(line)
            text = "\n".join(new_lines)
            if text and not text.endswith("\n"):
                text += "\n"
            self.repo_cfg.issues_file.write_text(text, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Dragged {len(targets)} issue(s) to {resolved_target}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to move issue(s): {exc}")

    def _row_map_for_source(self, source: str) -> list[int] | None:
        if source == "pending":
            return self.pending_row_map
        if source == "done":
            return self.done_row_map
        if source == "wait":
            return self.wait_row_map
        return None

    def _entries_for_source(self, source: str) -> list[tuple[list[int], str]] | None:
        if source == "pending":
            return self.issue_entries_pending
        if source == "done":
            return self.issue_entries_done
        if source == "wait":
            return self.issue_entries_wait
        return None

    def _entry_for_bucket(self, bucket: str, list_index: int) -> tuple[list[int], str] | None:
        row_map = self._row_map_for_source(bucket)
        entries = self._entries_for_source(bucket)
        if row_map is None or entries is None or not (0 <= list_index < len(row_map)):
            return None
        entry_idx = row_map[list_index]
        if 0 <= entry_idx < len(entries):
            return entries[entry_idx]
        return None

    def _edit_issue_entry(self, bucket: str, row: int) -> None:
        entry = self._entry_for_bucket(bucket, row)
        if not entry:
            return
        target_indices, current_text = entry
        self._open_issue_editor(current_text, target_indices)

    def _on_issue_double_click(self, event, bucket: str) -> None:
        listbox = self._listbox_for_bucket(bucket)
        if not listbox:
            return
        selection = listbox.curselection()
        if not selection:
            row = listbox.nearest(event.y)
            if row < 0:
                return
            listbox.selection_clear(0, END)
            listbox.selection_set(row)
            selection = (row,)
        self._edit_issue_entry(bucket, selection[0])

    def _open_issue_editor(self, initial_text: str, target_indices: list[int]) -> None:
        editor = Toplevel(self.root)
        editor.title("Edit issue")
        editor.transient(self.root)
        editor.grab_set()
        frame = ttk.Frame(editor, padding=8)
        frame.pack(fill=BOTH, expand=True)
        ttk.Label(frame, text="Edit issue text:").pack(anchor="w")
        text_widget = scrolledtext.ScrolledText(frame, height=6, wrap="word")
        text_widget.pack(fill=BOTH, expand=True, pady=(4, 4))
        text_widget.insert(END, initial_text)
        text_widget.focus_set()

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=BOTH, pady=(0, 4))

        def _save() -> None:
            new_text = text_widget.get("1.0", END).strip()
            if not new_text:
                messagebox.showwarning("Edit issue", "Issue text cannot be empty.")
                return
            try:
                self._apply_issue_edit(target_indices, new_text)
            finally:
                editor.destroy()

        ttk.Button(btn_row, text="Save", command=_save).pack(side=LEFT, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", command=editor.destroy).pack(side=LEFT)

    def _apply_issue_edit(self, target_indices: Iterable[int], new_text: str) -> None:
        try:
            lines = self._sanitize_issues_file()
            for idx in set(target_indices):
                if 0 <= idx < len(lines):
                    match = re.match(r"^(\s*[-*]\s*\[[^\]]\]\s*)(.*)", lines[idx])
                    if match:
                        lines[idx] = f"{match.group(1)}{new_text}"
                    else:
                        lines[idx] = f"- [ ] {new_text}"
            text_out = "\n".join(lines)
            if text_out and not text_out.endswith("\n"):
                text_out += "\n"
            self.repo_cfg.issues_file.write_text(text_out, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Updated issue text in {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to update issue text: {exc}")

    def _state_char_for_target(self, target: str) -> str | None:
        if target == "pending":
            return " "
        if target == "done":
            return "x"
        if target == "wait":
            return WAIT_STATE_CHAR
        return None

    def _bucket_for_widget(self, widget) -> str | None:
        if widget in (self.issue_listbox,):
            return "pending"
        if widget in (self.issue_listbox_done,):
            return "done"
        if widget in (self.issue_listbox_wait,):
            return "wait"
        return None

    def _listbox_for_bucket(self, bucket: str) -> Listbox | None:
        if bucket == "pending":
            return self.issue_listbox
        if bucket == "done":
            return self.issue_listbox_done
        if bucket == "wait":
            return self.issue_listbox_wait
        return None

    def _expand_issue_selection(self, listbox: Listbox | None, row_map: list[int]) -> None:
        """
        When a line belonging to a wrapped issue is selected, ensure every line for that issue is selected.
        """
        if not listbox or self._listbox_select_guard:
            return
        selection = listbox.curselection()
        if not selection:
            return
        selected_entries = {row_map[i] for i in selection if 0 <= i < len(row_map)}
        if not selected_entries:
            return
        self._listbox_select_guard = True
        try:
            listbox.selection_clear(0, END)
            for idx, entry_idx in enumerate(row_map):
                if entry_idx in selected_entries:
                    listbox.select_set(idx)
        finally:
            self._listbox_select_guard = False

    def _select_all_pending(self) -> None:
        if self.issue_listbox:
            self.issue_listbox.select_set(0, END)

    def _select_all_list(self, listbox: Listbox | None) -> None:
        if listbox:
            listbox.select_set(0, END)

    def _select_all_done(self) -> None:
        if self.issue_listbox_done:
            self.issue_listbox_done.select_set(0, END)

    def _selected_pending_ids(self, selection: tuple[int, ...]) -> set[tuple[int, ...]]:
        ids: set[tuple[int, ...]] = set()
        for row in selection:
            if 0 <= row < len(self.pending_row_map):
                entry_idx = self.pending_row_map[row]
                if 0 <= entry_idx < len(self.issue_entries_pending):
                    idx_list, _ = self.issue_entries_pending[entry_idx]
                    ids.add(tuple(idx_list))
        return ids

    def _reorder_pending_segments(
        self, items: list[tuple[tuple[int, ...], str, str]], selected_ids: set[tuple[int, ...]], direction: int
    ) -> list[tuple[tuple[int, ...], str, str]]:
        segments: list[tuple[bool, list[tuple[tuple[int, ...], str, str]]]] = []
        current_type: bool | None = None
        current_segment: list[tuple[tuple[int, ...], str, str]] = []
        for item in items:
            is_selected = item[0] in selected_ids
            if current_type is None or is_selected != current_type:
                if current_segment:
                    segments.append((current_type, current_segment))
                current_segment = []
                current_type = is_selected
            current_segment.append(item)
        if current_segment:
            segments.append((current_type, current_segment))

        if direction == -1:
            idx = 0
            while idx < len(segments):
                is_selected, seg = segments[idx]
                if is_selected and idx > 0 and not segments[idx - 1][0]:
                    segments[idx - 1], segments[idx] = segments[idx], segments[idx - 1]
                    idx += 1
                idx += 1
        else:
            idx = len(segments) - 1
            while idx >= 0:
                is_selected, seg = segments[idx]
                if is_selected and idx < len(segments) - 1 and not segments[idx + 1][0]:
                    segments[idx], segments[idx + 1] = segments[idx + 1], segments[idx]
                    idx -= 1
                idx -= 1

        new_items: list[tuple[tuple[int, ...], str, str]] = []
        for _, segment in segments:
            new_items.extend(segment)
        return new_items

    def _move_pending_selection(self, direction: int) -> None:
        if not self.issue_listbox:
            return
        selection = self.issue_listbox.curselection()
        if not selection:
            return
        selected_ids = self._selected_pending_ids(selection)
        if not selected_ids:
            return
        pending_values = [(tuple(idx_list), "[ ]", text) for idx_list, text in self.issue_entries_pending]
        reordered = self._reorder_pending_segments(pending_values, selected_ids, direction)
        if reordered == pending_values:
            return
        entries = self._read_issue_entries()
        pending_iter = iter((state, text) for _, state, text in reordered)
        new_entries: list[tuple[str, str]] = []
        for state, text in entries:
            if self._is_pending_state(state):
                new_state, new_text = next(pending_iter)
                new_entries.append((new_state, new_text))
            else:
                new_entries.append((state, text))
        self._write_issue_entries(new_entries)
        self._refresh_issue_list()
        self._log(f"[ok] Reordered {len(selected_ids)} pending issue(s).")

    def _delete_selected_pending(self) -> None:
        if not self.issue_listbox:
            return
        selection = self.issue_listbox.curselection()
        if not selection:
            return
        entry_ids: set[int] = set()
        items = []
        for row in selection:
            if 0 <= row < len(self.pending_row_map):
                entry_idx = self.pending_row_map[row]
                if 0 <= entry_idx < len(self.issue_entries_pending):
                    if entry_idx not in entry_ids:
                        entry_ids.add(entry_idx)
                        items.append(self.issue_entries_pending[entry_idx])
        if not items:
            return
        if not self.skip_delete_confirm.get():
            confirm = messagebox.askyesno("Delete issue(s)", f"Delete {len(items)} pending issue(s)?")
            if not confirm:
                return
        try:
            lines = self._sanitize_issues_file()
            to_remove = {idx for idx_list, _ in items for idx in idx_list}
            new_lines = [line for i, line in enumerate(lines) if i not in to_remove]
            text = "\n".join(new_lines)
            if text and not text.endswith("\n"):
                text += "\n"
            self.repo_cfg.issues_file.write_text(text, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Deleted {len(items)} pending issue(s) from {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to delete issue(s): {exc}")

    def _delete_selected_done(self) -> None:
        if not self.issue_listbox_done:
            return
        selection = self.issue_listbox_done.curselection()
        if not selection:
            return
        entry_ids: set[int] = set()
        items = []
        for row in selection:
            if 0 <= row < len(self.done_row_map):
                entry_idx = self.done_row_map[row]
                if 0 <= entry_idx < len(self.issue_entries_done):
                    if entry_idx not in entry_ids:
                        entry_ids.add(entry_idx)
                        items.append(self.issue_entries_done[entry_idx])
        if not items:
            return
        if not self.skip_delete_confirm.get():
            confirm = messagebox.askyesno("Delete issue(s)", f"Delete {len(items)} completed issue(s)?")
            if not confirm:
                return
        try:
            lines = self._sanitize_issues_file()
            to_remove = {idx for idx_list, _ in items for idx in idx_list}
            new_lines = [line for i, line in enumerate(lines) if i not in to_remove]
            text = "\n".join(new_lines)
            if text and not text.endswith("\n"):
                text += "\n"
            self.repo_cfg.issues_file.write_text(text, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Deleted {len(items)} completed issue(s) from {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to delete issue(s): {exc}")

    def _delete_selected_wait(self) -> None:
        if not self.issue_listbox_wait:
            return
        selection = self.issue_listbox_wait.curselection()
        if not selection:
            return
        entry_ids: set[int] = set()
        items = []
        for row in selection:
            if 0 <= row < len(self.wait_row_map):
                entry_idx = self.wait_row_map[row]
                if 0 <= entry_idx < len(self.issue_entries_wait):
                    if entry_idx not in entry_ids:
                        entry_ids.add(entry_idx)
                        items.append(self.issue_entries_wait[entry_idx])
        if not items:
            return
        if not self.skip_delete_confirm.get():
            confirm = messagebox.askyesno("Delete issue(s)", f"Delete {len(items)} waitlist issue(s)?")
            if not confirm:
                return
        try:
            lines = self._sanitize_issues_file()
            to_remove = {idx for idx_list, _ in items for idx in idx_list}
            new_lines = [line for i, line in enumerate(lines) if i not in to_remove]
            text = "\n".join(new_lines)
            if text and not text.endswith("\n"):
                text += "\n"
            self.repo_cfg.issues_file.write_text(text, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Deleted {len(items)} waitlist issue(s) from {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to delete issue(s): {exc}")

    def _mark_any_pending(self) -> None:
        entries = self._collect_selected_entries()
        self._change_entries_state(entries, " ", "pending")

    def _mark_any_completed(self) -> None:
        entries = self._collect_selected_entries()
        self._change_entries_state(entries, "x", "completed")

    def _mark_any_waitlist(self) -> None:
        entries = self._collect_selected_entries()
        self._change_entries_state(entries, WAIT_STATE_CHAR, "waitlist")

    def _change_issue_state(
        self,
        listbox: Listbox | None,
        row_map: list[int],
        entries: list[tuple[list[int], str]],
        target_state_char: str,
        label: str,
    ) -> None:
        if not listbox:
            return
        selection = listbox.curselection()
        if not selection:
            return
        selected_entries = []
        for row in selection:
            if 0 <= row < len(row_map):
                entry_idx = row_map[row]
                if 0 <= entry_idx < len(entries):
                    selected_entries.append(entries[entry_idx])
        if not selected_entries:
            return
        self._change_entries_state(selected_entries, target_state_char, label)

    def _collect_selected_entries(self) -> list[tuple[list[int], str]]:
        entries: list[tuple[list[int], str]] = []
        seen: set[tuple[str, int]] = set()
        for source, listbox, row_map, data in [
            ("pending", self.issue_listbox, self.pending_row_map, self.issue_entries_pending),
            ("done", self.issue_listbox_done, self.done_row_map, self.issue_entries_done),
            ("wait", self.issue_listbox_wait, self.wait_row_map, self.issue_entries_wait),
        ]:
            if not listbox:
                continue
            for row in listbox.curselection():
                if 0 <= row < len(row_map):
                    entry_idx = row_map[row]
                    key = (source, entry_idx)
                    if 0 <= entry_idx < len(data) and key not in seen:
                        seen.add(key)
                        entries.append(data[entry_idx])
        return entries

    def _change_entries_state(self, entries: list[tuple[list[int], str]], target_state_char: str, label: str) -> None:
        if not entries:
            return
        targets = {idx for idx_list, _ in entries for idx in idx_list}
        try:
            lines = self._sanitize_issues_file()
            new_lines = []
            for i, line in enumerate(lines):
                if i in targets:
                    new_lines.append(self._set_issue_state(line, target_state_char))
                else:
                    new_lines.append(line)
            text = "\n".join(new_lines)
            if text and not text.endswith("\n"):
                text += "\n"
            self.repo_cfg.issues_file.write_text(text, encoding="utf-8")
            self._refresh_issue_list()
            self._log(f"[ok] Moved {len(targets)} issue(s) to {label} in {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to update issue state: {exc}")

    @staticmethod
    def _set_issue_state(line: str, state_char: str) -> str:
        return re.sub(r"^(\s*[-*]\s*\[)[^\]](\])", rf"\1{state_char}\2", line)

    def _apply_settings(self) -> None:
        toggle = self.hotkey_toggle_var.get().strip()
        quit_key = self.hotkey_quit_var.get().strip()
        try:
            repo_path, issues_path = self._resolve_repo_and_issues()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Invalid paths: {exc}")
            return

        self._record_repo_history(repo_path)
        self._ensure_repo_voice_assets(repo_path, issues_path)

        try:
            data = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to read config for update: {exc}")
            return

        data.setdefault("hotkeys", {})
        if toggle:
            data["hotkeys"]["toggle"] = toggle
        if quit_key:
            data["hotkeys"]["quit"] = quit_key
        data.setdefault("repos", {})
        data["defaultRepo"] = str(repo_path)
        try:
            rel_issue = str(issues_path.resolve().relative_to(repo_path))
            issue_entry = rel_issue
        except Exception:
            issue_entry = str(issues_path.resolve())
        data["repos"][str(repo_path)] = {"issuesFile": issue_entry}

        try:
            DEFAULT_CONFIG_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to write config: {exc}")
            return

        try:
            self.config = ConfigLoader.load(DEFAULT_CONFIG_PATH)
            self.repo_cfg = ConfigLoader.select_repo(self.config, self.config.default_repo)
            self.hotkey_toggle_var.set(self.config.hotkey_toggle)
            self.hotkey_quit_var.set(self.config.hotkey_quit)
            self.repo_path_var.set(str(self.repo_cfg.repo_path))
            self.issues_path_var.set(str(self.repo_cfg.issues_file))
            # Re-register hotkeys with new combos
            if keyboard:
                try:
                    keyboard.unhook_all()
                except Exception:
                    pass
            self.hotkey_registered = False
            self._register_hotkeys()
            self._refresh_issue_list()
            self._log(f"[ok] Settings updated and saved to {DEFAULT_CONFIG_PATH}")
            self._refresh_static_info()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to apply settings: {exc}")

    def _resolve_repo_and_issues(self) -> tuple[Path, Path]:
        repo_raw = self.repo_path_var.get().strip()
        issues_raw = self.issues_path_var.get().strip()
        repo_path = Path(repo_raw).expanduser().resolve()
        issues_path = Path(issues_raw).expanduser()
        if not issues_path.is_absolute():
            issues_path = (repo_path / issues_path).resolve()
        return repo_path, issues_path

    def _create_voice_file_for_selected_repo(self) -> None:
        try:
            repo_path, _ = self._resolve_repo_and_issues()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Invalid paths: {exc}")
            return
        issues_path = repo_path / ".voice" / "voice-issues.md"
        self.issues_path_var.set(str(issues_path))
        self._ensure_repo_voice_assets(repo_path, issues_path)
        self._record_repo_history(repo_path)
        try:
            rel_issue_entry = str(issues_path.resolve().relative_to(repo_path))
        except Exception:
            rel_issue_entry = str(issues_path.resolve())
        if self.config:
            self.config.default_repo = str(repo_path)
            self.config.repos[str(repo_path)] = {"issuesFile": rel_issue_entry}
        self.repo_cfg = RepoConfig(repo_path=repo_path, issues_file=issues_path)
        self.repo_path_var.set(str(repo_path))
        self.issues_path_var.set(str(issues_path))
        self._refresh_issue_list()
        self._refresh_static_info()
        self._log(f"[ok] Created voice issues file at {issues_path}")

    def _static_info_text(self) -> tuple[str, str, str]:
        return (
            f"Hotkeys: toggle {self.hotkey_toggle_var.get()} | quit {self.hotkey_quit_var.get()}",
            f"Repo: {self.repo_path_var.get()}",
            f"Issues: {self.issues_path_var.get()}",
        )

    def _refresh_static_info(self) -> None:
        hotkey_text, repo_text, issues_text = self._static_info_text()
        if self.hotkey_info_label:
            self.hotkey_info_label.config(text=hotkey_text)
        if self.repo_info_label:
            self.repo_info_label.config(text=repo_text)
        if self.issues_info_label:
            self.issues_info_label.config(text=issues_text)
        self._update_repo_hint()

    def _on_repo_path_value_changed(self, *args) -> None:
        if self._repo_path_trace_guard:
            return
        self._repo_path_trace_guard = True
        try:
            repo_text = self.repo_path_var.get().strip()
            if not repo_text:
                self.repo_hint_var.set("Select a repository path to see voice-file hints.")
                return
            repo_path = Path(repo_text).expanduser()
            try:
                repo_path = repo_path.resolve()
            except Exception:
                pass
            candidate = repo_path / ".voice" / "voice-issues.md"
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            new_path = str(resolved)
            if self.issues_path_var.get() != new_path:
                self.issues_path_var.set(new_path)
            self._refresh_static_info()
        finally:
            self._repo_path_trace_guard = False

    def _update_repo_hint(self) -> None:
        if not self.repo_hint_label:
            return
        repo_text = self.repo_path_var.get().strip()
        issues_text = self.issues_path_var.get().strip()
        if not repo_text:
            self.repo_hint_var.set("Select a repository path to see voice-file hints.")
            return
        try:
            repo_path = Path(repo_text).expanduser().resolve()
        except Exception:
            self.repo_hint_var.set("The selected repository path is invalid.")
            return
        issues_path = Path(issues_text or "voice-issues.md").expanduser()
        if not issues_path.is_absolute():
            issues_path = (repo_path / issues_path).resolve()
        if issues_path.exists():
            self.repo_hint_var.set(f"Existing voice issues log detected at {issues_path}; using that file.")
        else:
            self.repo_hint_var.set(
                f"No voice issues log found at {issues_path}; click Create voice file to bootstrap `.voice/voice-issues.md`."
            )

    def _browse_repo_path(self) -> None:
        try:
            selected = filedialog.askdirectory(initialdir=str(self.repo_cfg.repo_path))
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Repo selection cancelled: {exc}")
            return
        if not selected:
            return
        self.repo_path_var.set(selected)
        if self.repo_combo:
            self.repo_combo.set(selected)
    def _load_repo_history(self) -> list[str]:
        try:
            if not REPO_HISTORY_PATH.exists():
                return []
            data = json.loads(REPO_HISTORY_PATH.read_text(encoding="utf-8"))
            history = []
            seen = set()
            for item in data.get("history", []):
                try:
                    path = str(Path(item).expanduser().resolve())
                except Exception:
                    continue
                if path not in seen:
                    seen.add(path)
                    history.append(path)
            return history[:REPO_HISTORY_LIMIT]
        except Exception:
            return []

    def _persist_repo_history(self) -> None:
        try:
            REPO_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPO_HISTORY_PATH.write_text(json.dumps({"history": self.repo_history}, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Could not persist repo history: {exc}")

    def _append_repo_history_md(self, repo_path: str) -> None:
        try:
            PAST_REPOS_MD.parent.mkdir(parents=True, exist_ok=True)
            entry = f"- {repo_path}"
            if PAST_REPOS_MD.exists():
                existing = [line.strip() for line in PAST_REPOS_MD.read_text(encoding="utf-8").splitlines() if line.strip()]
            else:
                existing = []
            if entry in existing:
                return
            with PAST_REPOS_MD.open("a", encoding="utf-8") as fh:
                if existing:
                    fh.write("\n")
                fh.write(entry)
                fh.write("\n")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Could not update past repo list: {exc}")

    def _record_repo_history(self, repo_path: Path) -> None:
        repo_str = str(repo_path)
        seen_before = repo_str in self.repo_history
        history = [repo_str] + [p for p in self.repo_history if p != repo_str]
        self.repo_history = history[:REPO_HISTORY_LIMIT]
        self._persist_repo_history()
        self._update_repo_combo_values(current_repo=repo_path)
        if not seen_before:
            self._append_repo_history_md(repo_str)

    def _update_repo_combo_values(self, current_repo: Path | None = None) -> None:
        combo = self.repo_combo
        if not combo:
            return
        values = list(self.repo_history)
        current = str(current_repo or self.repo_cfg.repo_path)
        if values and values[0] == current:
            combo_values = values
        else:
            combo_values = [current] + [v for v in values if v != current]
        combo["values"] = combo_values

    def _ensure_repo_voice_assets(self, repo_path: Path, issues_path: Path) -> None:
        try:
            issues_path.parent.mkdir(parents=True, exist_ok=True)
            IssueWriter(issues_path).ensure_file()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Failed to prepare issues file at {issues_path}: {exc}")
        try:
            voice_dir = repo_path / ".voice"
            voice_dir.mkdir(parents=True, exist_ok=True)
            if AGENT_VOICE_SOURCE.exists():
                target = voice_dir / AGENT_VOICE_SOURCE.name
                if not target.exists():
                    shutil.copy(AGENT_VOICE_SOURCE, target)
            if VOICE_WORKFLOW_SOURCE.exists():
                workflow_target = voice_dir / VOICE_WORKFLOW_SOURCE.name
                if not workflow_target.exists():
                    shutil.copy(VOICE_WORKFLOW_SOURCE, workflow_target)
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Failed to copy voice guidance into {repo_path}: {exc}")

    def _read_issue_entries(self) -> list[tuple[str, str]]:
        writer = IssueWriter(self.repo_cfg.issues_file)
        writer.ensure_file()
        lines = self.repo_cfg.issues_file.read_text(encoding="utf-8-sig").splitlines()
        entries: list[tuple[str, str]] = []
        current_state: str | None = None
        current_text: list[str] = []

        def flush_pending() -> None:
            nonlocal current_state, current_text
            if current_text:
                text = " ".join(t.strip() for t in current_text if t.strip()).strip()
                if text:
                    state = current_state or "[ ]"
                    entries.append((state, text))
            current_state = None
            current_text = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- [") or stripped.startswith("* ["):
                flush_pending()
                try:
                    state = stripped.split("]", 1)[0].split("[", 1)[1]
                    state = f"[{state}]"
                    body = stripped.split("]", 1)[1].strip()
                except Exception:
                    state = "[ ]"
                    body = stripped
                current_state = state
                current_text = [body]
            elif stripped == "":
                flush_pending()
            else:
                if not current_text:
                    current_state = "[ ]"
                current_text.append(stripped)
        flush_pending()
        return entries

    def _format_issue_lines(self, entries: list[tuple[str, str]]) -> list[str]:
        return [f"- {state} {text}" for state, text in entries]

    def _write_issue_entries(self, entries: list[tuple[str, str]]) -> None:
        lines = self._format_issue_lines(entries)
        text_out = "\n".join(lines)
        if text_out and not text_out.endswith("\n"):
            text_out += "\n"
        self.repo_cfg.issues_file.write_text(text_out, encoding="utf-8")

    @staticmethod
    def _is_pending_state(state: str) -> bool:
        return state.strip().lower() == "[ ]"

    @staticmethod
    def _deduplicate_issues(issues: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for issue in issues:
            normalized = issue.strip().lower()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(issue)
        return unique

    def _sanitize_issues_file(self) -> list[str]:
        """Normalize the issues file: collapse wrapped lines into bullets, convert stray text into checklist items."""
        entries = self._read_issue_entries()
        self._write_issue_entries(entries)
        return self._format_issue_lines(entries)

    def _remove_duplicate_issues(self) -> None:
        try:
            entries = self._read_issue_entries()
            unique_entries: list[tuple[str, str]] = []
            seen: set[str] = set()
            duplicates = 0
            for state, text in entries:
                normalized = text.strip().lower()
                if not normalized:
                    continue
                if normalized in seen:
                    duplicates += 1
                    continue
                seen.add(normalized)
                unique_entries.append((state, text))
            if duplicates == 0:
                self._log("[info] No duplicate issues found.")
                return
            confirm = messagebox.askyesno(
                "Remove duplicates", f"Found {duplicates} duplicate issue(s). Remove them from the current repo?"
            )
            if not confirm:
                return
            self._write_issue_entries(unique_entries)
            self._refresh_issue_list()
            self._log(f"[ok] Removed {duplicates} duplicate issue(s) from {self.repo_cfg.issues_file}")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to deduplicate issues: {exc}")

    def refresh_devices(self) -> None:
        self.device_list = list_input_devices(self.config.device_allowlist, self.config.device_denylist)
        combo = self.device_combo
        if combo:
            combo["values"] = [f"{d['id']}: {d['name']}" for d in self.device_list]
        if self.device_list:
            if combo:
                combo.current(0)
            self.selected_device_id = self.device_list[0]["id"]
            self.selected_device_name = self.device_list[0]["name"]
            self.selected_device_hostapi = self.device_list[0].get("hostapi")
            self._log("[info] Devices refreshed.")
        else:
            self.selected_device_id = None
            self.selected_device_name = "None"
            self.selected_device_hostapi = None
            self._log("[warn] No input devices found.")
        if self.mic_tester.is_testing():
            self.mic_tester.stop()
            self._log("[info] Mic test stopped due to device refresh.")

    def on_device_change(self, event=None) -> None:  # type: ignore[override]
        if not self.device_combo:
            return
        sel = self.device_combo.get()
        if sel:
            self.selected_device_id = int(sel.split(":")[0])
            self.selected_device_name = sel.split(":", 1)[1].strip()
            # Find matching device entry to update hostapi
            for d in self.device_list:
                if d["id"] == self.selected_device_id:
                    self.selected_device_hostapi = d.get("hostapi")
                    break
            self._log(f"[info] Selected device {sel}")
            if self.mic_tester.is_testing():
                self.mic_tester.stop()
                self._log("[info] Mic test stopped; re-run on the new device.")

    def start_recording(self) -> None:
        if self.mic_tester.is_testing():
            self._log("[error] Stop mic test before recording.")
            return
        if not self.selected_device_id and self.selected_device_id != 0:
            self._log("[error] No input device selected.")
            return
        try:
            tmp_dir = ROOT / ".tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", prefix="voice_gui_", dir=tmp_dir, delete=False)
            tmp_path = Path(tmp.name)
            tmp.close()
            self.tmp_wav = tmp_path
            self.waterfall_history = []
            self._start_recorder_with_fallbacks()
            if self.start_btn:
                self.start_btn.config(state=DISABLED)
            if self.stop_btn:
                self.stop_btn.config(state=NORMAL)
            if self.status_var:
                self.status_var.config(text="Recording...")
            if self.live_indicator:
                self.live_indicator.config(text="Mic LIVE", background="#c1121f", foreground="white")
            if self.hotkey_registered:
                self._set_hotkey_indicator("Recording (hotkey ready)", "#c1121f")
            self._log("[info] Recording... press Stop & Transcribe when done.")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to start recording: {exc}")
            if self.status_var:
                self.status_var.config(text="Error")
            self._remove_tmp_wav()
            self.recorder = None
            self.tmp_wav = None

    def stop_recording(self) -> None:
        if not self.recorder or not self.recorder.is_recording():
            return
        keep_path = None
        try:
            self.recorder.stop()
            if self.status_var:
                self.status_var.config(text="Transcribing...")
            self._log("[info] Recording stopped. Transcribing...")
            if not self.tmp_wav:
                raise RuntimeError("Temp WAV missing.")
            keep_path = self.tmp_wav
            dur = validate_recording(self.tmp_wav)
            self._log(f"[info] Using recording {self.tmp_wav.name} ({dur:.2f}s)")
            transcript = transcribe_with_whisper_cpp(self.tmp_wav, self.config)
            self._send_transcript_to_server(transcript)
            issues = split_issues(transcript, self.config.next_issue_phrases, self.config.stop_phrases)
            unique_issues = self._deduplicate_issues(issues)
            if len(unique_issues) != len(issues):
                self._log(f"[info] Dropped {len(issues) - len(unique_issues)} duplicate issue(s).")
            issues = unique_issues
            if not issues:
                self._log("[info] No issues detected.")
            else:
                writer = IssueWriter(self.repo_cfg.issues_file)
                append_issues_incremental(writer, issues)
                self._log(f"[ok] Appended {len(issues)} issue(s) to {self.repo_cfg.issues_file}")
                self._refresh_issue_list()
            if self.status_var:
                self.status_var.config(text="Ready")
            if self.live_indicator:
                self.live_indicator.config(text="Idle", background="#666666", foreground="white")
            if self.hotkey_registered:
                self._set_hotkey_indicator(f"Hotkey ready: {self.config.hotkey_toggle}", "#2274a5")
            # Only delete after successful transcription path
            if self.tmp_wav:
                try:
                    self.tmp_wav.unlink()
                    self._log(f"[info] Deleted temp recording {self.tmp_wav.name}")
                except OSError:
                    pass
                keep_path = None
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] {exc}")
            if keep_path:
                self._log(f"[warn] Keeping temp WAV for inspection: {keep_path}")
            if self.status_var:
                self.status_var.config(text="Error")
        finally:
            if keep_path is None:
                self._remove_tmp_wav()
            self._cleanup_tmp_dir(max_age_seconds=5)
            self.tmp_wav = None
            self.recorder = None
            self.waterfall_history = []
            if self.start_btn:
                self.start_btn.config(state=NORMAL)
            if self.stop_btn:
                self.stop_btn.config(state=DISABLED)

    def _start_recorder_with_fallbacks(self) -> None:
        # Find working sample rates via check_input_settings, then try to start with each (and channels fallback)
        def similar_devices(name: str, current_id: int | None) -> list[tuple[int, str, int | None]]:
            norm = normalize_name(name)
            matches: list[tuple[int, str, int | None]] = []
            hostapis = sd.query_hostapis()
            for idx, dev in enumerate(sd.query_devices()):
                if dev.get("max_input_channels", 0) <= 0:
                    continue
                if idx == current_id:
                    continue
                if NOISY_NAMES.search(dev.get("name", "")):
                    continue
                priority = hostapi_priority(dev.get("hostapi"), hostapis)
                if priority >= 3:
                    continue
                other_norm = normalize_name(dev.get("name", ""))
                if norm in other_norm or other_norm in norm:
                    matches.append((idx, dev.get("name", ""), dev.get("hostapi")))
            # Prefer higher-priority hostapis for fallbacks too
            matches.sort(key=lambda x: hostapi_priority(x[2], hostapis))
            return matches

        devices_to_try: list[tuple[int | None, str, int | None]] = []
        devices_to_try.append((self.selected_device_id, self.selected_device_name, self.selected_device_hostapi))
        devices_to_try.extend(similar_devices(self.selected_device_name, self.selected_device_id))

        last_exc: Exception | None = None
        for dev_id, dev_name, dev_hostapi in devices_to_try:
            override_sr = self.config.stt_input_samplerate
            default_sr = get_device_samplerate(dev_id, fallback=44100)
            primary_rates: list[int] = []
            fallback_rates: list[int] = []
            seen_sr: set[int] = set()

            def add_rate(target: list[int], value) -> None:
                try:
                    sr_val = int(value)
                except Exception:
                    return
                if sr_val > 0 and sr_val not in seen_sr:
                    target.append(sr_val)
                    seen_sr.add(sr_val)

            # Always start with the device default samplerate; only after it fails do we try others.
            add_rate(primary_rates, default_sr)
            add_rate(fallback_rates, override_sr)
            for sr in (48000, 44100, 32000):
                add_rate(fallback_rates, sr)

            if not primary_rates:
                last_exc = RuntimeError(f"No valid samplerate for device {dev_name}")
                continue

            ch_override = self.config.stt_input_channels
            ch_candidates = [ch_override] if ch_override else [1, get_device_channels(dev_id, fallback=1)]
            ch_candidates = [c for c in ch_candidates if c > 0]
            extras: list[object | None] = []
            try:
                hostapis = sd.query_hostapis()
                if dev_hostapi is not None and dev_hostapi < len(hostapis):
                    hostapi_name = hostapis[dev_hostapi].get("name", "").lower()
                    if "wasapi" in hostapi_name:
                        # Prefer WASAPI shared first; fall back to default only if needed.
                        extras.append(sd.WasapiSettings(exclusive=False))
            except Exception:
                pass
            extras.append(None)

            if dev_id != self.selected_device_id:
                self._log(f"[info] Trying fallback device '{dev_name}' (id {dev_id})")

            def try_rates(rates: list[int]) -> tuple[bool, bool]:
                """Return (success, host_error); set last_exc on failure."""
                nonlocal last_exc
                host_error = False
                for sr in rates:
                    for ch in ch_candidates:
                        for idx_extra, extra in enumerate(extras):
                            try:
                                rec = Recorder(device=dev_id, samplerate=sr, channels=ch)
                                rec.start(self.tmp_wav, extra_settings=extra)
                                self.recorder = rec
                                mode = "wasapi-shared" if extra else "default"
                                self._log(f"[info] Recording with {mode} samplerate {sr} Hz, channels={ch}, device='{dev_name}'.")
                                if dev_id != self.selected_device_id:
                                    # Promote the working fallback as the current selection for subsequent runs.
                                    self.selected_device_id = dev_id
                                    self.selected_device_name = dev_name
                                    self.selected_device_hostapi = dev_hostapi
                                    # If not already in the dropdown, add it.
                                    if all(d.get("id") != dev_id for d in self.device_list):
                                        self.device_list.append(
                                            {
                                                "id": dev_id,
                                                "name": dev_name,
                                                "max_input_channels": get_device_channels(dev_id, fallback=1),
                                                "hostapi": dev_hostapi,
                                                "hostapi_priority": hostapi_priority(dev_hostapi),
                                            }
                                        )
                                        self.device_combo["values"] = [f"{d['id']}: {d['name']}" for d in self.device_list]
                                    for i, d in enumerate(self.device_list):
                                        if d.get("id") == dev_id:
                                            self.device_combo.current(i)
                                            break
                                    self.device_label.config(text=f"Selected: {self.selected_device_name}")
                                return True, host_error
                            except Exception as exc:  # noqa: BLE001
                                last_exc = exc
                                self._log(f"[warn] Failed at {sr} Hz, ch={ch}, extra={bool(extra)} on '{dev_name}': {exc}")
                                msg = str(exc).lower()
                                if "-9999" in msg or "usbterminalguid" in msg or "unanticipated host error" in msg:
                                    # Host-level failure: stop trying other rates on this device, move to next device.
                                    host_error = True
                                    # If there's another extra_settings to try (e.g., WASAPI shared), attempt it before bailing.
                                    if idx_extra < len(extras) - 1:
                                        continue
                                    return False, host_error
                                continue
                return False, host_error

            # First, try only the primary (device-default) rate(s)
            success, host_error = try_rates(primary_rates)
            if success:
                return
            if host_error:
                continue
            # Only if primary fails without a hard host error, try fallback rates
            if fallback_rates:
                success, host_error = try_rates(fallback_rates)
                if success:
                    return
                if host_error:
                    continue

        raise RuntimeError(f"Failed to start recorder at any checked samplerate. Last error: {last_exc}")


    def _poll_level(self) -> None:
        test_btn = self.test_btn
        cta_btn = self.test_cta_btn
        canvas = self.test_canvas
        if self.mic_tester.is_testing():
            level = self.mic_tester.level
            self._push_waterfall(level)
            self._draw_test_history(self.waterfall_history, threshold=self.mic_tester.threshold)
            if test_btn:
                test_btn.config(text="Stop Test")
            if cta_btn:
                cta_btn.config(text="Stop Test")
            if self.waterfall_status:
                self.waterfall_status.config(text=f"Waterfall: mic test ({self.selected_device_name})")
        elif self.recorder and self.recorder.is_recording():
            level = self.recorder.level
            self._push_waterfall(level)
            self._draw_test_history(self.waterfall_history)
            if test_btn:
                test_btn.config(text="Test Selected Mic")
            if cta_btn:
                cta_btn.config(text="Test Selected Mic")
            if self.waterfall_status:
                self.waterfall_status.config(text="Waterfall: recording")
        else:
            if canvas:
                canvas.delete("all")
            if test_btn:
                test_btn.config(text="Test Selected Mic")
            if cta_btn:
                cta_btn.config(text="Test Selected Mic")
            self.waterfall_history = []
            if self.waterfall_status:
                self.waterfall_status.config(text="Waterfall: idle")
        self.root.after(100, self._poll_level)

    def _push_waterfall(self, level: float) -> None:
        self.waterfall_history.append(level)
        self.waterfall_history = self.waterfall_history[-WATERFALL_WINDOW:]

    def _draw_test_history(self, history: list[float], threshold: float | None = None) -> None:
        canvas = self.test_canvas
        if not canvas:
            return
        palette = self._current_palette()
        canvas.delete("all")
        if not history:
            return
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or 80)
        bar_width = max(2, width // max(1, len(history)))
        max_bars = max(1, width // bar_width)
        canvas.create_rectangle(0, 0, width, height, fill=palette["canvas_bg"], outline="")
        for i, level in enumerate(history[-max_bars:]):
            x0 = i * bar_width
            x1 = x0 + bar_width - 1
            bar_height = int(max(0.0, min(level, 1.0)) * height)
            y0 = height - bar_height
            y1 = height
            color = self._waterfall_color(level, palette)
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline=color)
            canvas.create_line(x0, y0, x1 + 1, y0, fill=palette["border"], width=1)
        for idx in range(1, 4):
            y = height - idx * (height / 4)
            canvas.create_line(0, y, width, y, fill=palette["border"], width=1)
        if threshold is not None:
            th_val = max(0.0, min(threshold, 1.0))
            th_y = height - int(th_val * height)
            canvas.create_line(0, th_y, width, th_y, fill=palette["accent"], dash=(4, 4), width=2)
        canvas.create_line(0, height - 1, width, height - 1, fill=palette["accent"], width=2)

    def run(self) -> None:
        self.root.mainloop()

    def _register_hotkeys(self) -> None:
        if not keyboard:
            self._log("[warn] Global hotkeys unavailable (keyboard module not loaded).")
            self._set_hotkey_indicator("Hotkey unavailable", "#8b0000")
            return
        combo = self.config.hotkey_toggle
        if hotkey_conflicts(combo):
            self._log(f"[warn] Hotkey '{combo}' may conflict with system combos.")
        try:
            keyboard.add_hotkey(combo, lambda: self._hotkey_toggle())
            self.hotkey_registered = True
            self._set_hotkey_indicator(f"Hotkey ready: {combo}", "#2274a5")
            self._log(f"[info] Hotkey registered: {combo} (toggle record)")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Failed to register hotkey: {exc}")
            self._set_hotkey_indicator("Hotkey unavailable", "#666666")

    def _hotkey_toggle(self) -> None:
        # Avoid conflicts with mic test
        if self.mic_tester.is_testing():
            self._log("[error] Stop mic test before recording.")
            return
        self._set_hotkey_indicator("Hotkey pressed", "#c1121f")
        if self.recorder and self.recorder.is_recording():
            self.stop_recording()
            self._set_hotkey_indicator(f"Hotkey ready: {self.config.hotkey_toggle}", "#2274a5")
        else:
            self.start_recording()
            self._set_hotkey_indicator("Recording (hotkey)", "#c1121f")

    def _set_hotkey_indicator(self, text: str, bg: str = "#666666") -> None:
        try:
            if self.hotkey_indicator:
                self.hotkey_indicator.config(text=text, background=bg, foreground="white")
        except Exception:
            pass

    def _ensure_keyboard_module(self) -> None:
        global keyboard
        if keyboard:
            return
        try:
            import keyboard as kb  # type: ignore

            keyboard = kb
            return
        except Exception:
            pass
        try:
            self._log("[info] Installing 'keyboard' for hotkeys...")
            subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "keyboard"], check=True)
            import keyboard as kb  # type: ignore

            keyboard = kb
            self._log("[ok] Installed 'keyboard'; hotkeys enabled.")
        except Exception as exc:
            keyboard = None
            self._log(f"[warn] Failed to install 'keyboard'; hotkeys disabled: {exc}")

    def _cleanup(self) -> None:
        try:
            if self.mic_tester.is_testing():
                self.mic_tester.stop()
        except Exception:
            pass
        try:
            if self.recorder and self.recorder.is_recording():
                self.recorder.stop()
        except Exception:
            pass
        try:
            if keyboard:
                keyboard.unhook_all()
        except Exception:
            pass
        try:
            if self.transcript_listener:
                self.transcript_listener.stop()
        except Exception:
            pass
        try:
            self._remove_tmp_wav()
        except Exception:
            pass
        try:
            self._cleanup_tmp_dir()
        except Exception:
            pass

    def _on_close(self) -> None:
        self._cleanup()
        self.root.destroy()

    def toggle_mic_test(self) -> None:
        if self.mic_tester.is_testing():
            self.mic_tester.stop()
            self._log("[info] Mic test stopped.")
            self._set_hotkey_indicator(f"Hotkey ready: {self.config.hotkey_toggle}", "#2274a5" if self.hotkey_registered else "#666666")
            return
        if self.recorder and self.recorder.is_recording():
            self._log("[error] Stop recording before testing the mic.")
            return
        try:
            sr = get_device_samplerate(self.selected_device_id, fallback=16000)
            ch = get_device_channels(self.selected_device_id, fallback=1)
            self.waterfall_history = []
            self.mic_tester.start(self.selected_device_id, samplerate=sr, channels=ch)
            self._log(f"[info] Mic test started on '{self.selected_device_name}'. Speak normally for ~2 seconds.")
            self._set_hotkey_indicator("Hotkey paused (mic test)", "#666666")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to start mic test (device={self.selected_device_name}): {exc}")

    def _remove_tmp_wav(self) -> None:
        if self.tmp_wav and self.tmp_wav.exists():
            try:
                self.tmp_wav.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _cleanup_tmp_dir(self, max_age_seconds: int = 300) -> None:
        tmp_dir = ROOT / ".tmp"
        if not tmp_dir.exists():
            return
        now = time.time()
        for wav in tmp_dir.glob("voice_gui_*.wav"):
            try:
                if wav.stat().st_mtime < now - max_age_seconds:
                    wav.unlink()
            except OSError:
                continue


def main() -> int:
    try:
        app = VoiceGUI()
        app.run()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
