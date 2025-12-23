# VoiceToTextCommands

Repo-aware voice issue recorder plus Codex bridge with local STT via whisper.cpp.

## What it does
- Capture issues by voice into a repo-local Markdown file (`voiceissues/voice-issues.md` by default; legacy `.voice/voice-issues.md` supported).
- Run Codex to address issues and tick them off with short notes.
- Uses local STT via `whisper.cpp` (no API key needed).
- GUI recorder with mic selection and live level (whisper.cpp backend).
- GUI mic test with waterfall meter to confirm the mic is working.
- Remembers the last selected input device and restores it on launch.
- Manage issue states in the GUI (mark pending as done, undo completed items, delete, waitlist bucket with drag/drop, skip delete confirms, and wrap long text).
- Settings panel now lists the configured hotkeys, repo path, and issues file in a static column, keeps the inputs grouped in left/right columns that match the mockup, and sits the Test Selected Mic button beside the device picker so checks happen where you choose the mic.
- The repo picker remembers past selections in `.voice/past_repos.md`, so previously used repositories reappear in the dropdown without retyping.
- When targeting another repo, the app creates a repo-local `voiceissues/` folder (workflow + agent + `.gitignore`) without touching the repo root.
- Deleted issues are archived with Undo Delete and Empty Archive actions.
- Plays a chime/logs a notification when a repo's pending issues reach zero.
- The latest GUI action (drag, delete, edit, reorder) can be undone with `Ctrl+Z` without manually editing the file.
- Completed issues show the most recently closed items first and append a `(completed YYYY-MM-DD HH:MM)` timestamp when they move to done so the bucket highlights when each entry landed in the "done" lane.
- Optional realtime transcript relay server (FastAPI/Docker) that feeds a speech output window in the GUI.
- Hotkey daemon for quick capture via whisper.cpp.
- Optional GitHub bridge: push unchecked voice issues to GitHub using the `gh` CLI.
- One-click installer to fetch whisper.cpp binary/model into the repo and set config.
- Automated smoke tests via `scripts/run_smoke_tests.py` using the `test repo/` fixture.
- Test transcription helper (HF whisper) for quick verification.
- Product ideas go straight into the GUI’s Waitlist bucket so marketing-ready concepts stay visible without an extra file.

## Quick start
1) Clone and enter the repo.
2) Build/download whisper.cpp and a model (e.g., `ggml-base.bin`).
   - whisper.cpp: https://github.com/ggerganov/whisper.cpp
   - Models (GGML/GGUF): https://huggingface.co/ggerganov/whisper.cpp or run `bash ./models/download-ggml-model.sh base` inside whisper.cpp.
3) Copy `.voice_config.sample.json` to `.voice_config.json` (in this repo) and set:
   - `repos`: assign an alias (the sample uses `"local"`) with `path": "."` and `issuesFile": "voiceissues/voice-issues.md"` so the loader stays repo-agnostic; you can also let the GUI populate this when you point it at a new repo.
   - `stt.binaryPath`: keep the path relative to the repo (e.g., `.tools/whisper/whisper-cli.exe` or `main.exe`).
   - `stt.model`: the relative path to your GGML/GGUF model inside the repo.
   - `stt.language`: optional (e.g., `en`).
   - If you just pulled the repo: `git submodule update --init --recursive` to fetch `whisper.cpp`.
4) Capture issues (from audio):  
   `python voice_issue_daemon.py --provider whisper_cpp --audio-file sample.wav`  
   - Phrases: "next issue" starts a new bullet; "end issues" stops ingestion.  
   - Writes/updates `voiceissues/voice-issues.md` (or legacy `.voice/voice-issues.md` when present).
5) Review/fix via Codex:
   - PowerShell: `./codex_review_issues.ps1`
   - Bash: `./codex_review_issues.sh`
   Codex will use the repo's issues file as its task list, apply fixes, and tick items with notes.

## Keyboard shortcuts
- `Delete` removes the current selection from the focused bucket (pending/done/waitlist).
- `Ctrl+D` removes the current selection from the focused bucket (matches "Delete selected").
- `Ctrl+Z` undoes the most recent issues-file action (drag, delete, edit, reorder, or state change).
- Click an already-selected issue to deselect it without touching a toolbar button.
- `Escape` clears the active selection so the alternating buttons stay accessible.
- The `Delete selected` action now lives beside `Remove duplicates` above the buckets so it always affects whichever list currently has focus.

## Sync voice issues to GitHub (optional)
- Repo target comes from `RepoPointer.md.txt` or your `origin` remote; override with `--repo owner/name`.
- Preview: `python sync_github_issues.py --list` (shows GitHub issues) and `python sync_github_issues.py` (shows pending backlog items without creating anything).
- Create issues: `python sync_github_issues.py --apply --label voice` (uses `gh issue create`, adds `(gh#123)` tags back into the issues file unless `--no-annotate`).
- Throttle with `--limit N`. Requires GitHub CLI (`gh`) to be installed and authenticated.

## Realtime transcript server (optional)
- Start locally (no Docker): `uvicorn speech_server:app --host 0.0.0.0 --port 8000`
- Or build/run via Docker:  
  `docker build -f Dockerfile.speech-server -t voice-transcript-server .`  
  `docker run --rm -p 8000:8000 voice-transcript-server`
- Configure the GUI to listen/post in `.voice_config.json` (defaults are `ws://localhost:8000/ws` and `http://localhost:8000/transcript` under `"realtime"`).
- The GUI speech output window will show any transcript strings posted to `/transcript`; it reconnects automatically if the server restarts.

## Files
- `voiceissues/voice-issues.md` - living checklist in target repos (legacy `.voice/voice-issues.md` supported).
- `voice_issue_daemon.py` – daemon/CLI to transcribe and append issues.
- `voice_hotkey_daemon.py` — desktop hotkey recorder (mic → whisper.cpp → issues file).
- `.voice_config.sample.json` — config template for repos/phrases/STT (copy to `.voice_config.json`).
- `codex_review_issues.ps1` / `codex_review_issues.sh` - run Codex against the checklist.
- `VOICE_ISSUE_WORKFLOW.md` - fuller workflow and options.
- `agents/VoiceIssuesAgent.md` / `config/voiceissues_workflow.md` - templates seeded into `voiceissues/`.
- `requirements.txt` - Python deps for hotkey/mic capture.

## Tips
- Quick test without audio: `python voice_issue_daemon.py --text "first issue next issue second issue end issues"`.
- If whisper.cpp binary is not in PATH, set `stt.binaryPath` in `.voice_config.json` (e.g., `.tools/whisper/main.exe`).
- Ensure the issues file exists in the target repo before running Codex.

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
- The input level bar shows live mic activity; results are appended to the configured issues file (defaults to `voiceissues/voice-issues.md`).

## Hotkey desktop capture (Windows)
1) Install Python deps: `pip install -r requirements.txt`
2) Ensure whisper.cpp binary/model paths are set in `.voice_config.json`.
3) Optional: set hotkeys in `.voice_config.json` under `hotkeys.toggle` and `hotkeys.quit`.
4) Run: `python voice_hotkey_daemon.py`  
   - Start/stop recording: `Ctrl+Alt+I` (default, or your `hotkeys.toggle`)
   - Quit: `Ctrl+Alt+Q` (default, or your `hotkeys.quit`)
   - It records mic audio, transcribes via whisper.cpp, segments issues on "next issue" / stops on "end issues", and appends to the configured issues file.
