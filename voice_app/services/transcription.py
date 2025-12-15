"""Transcription helpers built on whisper.cpp."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional


ISSUE_NUMBER_PATTERN = re.compile(r"\bissue\s+(?:number\s+)?(\d+)\b", re.IGNORECASE)


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


class WhisperCppProvider:
    """Drive the whisper.cpp binary to transcribe audio files."""

    def __init__(self, binary: Path, model: Path, language: Optional[str] = None):
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
            import wave

            with wave.open(str(src), "rb") as reader:
                params = reader.getparams()
                data = reader.readframes(params.nframes)
            with wave.open(str(dest), "wb") as writer:
                writer.setnchannels(params.nchannels)
                writer.setsampwidth(params.sampwidth)
                writer.setframerate(params.framerate)
                writer.writeframes(data)

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
                    stderr = exc.stderr or ""
                    stdout = exc.stdout or ""
                    msg = (stderr or stdout).strip() or "unknown error"
                    if "failed to read audio data as wav" in msg.lower() and attempt == 1 and audio_file.suffix.lower() == ".wav":
                        fixed = Path(tmpdir) / "rewritten.wav"
                        rewrite_wav(audio_file, fixed)
                        in_path = fixed
                        continue
                    raise RuntimeError(f"whisper.cpp failed: {msg}") from exc
                else:
                    if completed.stderr:
                        err = completed.stderr.strip()
                        if err:
                            print(f"[warn] whisper.cpp: {err}", file=sys.stderr)

                out_txt = Path(f"{out_base}.txt")
                if out_txt.exists():
                    return out_txt.read_text(encoding="utf-8")

                stdout = completed.stdout.strip() if completed and completed.stdout else ""
                stderr = completed.stderr.strip() if completed and completed.stderr else ""
                if attempt == 1 and audio_file.suffix.lower() == ".wav":
                    fixed = Path(tmpdir) / "rewritten.wav"
                    rewrite_wav(audio_file, fixed)
                    in_path = fixed
                    continue
                raise RuntimeError(
                    "whisper.cpp did not produce transcription output. "
                    f"stdout={stdout or 'n/a'}, stderr={stderr or 'n/a'}"
                )


def transcribe_with_whisper_cpp(audio_file: Path, config) -> str:
    provider = WhisperCppProvider(
        binary=Path(config.stt_binary or "main").expanduser(),
        model=Path(config.stt_model or "").expanduser(),
        language=config.stt_language,
    )
    return provider.transcribe_file(audio_file)


__all__ = [
    "WhisperCppProvider",
    "transcribe_with_whisper_cpp",
    "split_issues",
    "strip_after_stop",
]
