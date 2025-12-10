#!/usr/bin/env python3
"""
Voice Hotkey Daemon (desktop)

Listens for a global hotkey, records mic audio until toggled off, transcribes
with local whisper.cpp, and appends issues to the configured Markdown backlog.

Dependencies (pip):
  - keyboard
  - sounddevice
  - numpy
whisper.cpp binary + model must be installed locally (see README).
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Optional

try:
    import keyboard  # type: ignore
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install keyboard") from exc

try:
    import sounddevice as sd  # type: ignore
except ImportError as exc:
    raise SystemExit("Missing dependency: pip install sounddevice numpy") from exc

from voice_issue_daemon import (
    ConfigLoader,
    DEFAULT_CONFIG_PATH,
    IssueWriter,
    WhisperCppProvider,
    split_issues,
)


def record_audio_to_wav(
    output_path: Path, stop_event: threading.Event, samplerate: int = 16000, channels: int = 1
) -> None:
    """
    Record from default input device until stop_event is set. Writes a WAV file.
    """
    q: queue.Queue = queue.Queue()

    def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
        if status:
            # Non-fatal warnings can be ignored; print for visibility.
            print(f"[warn] Audio status: {status}", file=sys.stderr)
        q.put(indata.copy())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sd.InputStream(
        samplerate=samplerate, channels=channels, dtype="int16", callback=callback
    ):
        with wave.open(str(output_path), "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)  # int16
            wf.setframerate(samplerate)

            while not stop_event.is_set():
                try:
                    data = q.get(timeout=0.1)
                    wf.writeframes(data.tobytes())
                except queue.Empty:
                    continue


def transcribe_with_whisper_cpp(audio_file: Path, config) -> str:
    provider = WhisperCppProvider(
        binary=Path(config.stt_binary or "main").expanduser(),
        model=Path(config.stt_model or "").expanduser(),
        language=config.stt_language,
    )
    return provider.transcribe_file(audio_file)


def run_daemon(
    config_path: Path,
    repo_key: Optional[str],
    start_stop_hotkey: str,
    quit_hotkey: str,
    samplerate: int,
    channels: int,
) -> None:
    config = ConfigLoader.load(config_path)
    repo_cfg = ConfigLoader.select_repo(config, repo_key)

    print(f"[info] Using repo: {repo_cfg.repo_path}")
    print(f"[info] Issues file: {repo_cfg.issues_file}")
    print(f"[info] Hotkey: {start_stop_hotkey} to start/stop, {quit_hotkey} to quit")

    recording = False
    stop_event = threading.Event()
    record_thread: Optional[threading.Thread] = None

    def start_recording():
        nonlocal recording, stop_event, record_thread
        if recording:
            return
        recording = True
        stop_event = threading.Event()
        tmp_wav = Path.cwd() / "tmp_voice_capture.wav"
        record_thread = threading.Thread(
            target=record_audio_to_wav, args=(tmp_wav, stop_event, samplerate, channels), daemon=True
        )
        record_thread.start()
        print("[info] Recording... (press hotkey again to stop)")
        return tmp_wav

    def stop_recording(tmp_wav: Path):
        nonlocal recording, stop_event, record_thread
        if not recording:
            return None
        stop_event.set()
        if record_thread:
            record_thread.join()
        recording = False
        print("[info] Recording stopped. Transcribing...")
        return tmp_wav

    state = {"tmp": None}

    def toggle_recording():
        if not recording:
            state["tmp"] = start_recording()
        else:
            tmp_wav = stop_recording(state.get("tmp"))
            if tmp_wav:
                try:
                    transcript = transcribe_with_whisper_cpp(tmp_wav, config)
                    issues = split_issues(transcript, config.next_issue_phrases, config.stop_phrases)
                    if not issues:
                        print("[info] No issues detected.")
                        return
                    writer = IssueWriter(repo_cfg.issues_file)
                    writer.append_issues(issues)
                    print(f"[ok] Appended {len(issues)} issue(s) to {repo_cfg.issues_file}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[error] {exc}", file=sys.stderr)
                finally:
                    try:
                        tmp_wav.unlink()
                    except OSError:
                        pass

    keyboard.add_hotkey(start_stop_hotkey, toggle_recording)

    def quit_daemon():
        if recording:
            stop_event.set()
        print("[info] Exiting.")
        keyboard.unhook_all_hotkeys()
        raise SystemExit(0)

    keyboard.add_hotkey(quit_hotkey, quit_daemon)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        quit_daemon()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice hotkey daemon (whisper.cpp local)")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to voice issues config (default: ~/.voice_issues_config.json)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repo key from config.repos to target (defaults to config.defaultRepo)",
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        default="ctrl+alt+i",
        help="Global hotkey to start/stop recording (default: ctrl+alt+i)",
    )
    parser.add_argument(
        "--quit",
        type=str,
        default="ctrl+alt+q",
        help="Global hotkey to quit daemon (default: ctrl+alt+q)",
    )
    parser.add_argument(
        "--samplerate",
        type=int,
        default=16000,
        help="Audio sample rate for recording (default: 16000)",
    )
    parser.add_argument(
        "--channels",
        type=int,
        default=1,
        help="Number of audio channels (default: 1/mono)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_daemon(
        config_path=args.config,
        repo_key=args.repo,
        start_stop_hotkey=args.hotkey,
        quit_hotkey=args.quit,
        samplerate=args.samplerate,
        channels=args.channels,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
