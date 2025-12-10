# VoiceToTextCommands

A repo-aware voice issue recorder plus Codex bridge.

## What it does
- Capture issues by voice into a repo-local Markdown file (`.voice/voice-issues.md`).
- Run Codex to address issues and tick them off with notes.
- Uses local STT via `whisper.cpp` (no API key needed).

## Quick start
1) Clone and enter the repo.
2) Build/download `whisper.cpp` and a model (e.g., `ggml-base.bin`).
3) Copy `voice_issues_config.sample.json` to `~/.voice_issues_config.json` and set:
   - `repos`: map your repo path to `.voice/voice-issues.md`.
   - `stt.binaryPath`: path to `main`/`main.exe`.
   - `stt.model`: path to your GGML/GGUF model.
   - `stt.language`: optional (e.g., `en`).
4) Capture issues (with audio file):  
   `python voice_issue_daemon.py --provider whisper_cpp --audio-file sample.wav`
   - Phrases: “next issue” starts a new bullet; “end issues” stops ingestion.
   - Writes/updates `.voice/voice-issues.md`.
5) Review/fix via Codex:
   - PowerShell: `./scripts/codex_review_issues.ps1`
   - Bash: `./scripts/codex_review_issues.sh`
   Codex will use `.voice/voice-issues.md` as its task list, apply fixes, and tick items with short notes.

## Files
- `.voice/voice-issues.md` — living checklist (voice-captured).
- `voice_issue_daemon.py` — daemon/CLI to transcribe and append issues.
- `voice_issues_config.sample.json` — config template for repos/phrases/STT.
- `scripts/codex_review_issues.ps1` / `scripts/codex_review_issues.sh` — run Codex against the checklist.
- `VOICE_ISSUE_WORKFLOW.md` — fuller workflow and options.

## Tips
- For quick testing without audio: `python voice_issue_daemon.py --text "first issue next issue second issue end issues"`.
- Ensure `.voice/voice-issues.md` is committed so Codex can both read and update it.
