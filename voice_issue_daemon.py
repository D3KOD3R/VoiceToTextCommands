#!/usr/bin/env python3
"""
Voice Issue Daemon (skeleton)

Listens for a trigger, captures speech-to-text, segments issues on key phrases,
and writes/updates the Markdown backlog file used by Codex.

This skeleton focuses on file handling and parsing. Replace `SpeechToTextStub`
with a concrete STT provider (e.g., Whisper) and wire a global hotkey using
`keyboard` or your preferred library.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from voice_app.config import ConfigLoader, DEFAULT_CONFIG_PATH, RepoConfig

DEFAULT_HEADER_TITLE = "Voice Issues"
ISSUE_NUMBER_PATTERN = re.compile(r"\bissue\s+(?:number\s+)?(\d+)\b", re.IGNORECASE)

class IssueWriter:
    def __init__(self, issues_file: Path):
        self.issues_file = issues_file

    def ensure_file(self) -> None:
        self.issues_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.issues_file.exists():
            header = f"# {DEFAULT_HEADER_TITLE}  {datetime.now():%Y-%m-%d %H:%M}\n\n"
            self.issues_file.write_text(header, encoding="utf-8")

    def append_issues(self, issues: Iterable[str]) -> None:
        cleaned = [issue.strip() for issue in issues if issue.strip()]
        if not cleaned:
            return
        self.ensure_file()
        with self.issues_file.open("a", encoding="utf-8") as f:
            for issue in cleaned:
                f.write(f"- [ ] {issue}\n")


def append_issues_incremental(writer: IssueWriter, issues: Iterable[str]) -> None:
    """
    Write issues one-by-one so each boundary (e.g., 'next issue') persists immediately.
    """
    for issue in issues:
        writer.append_issues([issue])


def strip_after_stop(text: str, stop_phrases: List[str]) -> str:
    if not text:
        return ""
    pattern = "|".join(re.escape(p) for p in stop_phrases)
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return text[: match.start()] if match else text


def split_issues(text: str, next_phrases: List[str], stop_phrases: List[str]) -> List[str]:
    text = strip_after_stop(text, stop_phrases)
    if not text.strip():
        return []
    marker = "__ISSUE_BOUNDARY__"

    def _inject_boundary(match: re.Match[str]) -> str:
        return f"{marker} {match.group(0)}"

    text = ISSUE_NUMBER_PATTERN.sub(_inject_boundary, text)
    separators = [re.escape(p) for p in next_phrases if p and p.strip()]
    separators.append(re.escape(marker))
    pattern = "|".join(separators)
    parts = re.split(pattern, text, flags=re.IGNORECASE) if pattern else [text]
    issues = [part.strip(" .;-") for part in parts if part and part.strip(" .;-")]
    return issues


class SpeechToTextStub:
    """
    Placeholder STT. Replace with real implementation (Whisper/DeepSeek/etc.).
    For now, uses provided text or stdin lines to simulate a transcript.
    """

    def __init__(self, provided_text: Optional[str] = None):
        self.provided_text = provided_text

    def record_and_transcribe(self) -> str:
        if self.provided_text is not None:
            return self.provided_text
        print("STT stub: type your transcript, end with EOF (Ctrl+D/Ctrl+Z):", file=sys.stderr)
        return sys.stdin.read()


class WhisperCppProvider:
    """
    Local whisper.cpp runner. Requires the whisper.cpp binary and a GGML/GGUF model.
    Example command pattern:
        ./main -m ./models/ggml-base.bin -f audio.wav -otxt -of /tmp/out
    """

    def __init__(self, binary: Path, model: Path, language: Optional[str] = None):
        # Prefer whisper-cli.exe if the config still points at main.exe (deprecated wrapper)
        if binary.name.lower() == "main.exe":
            alt = binary.with_name("whisper-cli.exe")
            if alt.exists():
                binary = alt
        self.binary = binary
        self.model = model
        self.language = language
        if not self.binary.exists():
            raise FileNotFoundError(f"whisper.cpp binary not found at {self.binary}")
        if not self.model.exists():
            raise FileNotFoundError(f"whisper.cpp model not found at {self.model}")

    def transcribe_file(self, audio_file: Path) -> str:
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        def rewrite_wav(src: Path, dest: Path) -> None:
            import wave  # local import to keep top-level lean
            with wave.open(str(src), "rb") as r:
                params = r.getparams()
                data = r.readframes(params.nframes)
            with wave.open(str(dest), "wb") as w:
                w.setnchannels(params.nchannels)
                w.setsampwidth(params.sampwidth)
                w.setframerate(params.framerate)
                w.writeframes(data)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_base = Path(tmpdir) / "whisper_out"
            in_path = audio_file
            attempt = 0
            while True:
                attempt += 1
                cmd = [
                    str(self.binary),
                    "-m",
                    str(self.model),
                    "-f",
                    str(in_path),
                    "-otxt",
                    "-of",
                    str(out_base),
                ]
                if self.language:
                    cmd.extend(["-l", self.language])

                try:
                    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
                except subprocess.CalledProcessError as exc:  # noqa: BLE001
                    stderr = exc.stderr if exc.stderr else ""
                    stdout = exc.stdout if exc.stdout else ""
                    msg = (stderr or stdout).strip() or "unknown error"
                    # If WAV read failed, rewrite to a fresh PCM16 and retry once.
                    if "failed to read audio data as wav" in msg.lower() and attempt == 1 and audio_file.suffix.lower() == ".wav":
                        fixed = Path(tmpdir) / "rewritten.wav"
                        rewrite_wav(audio_file, fixed)
                        in_path = fixed
                        continue
                    raise RuntimeError(f"whisper.cpp failed: {msg}") from exc
                else:
                    # whisper.cpp sometimes prints warnings to stderr even on success; surface them in logs if needed.
                    if completed.stderr:
                        err = completed.stderr.strip()
                        if err:
                            print(f"[warn] whisper.cpp: {err}", file=sys.stderr)

                out_txt = Path(f"{out_base}.txt")
                if out_txt.exists():
                    return out_txt.read_text(encoding="utf-8")

                stdout = completed.stdout.strip() if completed and completed.stdout else ""
                stderr = completed.stderr.strip() if completed and completed.stderr else ""
                # If output missing after first attempt and we haven't rewritten, try a rewrite once.
                if attempt == 1 and audio_file.suffix.lower() == ".wav":
                    fixed = Path(tmpdir) / "rewritten.wav"
                    rewrite_wav(audio_file, fixed)
                    in_path = fixed
                    continue
                raise RuntimeError(
                    "whisper.cpp did not produce transcription output. "
                    f"stdout: {stdout or '∅'} | stderr: {stderr or '∅'}"
                )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice Issue Daemon (skeleton)")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to voice issues config (default: .voice_config.json in repo)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repo key from config.repos to target (defaults to config.defaultRepo)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="STT provider override (stub|whisper_cpp). Defaults to config.stt.provider.",
    )
    parser.add_argument(
        "--audio-file",
        type=Path,
        default=None,
        help="Path to an audio file to transcribe (wav/m4a/mp3). Overrides --text.",
    )
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="Bypass STT and use this transcript string (useful for testing)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = ConfigLoader.load(args.config)
        repo_cfg = ConfigLoader.select_repo(config, args.repo)
    except Exception as exc:  # noqa: BLE001 (small CLI)
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    provider = (args.provider or config.stt_provider or "stub").lower()

    if args.text:
        stt = SpeechToTextStub(provided_text=args.text)
        transcript = stt.record_and_transcribe()
    elif provider == "whisper_cpp":
        try:
            binary = Path(config.stt_binary or "main").expanduser()
            model = Path(config.stt_model or "").expanduser()
            if not args.audio_file:
                raise ValueError("Provide --audio-file when using provider=whisper_cpp.")
            stt = WhisperCppProvider(binary=binary, model=model, language=config.stt_language)
            transcript = stt.transcribe_file(args.audio_file)
        except Exception as exc:  # noqa: BLE001
            print(f"[error] STT failed: {exc}", file=sys.stderr)
            return 1
    else:
        stt = SpeechToTextStub()
        transcript = stt.record_and_transcribe()
    issues = split_issues(transcript, config.next_issue_phrases, config.stop_phrases)

    if not issues:
        print("[info] No issues detected in transcript.")
        return 0

    writer = IssueWriter(repo_cfg.issues_file)
    append_issues_incremental(writer, issues)

    print(f"[ok] Appended {len(issues)} issue(s) to {repo_cfg.issues_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
