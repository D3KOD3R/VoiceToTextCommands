# VoiceToTextCommands

Repo-aware voice issue recorder plus Codex bridge with local STT via whisper.cpp.

## What it does
- Capture issues by voice into a repo-local Markdown file (`.voice/voice-issues.md`).
- Run Codex to address issues and tick them off with short notes.
- Uses local STT via `whisper.cpp` (no API key needed).

## Quick start
1) Clone and enter the repo.
2) Build/download whisper.cpp and a model (e.g., `ggml-base.bin`).
   - whisper.cpp: https://github.com/ggerganov/whisper.cpp
   - Models (GGML/GGUF): https://huggingface.co/ggerganov/whisper.cpp or run `bash ./models/download-ggml-model.sh base` inside whisper.cpp.
3) Copy `voice_issues_config.sample.json` to `~/.voice_issues_config.json` and set:
   - `repos`: map your repo path to `.voice/voice-issues.md`.
   - `stt.binaryPath`: path to `main`/`main.exe`.
   - `stt.model`: path to your GGML/GGUF model.
   - `stt.language`: optional (e.g., `en`).
   - If you just pulled the repo: `git submodule update --init --recursive` to fetch `whisper.cpp`.
4) Capture issues (from audio):  
   `python voice_issue_daemon.py --provider whisper_cpp --audio-file sample.wav`  
   - Phrases: "next issue" starts a new bullet; "end issues" stops ingestion.  
   - Writes/updates `.voice/voice-issues.md`.
5) Review/fix via Codex:
   - PowerShell: `./scripts/codex_review_issues.ps1`
   - Bash: `./scripts/codex_review_issues.sh`
   Codex will use `.voice/voice-issues.md` as its task list, apply fixes, and tick items with notes.

## Files
- `.voice/voice-issues.md` — living checklist (voice-captured).
- `voice_issue_daemon.py` — daemon/CLI to transcribe and append issues.
- `voice_hotkey_daemon.py` — desktop hotkey recorder (mic → whisper.cpp → issues file).
- `voice_issues_config.sample.json` — config template for repos/phrases/STT.
- `scripts/codex_review_issues.ps1` / `scripts/codex_review_issues.sh` — run Codex against the checklist.
- `VOICE_ISSUE_WORKFLOW.md` — fuller workflow and options.
- `requirements.txt` — Python deps for hotkey/mic capture.

## Tips
- Quick test without audio: `python voice_issue_daemon.py --text "first issue next issue second issue end issues"`.
- If whisper.cpp binary is not in PATH, set `stt.binaryPath` in `~/.voice_issues_config.json` (e.g., `C:/tools/whisper.cpp/main.exe`).
- Ensure `.voice/voice-issues.md` is committed so Codex can both read and update it.

## Hotkey desktop capture (Windows)
1) Install Python deps: `pip install -r requirements.txt`
2) Ensure whisper.cpp binary/model paths are set in `~/.voice_issues_config.json`.
3) Run: `python voice_hotkey_daemon.py`  
   - Start/stop recording: `Ctrl+Alt+I` (default)
   - Quit: `Ctrl+Alt+Q`
   - It records mic audio, transcribes via whisper.cpp, segments issues on “next issue” / stops on “end issues”, and appends to `.voice/voice-issues.md`.
