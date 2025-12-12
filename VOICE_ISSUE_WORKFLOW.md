# Voice Issue Workflow

This repo uses a voice-driven issues file that Codex can consume and update.

## Files
- `.voice/voice-issues.md`: living checklist captured from voice; Codex both reads and updates this file.
- `codex_review_issues.ps1`: Windows helper to run Codex against the checklist.
- `codex_review_issues.sh`: Bash helper for the same flow.
- `voice_issue_daemon.py`: Python skeleton daemon to capture voice and append issues.
- `voice_hotkey_daemon.py`: desktop hotkey recorder (Ctrl+Alt+I by default) that records mic, runs whisper.cpp, and appends issues.
- `.voice_config.sample.json`: starter config for daemon paths/phrases.
  - By default uses local `whisper.cpp` (no API key). Set `binaryPath` to your built whisper.cpp binary and `model` to a downloaded GGML/GGUF file.

## Capture Issues by Voice
You can dry-run the Python skeleton without real STT; it accepts `--text` to simulate transcription.

Config template: copy `.voice_config.sample.json` to `.voice_config.json` (repo root) and adjust repo path + issues file.

Run (simulated input):
```
python voice_issue_daemon.py --text "first issue next issue second issue end issues"
```

Run with local whisper.cpp:
```
python voice_issue_daemon.py --provider whisper_cpp --audio-file sample.wav
```
Requires:
- `binaryPath` pointing to `main`/`main.exe` from whisper.cpp build
- `model` pointing to a local GGML/GGUF model (e.g., `ggml-base.bin`)

Expected segmentation:
- "next issue" starts a new bullet.
- "end issues" stops ingestion.

Result: appends to `.voice/voice-issues.md` in the configured repo as unchecked items:
```
- [ ] Issue description
```

## Review Issues with Codex
- PowerShell: `./codex_review_issues.ps1`
- Bash: `./codex_review_issues.sh`

These scripts:
1. Verify `.voice/voice-issues.md` exists.
2. Invoke `codex --full-auto` with instructions to:
   - Use the checklist as the task list.
   - For each addressed issue: modify the codebase, then change `[ ]` to `[x]` in `.voice/voice-issues.md` with a short note (e.g., `(fixed in file X)`).
   - After the user confirms the fix is acceptable, delete the resolved item from `.voice/voice-issues.md` (do not delete without confirmation).
   - Avoid ticking items that were not actually worked on.

## Acceptance Options
- Trust mode: Codex fixes and ticks items in one run. If you revert changes, manually untick the item.
- Two-step mode: Adjust the prompt to ask Codex to propose completed items first, then run a second command to tick them after you agree.

## Repo Pointer
The remote repository URL is stored in `RepoPointer.md.txt` if needed.
