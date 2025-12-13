# VoiceToTextCommands

Repo-aware voice issue recorder plus Codex bridge with local STT via whisper.cpp.

## What it does
- Capture issues by voice into a repo-local Markdown file (`.voice/voice-issues.md`).
- Run Codex to address issues and tick them off with short notes.
- Uses local STT via `whisper.cpp` (no API key needed).
- GUI recorder with mic selection and live level (whisper.cpp backend).
- GUI mic test with waterfall meter to confirm the mic is working.
- Manage issue states in the GUI (mark pending as done, undo completed items, delete, waitlist bucket with drag/drop, skip delete confirms, and wrap long text).
- Settings panel now lists the configured hotkeys, repo path, and issues file in a static column, offers a one-click **Create voice file** helper, and keeps the inputs grouped in left/right columns that match the mockup.
- The repo picker remembers past selections in `.voice/past_repos.md`, so previously used repositories reappear in the dropdown without retyping.
- Optional realtime transcript relay server (FastAPI/Docker) that feeds a speech output window in the GUI.
- Hotkey daemon for quick capture via whisper.cpp.
- Optional GitHub bridge: push unchecked voice issues to GitHub using the `gh` CLI.
- One-click installer to fetch whisper.cpp binary/model into the repo and set config.
- Test transcription helper (HF whisper) for quick verification.

## Quick start
1) Clone and enter the repo.
2) Build/download whisper.cpp and a model (e.g., `ggml-base.bin`).
   - whisper.cpp: https://github.com/ggerganov/whisper.cpp
   - Models (GGML/GGUF): https://huggingface.co/ggerganov/whisper.cpp or run `bash ./models/download-ggml-model.sh base` inside whisper.cpp.
3) Copy `.voice_config.sample.json` to `.voice_config.json` (in this repo) and set:
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
   - PowerShell: `./codex_review_issues.ps1`
   - Bash: `./codex_review_issues.sh`
   Codex will use `.voice/voice-issues.md` as its task list, apply fixes, and tick items with notes.

## Sync voice issues to GitHub (optional)
- Repo target comes from `RepoPointer.md.txt` or your `origin` remote; override with `--repo owner/name`.
- Preview: `python sync_github_issues.py --list` (shows GitHub issues) and `python sync_github_issues.py` (shows pending backlog items without creating anything).
- Create issues: `python sync_github_issues.py --apply --label voice` (uses `gh issue create`, adds `(gh#123)` tags back into `.voice/voice-issues.md` unless `--no-annotate`).
- Throttle with `--limit N`. Requires GitHub CLI (`gh`) to be installed and authenticated.

## Realtime transcript server (optional)
- Start locally (no Docker): `uvicorn speech_server:app --host 0.0.0.0 --port 8000`
- Or build/run via Docker:  
  `docker build -f Dockerfile.speech-server -t voice-transcript-server .`  
  `docker run --rm -p 8000:8000 voice-transcript-server`
- Configure the GUI to listen/post in `.voice_config.json` (defaults are `ws://localhost:8000/ws` and `http://localhost:8000/transcript` under `"realtime"`).
- The GUI speech output window will show any transcript strings posted to `/transcript`; it reconnects automatically if the server restarts.

## Files
- `.voice/voice-issues.md` – living checklist (voice-captured).
- `voice_issue_daemon.py` – daemon/CLI to transcribe and append issues.
- `voice_hotkey_daemon.py` — desktop hotkey recorder (mic → whisper.cpp → issues file).
- `.voice_config.sample.json` — config template for repos/phrases/STT (copy to `.voice_config.json`).
- `codex_review_issues.ps1` / `codex_review_issues.sh` — run Codex against the checklist.
- `VOICE_ISSUE_WORKFLOW.md` — fuller workflow and options.
- `requirements.txt` — Python deps for hotkey/mic capture.

## Tips
- Quick test without audio: `python voice_issue_daemon.py --text "first issue next issue second issue end issues"`.
- If whisper.cpp binary is not in PATH, set `stt.binaryPath` in `.voice_config.json` (e.g., `.tools/whisper/main.exe`).
- Ensure `.voice/voice-issues.md` is committed so Codex can both read and update it.

## Whisper sanity test
- Optional deps (CPU): `python -m pip install --user --index-url https://download.pytorch.org/whl/cpu torch torchaudio` and `python -m pip install --user soundfile transformers`
- Transcribe a WAV (defaults to `openai/whisper-tiny.en`): `python test_whisper_transcription.py --audio TestVoice.wav`

## One-click install (Windows)
- Double-click `install_whisper.cmd` (or run `powershell -ExecutionPolicy Bypass -File install_whisper.ps1`).
- This downloads the official whisper.cpp v1.8.2 x64 binary and the `ggml-base.en.bin` model into `.tools/whisper` and updates `.voice_config.json` in this repo to point at them.
- After that, run `python voice_hotkey_daemon.py` and use your configured hotkeys.

## GUI recorder (mic select + live level)
- Run: `python voice_gui.py` (wrapper for the GUI app)
- Pick your microphone from the dropdown, click “Start Recording”, then “Stop & Transcribe”.
- The input level bar shows live mic activity; results are appended to `.voice/voice-issues.md` using your config’s whisper paths and hotkeys are not required.

## Hotkey desktop capture (Windows)
1) Install Python deps: `pip install -r requirements.txt`
2) Ensure whisper.cpp binary/model paths are set in `.voice_config.json`.
3) Optional: set hotkeys in `.voice_config.json` under `hotkeys.toggle` and `hotkeys.quit`.
4) Run: `python voice_hotkey_daemon.py`  
   - Start/stop recording: `Ctrl+Alt+I` (default, or your `hotkeys.toggle`)
   - Quit: `Ctrl+Alt+Q` (default, or your `hotkeys.quit`)
   - It records mic audio, transcribes via whisper.cpp, segments issues on “next issue” / stops on “end issues”, and appends to `.voice/voice-issues.md`.
