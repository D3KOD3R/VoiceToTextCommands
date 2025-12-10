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
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


DEFAULT_CONFIG_PATH = Path.home() / ".voice_issues_config.json"
DEFAULT_HEADER_TITLE = "Voice Issues"


@dataclass
class RepoConfig:
    repo_path: Path
    issues_file: Path


@dataclass
class VoiceConfig:
    repos: dict
    default_repo: str
    next_issue_phrases: List[str]
    stop_phrases: List[str]
    stt_provider: str
    stt_model: Optional[str]
    stt_binary: Optional[str]
    stt_language: Optional[str]

    @classmethod
    def from_json(cls, data: dict) -> "VoiceConfig":
        repos = data.get("repos") or {}
        default_repo = data.get("defaultRepo")
        phrases = data.get("phrases") or {}
        next_issue_phrases = phrases.get("nextIssue") or ["next issue", "next point"]
        stop_phrases = phrases.get("stop") or ["end issues", "stop issues"]
        stt = data.get("stt") or {}
        return cls(
            repos=repos,
            default_repo=default_repo,
            next_issue_phrases=next_issue_phrases,
            stop_phrases=stop_phrases,
            stt_provider=stt.get("provider", "stub"),
            stt_model=stt.get("model"),
            stt_binary=stt.get("binaryPath"),
            stt_language=stt.get("language"),
        )


class ConfigLoader:
    @staticmethod
    def load(path: Path) -> VoiceConfig:
        if not path.exists():
            raise FileNotFoundError(
                f"Config not found at {path}. Create it from voice_issues_config.sample.json."
            )
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return VoiceConfig.from_json(data)

    @staticmethod
    def select_repo(config: VoiceConfig, explicit_repo: Optional[str]) -> RepoConfig:
        repo_key = explicit_repo or config.default_repo
        if not repo_key:
            raise ValueError("No repo selected and no defaultRepo set in config.")
        repo_entry = config.repos.get(repo_key)
        if not repo_entry or "issuesFile" not in repo_entry:
            raise ValueError(f"Config for repo '{repo_key}' is missing or incomplete.")
        repo_path = Path(repo_key).expanduser().resolve()
        issues_file = repo_path / repo_entry["issuesFile"]
        return RepoConfig(repo_path=repo_path, issues_file=issues_file)


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
    if next_phrases:
        separator = "|".join(re.escape(p) for p in next_phrases)
        parts = re.split(separator, text, flags=re.IGNORECASE)
    else:
        parts = [text]
    issues = [part.strip(" .;-") for part in parts if part.strip(" .;-")]
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

        with tempfile.TemporaryDirectory() as tmpdir:
            out_base = Path(tmpdir) / "whisper_out"
            cmd = [
                str(self.binary),
                "-m",
                str(self.model),
                "-f",
                str(audio_file),
                "-otxt",
                "-of",
                str(out_base),
            ]
            if self.language:
                cmd.extend(["-l", self.language])

            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:  # noqa: BLE001
                stderr = exc.stderr.decode("utf-8", errors="ignore") if exc.stderr else ""
                raise RuntimeError(f"whisper.cpp failed: {stderr}") from exc

            out_txt = Path(f"{out_base}.txt")
            if not out_txt.exists():
                raise RuntimeError("whisper.cpp did not produce transcription output.")
            return out_txt.read_text(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Voice Issue Daemon (skeleton)")
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
    writer.append_issues(issues)

    print(f"[ok] Appended {len(issues)} issue(s) to {repo_cfg.issues_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
