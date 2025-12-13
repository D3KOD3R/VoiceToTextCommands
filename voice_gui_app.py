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
from tkinter import BOTH, DISABLED, END, LEFT, NORMAL, RIGHT, Canvas, Listbox, StringVar, BooleanVar, Tk, messagebox, ttk
from tkinter import scrolledtext

import numpy as np
import sounddevice as sd

try:
    import keyboard  # type: ignore
except Exception:  # noqa: BLE001
    keyboard = None

# Ensure repo root is importable regardless of CWD
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_issue_daemon import (
    ConfigLoader,
    DEFAULT_CONFIG_PATH,
    IssueWriter,
    WhisperCppProvider,
    append_issues_incremental,
    split_issues,
)


NOISY_NAMES = re.compile(r"(hands[- ]?free|hf audio|bthhfenum|telephony|communications|loopback|primary sound capture)", re.I)
WATERFALL_WINDOW = 50  # number of samples to display (~5s at 10 Hz poll)
WAIT_STATE_CHAR = "~"


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
        self.status_var = ttk.Label(self.controls_frame, text="Ready")
        self.level_canvas = Canvas(self.controls_frame, width=40, height=80, bg="#1e1e1e", highlightthickness=0)
        self.log_widget: scrolledtext.ScrolledText | None = None
        self.live_indicator = ttk.Label(self.controls_frame, text="Idle", foreground="white", background="#666666", padding=6)
        self.start_btn = ttk.Button(self.controls_frame, text="Start Recording", command=self.start_recording)
        self.stop_btn = ttk.Button(self.controls_frame, text="Stop & Transcribe", command=self.stop_recording, state=DISABLED)
        self.test_cta_btn = ttk.Button(self.controls_frame, text="Test Selected Mic", command=self.toggle_mic_test)
        self.test_btn = ttk.Button(self.controls_frame, text="Test Selected Mic", command=self.toggle_mic_test)
        self.test_canvas = Canvas(self.controls_frame, height=80, bg="#1e1e1e", highlightthickness=0)
        self.hotkey_indicator = None
        self.hotkey_registered = False
        self.device_label = None
        self.issue_listbox: Listbox | None = None
        self.issue_listbox_done: Listbox | None = None
        self.issue_listbox_wait: Listbox | None = None
        self.issue_entries_pending: list[tuple[list[int], str]] = []
        self.issue_entries_done: list[tuple[list[int], str]] = []
        self.issue_entries_wait: list[tuple[list[int], str]] = []
        self.pending_row_map: list[int] = []
        self.done_row_map: list[int] = []
        self.wait_row_map: list[int] = []
        self._listbox_select_guard = False
        self.waterfall_history: list[float] = []
        self.skip_delete_confirm = BooleanVar(value=False)
        self._drag_info: dict | None = None
        self.waterfall_status: ttk.Label | None = None
        self.transcript_widget: scrolledtext.ScrolledText | None = None
        self.transcript_listener: TranscriptListener | None = None
        self.info_label: ttk.Label | None = None
        self.hotkey_toggle_var = StringVar(value=self.config.hotkey_toggle)
        self.hotkey_quit_var = StringVar(value=self.config.hotkey_quit)
        self.repo_path_var = StringVar(value=str(self.repo_cfg.repo_path))
        self.issues_path_var = StringVar(value=str(self.repo_cfg.issues_file))
        self.device_combo = ttk.Combobox(
            self.controls_frame,
            values=[f"{d['id']}: {d['name']}" for d in self.device_list],
            state="readonly",
            width=45,  # just enough to show the selected device name
        )

        self._build_layout()
        self._ensure_keyboard_module()
        self.root.after(100, self._poll_level)
        self._register_hotkeys()
        self._refresh_issue_list()
        self._start_transcript_listener()
        self._cleanup_tmp_dir()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # Controls block (everything above the log)
        self.controls_frame.pack(fill=BOTH, expand=False)

        header = ttk.Frame(self.controls_frame)
        header.pack(fill=BOTH, **pad)
        left_header = ttk.Frame(header)
        left_header.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(left_header, text="Voice Issue Recorder", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        info = (
            f"Repo: {self.repo_cfg.repo_path}\n"
            f"Issues: {self.repo_cfg.issues_file}\n"
            f"Hotkeys (daemon): start/stop {self.config.hotkey_toggle}, quit {self.config.hotkey_quit}"
        )
        self.info_label = ttk.Label(self.controls_frame, text=info, justify=LEFT)

        issues_panel = ttk.Frame(header, padding=(8, 0, 0, 0))
        issues_panel.pack(side=RIGHT, fill=BOTH, expand=True)
        move_all_row = ttk.Frame(issues_panel)
        move_all_row.pack(fill=BOTH, expand=False, pady=(0, 4))
        ttk.Label(move_all_row, text="Move selected to:").pack(side=LEFT, padx=(0, 6))
        ttk.Button(move_all_row, text="Pending", command=self._mark_any_pending).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Completed", command=self._mark_any_completed).pack(side=LEFT, padx=(0, 4))
        ttk.Button(move_all_row, text="Waitlist", command=self._mark_any_waitlist).pack(side=LEFT, padx=(0, 4))

        lists_row = ttk.Frame(issues_panel)
        lists_row.pack(fill=BOTH, expand=True)

        pending_frame = ttk.Frame(lists_row, padding=(0, 0, 4, 0))
        pending_frame.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(pending_frame, text="Pending issues:").pack(anchor="w")
        self.issue_listbox = Listbox(
            pending_frame,
            height=16,
            width=40,
            selectmode="extended",
            exportselection=False,
        )
        self.issue_listbox.pack(fill=BOTH, expand=True, pady=(2, 4))
        self.issue_listbox.bind("<<ListboxSelect>>", self._on_pending_select)
        self.issue_listbox.bind("<ButtonPress-1>", lambda e: self._start_drag(e, "pending"))
        self.issue_listbox.bind("<ButtonRelease-1>", lambda e: self._finish_drag(e, "pending"))
        pending_btn_row = ttk.Frame(pending_frame)
        pending_btn_row.pack(fill=BOTH, expand=False, pady=(0, 2))
        ttk.Button(pending_btn_row, text="Select all", command=self._select_all_pending).pack(side=LEFT, padx=(0, 4))
        ttk.Button(pending_btn_row, text="Delete selected", command=self._delete_selected_pending).pack(side=LEFT)

        done_frame = ttk.Frame(lists_row, padding=(4, 0, 0, 0))
        done_frame.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(done_frame, text="Completed issues:").pack(anchor="w")
        self.issue_listbox_done = Listbox(
            done_frame,
            height=16,
            width=40,
            selectmode="extended",
            exportselection=False,
        )
        self.issue_listbox_done.pack(fill=BOTH, expand=True, pady=(2, 4))
        self.issue_listbox_done.bind("<<ListboxSelect>>", self._on_done_select)
        self.issue_listbox_done.bind("<ButtonPress-1>", lambda e: self._start_drag(e, "done"))
        self.issue_listbox_done.bind("<ButtonRelease-1>", lambda e: self._finish_drag(e, "done"))
        done_btn_row = ttk.Frame(done_frame)
        done_btn_row.pack(fill=BOTH, expand=False, pady=(0, 2))
        ttk.Button(done_btn_row, text="Select all", command=self._select_all_done).pack(side=LEFT, padx=(0, 4))
        ttk.Button(done_btn_row, text="Delete selected", command=self._delete_selected_done).pack(side=LEFT)

        wait_frame = ttk.Frame(lists_row, padding=(4, 0, 0, 0))
        wait_frame.pack(side=LEFT, fill=BOTH, expand=True)
        ttk.Label(wait_frame, text="Waitlist issues:").pack(anchor="w")
        self.issue_listbox_wait = Listbox(
            wait_frame,
            height=16,
            width=40,
            selectmode="extended",
            exportselection=False,
        )
        self.issue_listbox_wait.pack(fill=BOTH, expand=True, pady=(2, 4))
        self.issue_listbox_wait.bind("<<ListboxSelect>>", lambda e: self._on_wait_select())
        self.issue_listbox_wait.bind("<ButtonPress-1>", lambda e: self._start_drag(e, "wait"))
        self.issue_listbox_wait.bind("<ButtonRelease-1>", lambda e: self._finish_drag(e, "wait"))
        wait_btn_row = ttk.Frame(wait_frame)
        wait_btn_row.pack(fill=BOTH, expand=False, pady=(0, 2))
        ttk.Button(wait_btn_row, text="Select all", command=lambda: self._select_all_list(self.issue_listbox_wait)).pack(
            side=LEFT, padx=(0, 4)
        )
        ttk.Button(wait_btn_row, text="Delete selected", command=self._delete_selected_wait).pack(side=LEFT)

        ttk.Checkbutton(
            issues_panel,
            text="Skip delete confirmation",
            variable=self.skip_delete_confirm,
        ).pack(anchor="w", pady=(2, 0))

        self.test_cta_btn.pack(in_=self.controls_frame, fill=BOTH, padx=10, pady=(4, 4))

        hk_row = ttk.Frame(self.controls_frame, padding=(6, 2, 6, 2))
        hk_row.pack(fill=BOTH, **pad)
        ttk.Label(hk_row, text="Hotkey toggle:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.hotkey_toggle_var, width=16).pack(side=LEFT, padx=(0, 10))
        ttk.Label(hk_row, text="Hotkey quit:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(hk_row, textvariable=self.hotkey_quit_var, width=16).pack(side=LEFT, padx=(0, 10))

        path_row = ttk.Frame(self.controls_frame, padding=(6, 2, 6, 2))
        path_row.pack(fill=BOTH, **pad)
        ttk.Label(path_row, text="Repo path:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(path_row, textvariable=self.repo_path_var, width=70).pack(side=LEFT, padx=(0, 10))

        issue_path_row = ttk.Frame(self.controls_frame, padding=(6, 2, 6, 2))
        issue_path_row.pack(fill=BOTH, **pad)
        ttk.Label(issue_path_row, text="Issues file:").pack(side=LEFT, padx=(0, 6))
        ttk.Entry(issue_path_row, textvariable=self.issues_path_var, width=70).pack(side=LEFT, padx=(0, 10))
        ttk.Button(issue_path_row, text="Apply settings", command=self._apply_settings).pack(side=LEFT)

        device_row = ttk.Frame(self.controls_frame, padding=(2, 1, 2, 1))
        device_row.pack(fill="x", expand=False, padx=8, pady=(0, 4))
        ttk.Label(device_row, text="Input device:").pack(side=LEFT, padx=(0, 6))
        if self.device_list:
            self.device_combo.current(0)
            self.device_combo.bind("<<ComboboxSelected>>", self.on_device_change)
        self.device_combo.config(width=30)
        self.device_combo.pack(side=LEFT, padx=(4, 6), fill="x", expand=True)
        ttk.Button(device_row, text="Refresh", command=self.refresh_devices).pack(side=LEFT, padx=(0, 6))
        self.live_indicator.pack(in_=device_row, side=LEFT, padx=(4, 0))

        test_row = ttk.Frame(self.controls_frame, padding=(6, 4, 6, 4))
        test_row.pack(fill=BOTH, **pad)
        self.test_btn.pack(in_=test_row, side=LEFT, padx=(0, 10), pady=2)

        meter_row = ttk.Frame(self.controls_frame)
        meter_row.pack(fill=BOTH, padx=10, pady=(2, 2))
        self.level_canvas.pack(in_=meter_row, side=LEFT, padx=(0, 0))

        wf_header = ttk.Frame(self.controls_frame)
        wf_header.pack(fill=BOTH, padx=10, pady=(4, 0))
        ttk.Label(wf_header, text="Microphone waterfall").pack(side=LEFT)
        self.waterfall_status = ttk.Label(wf_header, text="Waterfall: idle")
        self.waterfall_status.pack(side=LEFT, padx=(8, 0))
        self.test_canvas.config(height=280)
        self.test_canvas.pack(in_=self.controls_frame, fill=BOTH, expand=True, padx=10, pady=(0, 5))

        info_row = ttk.Frame(self.controls_frame)
        info_row.pack(fill=BOTH, padx=10, pady=(0, 6))
        self.info_label.pack(in_=info_row, anchor="w")

        transcript_frame = ttk.Frame(self.controls_frame, padding=(6, 2, 6, 2))
        transcript_frame.pack(fill=BOTH, expand=False, padx=6, pady=(2, 4))
        ttk.Label(transcript_frame, text="Speech output (from server):").pack(anchor="w")
        self.transcript_widget = scrolledtext.ScrolledText(transcript_frame, height=5, state=DISABLED)
        self.transcript_widget.pack(fill=BOTH, expand=True, pady=(2, 0))

        btn_row = ttk.Frame(self.controls_frame)
        btn_row.pack(fill=BOTH, **pad)
        self.start_btn.pack(in_=btn_row, side=LEFT, expand=True, fill=BOTH, padx=(0, 5))
        self.stop_btn.pack(in_=btn_row, side=RIGHT, expand=True, fill=BOTH, padx=(5, 0))

        self.status_var.pack(in_=self.controls_frame, anchor="w", **pad)

        # Log block
        log_frame = ttk.Frame(self.root)
        log_frame.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))
        ttk.Label(log_frame, text="Log:").pack(anchor="w")
        self.log_widget = scrolledtext.ScrolledText(log_frame, height=8, state=DISABLED)
        self.log_widget.pack(fill=BOTH, expand=True, pady=(2, 0))
        self._log("Ready. Select mic, use 'Test Selected Mic' to monitor, then Start Recording.")

    def _log(self, msg: str) -> None:
        if not self.log_widget:
            return
        self.log_widget.config(state=NORMAL)
        self.log_widget.insert(END, msg + "\n")
        self.log_widget.see(END)
        self.log_widget.config(state=DISABLED)

    def _append_transcript(self, text: str) -> None:
        if not self.transcript_widget or not text:
            return
        self.transcript_widget.config(state=NORMAL)
        self.transcript_widget.insert(END, text.strip() + "\n")
        self.transcript_widget.see(END)
        self.transcript_widget.config(state=DISABLED)

    def _handle_transcript_message(self, text: str) -> None:
        if not text:
            return
        self.root.after(0, lambda: self._append_transcript(text))

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
        except Exception as exc:  # noqa: BLE001
            self._log(f"[warn] Unable to read issues file {self.repo_cfg.issues_file}: {exc}")

    def _populate_issue_listbox(self, listbox: Listbox, entries: list[tuple[list[int], str]], row_map: list[int]) -> None:
        wrap_width = 70
        for idx, (_, text) in enumerate(entries):
            wrapped = textwrap.wrap(text, width=wrap_width) or [text]
            for j, line in enumerate(wrapped):
                display = line if j == 0 else f"   {line}"
                listbox.insert(END, display)
                row_map.append(idx)

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
        repo_raw = self.repo_path_var.get().strip()
        issues_raw = self.issues_path_var.get().strip()
        try:
            repo_path = Path(repo_raw).expanduser().resolve()
            issues_path = Path(issues_raw).expanduser()
            if not issues_path.is_absolute():
                issues_path = (repo_path / issues_path).resolve()
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Invalid paths: {exc}")
            return

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
            info = (
                f"Repo: {self.repo_cfg.repo_path}\n"
                f"Issues: {self.repo_cfg.issues_file}\n"
                f"Hotkeys (daemon): start/stop {self.config.hotkey_toggle}, quit {self.config.hotkey_quit}"
            )
            if self.info_label:
                self.info_label.config(text=info)
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
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to apply settings: {exc}")

    def _sanitize_issues_file(self) -> list[str]:
        """Normalize the issues file: collapse wrapped lines into bullets, convert stray text into checklist items."""
        writer = IssueWriter(self.repo_cfg.issues_file)
        writer.ensure_file()
        lines = self.repo_cfg.issues_file.read_text(encoding="utf-8-sig").splitlines()
        entries: list[tuple[str, str]] = []  # (state, text)
        current_state = None
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
                # Extract state and body
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

        new_lines = [f"- {state} {text}" for state, text in entries]
        text_out = "\n".join(new_lines)
        if text_out and not text_out.endswith("\n"):
            text_out += "\n"
        self.repo_cfg.issues_file.write_text(text_out, encoding="utf-8")
        return new_lines

    def refresh_devices(self) -> None:
        self.device_list = list_input_devices(self.config.device_allowlist, self.config.device_denylist)
        self.device_combo["values"] = [f"{d['id']}: {d['name']}" for d in self.device_list]
        if self.device_list:
            self.device_combo.current(0)
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
            self.start_btn.config(state=DISABLED)
            self.stop_btn.config(state=NORMAL)
            self.status_var.config(text="Recording...")
            self.live_indicator.config(text="Mic LIVE", background="#c1121f", foreground="white")
            if self.hotkey_registered:
                self._set_hotkey_indicator("Recording (hotkey ready)", "#c1121f")
            self._log("[info] Recording... press Stop & Transcribe when done.")
        except Exception as exc:  # noqa: BLE001
            self._log(f"[error] Failed to start recording: {exc}")
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
            if not issues:
                self._log("[info] No issues detected.")
            else:
                writer = IssueWriter(self.repo_cfg.issues_file)
                append_issues_incremental(writer, issues)
                self._log(f"[ok] Appended {len(issues)} issue(s) to {self.repo_cfg.issues_file}")
                self._refresh_issue_list()
            self.status_var.config(text="Ready")
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
            self.status_var.config(text="Error")
        finally:
            if keep_path is None:
                self._remove_tmp_wav()
            self._cleanup_tmp_dir(max_age_seconds=5)
            self.tmp_wav = None
            self.recorder = None
            self.waterfall_history = []
            self.start_btn.config(state=NORMAL)
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
        if self.mic_tester.is_testing():
            level = self.mic_tester.level
            self._draw_level_bar(level)
            self._push_waterfall(level)
            self._draw_test_history(self.waterfall_history, threshold=self.mic_tester.threshold)
            self.test_btn.config(text="Stop Test")
            self.test_cta_btn.config(text="Stop Test")
            if self.waterfall_status:
                self.waterfall_status.config(text=f"Waterfall: mic test ({self.selected_device_name})")
        elif self.recorder and self.recorder.is_recording():
            level = self.recorder.level
            self._draw_level_bar(level)
            self._push_waterfall(level)
            self._draw_test_history(self.waterfall_history)
            self.test_btn.config(text="Test Selected Mic")
            self.test_cta_btn.config(text="Test Selected Mic")
            if self.waterfall_status:
                self.waterfall_status.config(text="Waterfall: recording")
        else:
            self._draw_level_bar(0.0)
            self.test_canvas.delete("all")
            self.test_btn.config(text="Test Selected Mic")
            self.test_cta_btn.config(text="Test Selected Mic")
            self.waterfall_history = []
            if self.waterfall_status:
                self.waterfall_status.config(text="Waterfall: idle")
        self.root.after(100, self._poll_level)

    def _push_waterfall(self, level: float) -> None:
        self.waterfall_history.append(level)
        self.waterfall_history = self.waterfall_history[-WATERFALL_WINDOW:]

    def _draw_test_history(self, history: list[float], threshold: float | None = None) -> None:
        canvas = self.test_canvas
        canvas.delete("all")
        if not history:
            return
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or 80)
        n = len(history)
        bar_width = max(2, width // max(1, n))
        for i, level in enumerate(history[-(width // bar_width) :]):
            x0 = i * bar_width
            x1 = x0 + bar_width - 1
            bar_height = int(level * height)
            y0 = height - bar_height
            y1 = height
            th = threshold if threshold is not None else 0.1
            color = "#4caf50" if level > th else "#888888"
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")

    def _draw_level_bar(self, level: float) -> None:
        canvas = self.level_canvas
        canvas.delete("all")
        width = int(canvas.winfo_width() or canvas["width"])
        height = int(canvas.winfo_height() or 80)
        level = max(0.0, min(1.0, level))
        bar_height = int(level * height)
        y0 = height - bar_height
        color = "#4caf50" if level > 0.1 else "#888888"
        canvas.create_rectangle(2, y0, width - 2, height - 2, fill=color, outline="")

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
