# Voice Issue Workflow (voiceissues)

This repo uses a repo-local `voiceissues/` folder so the Voice Issue Recorder can work without touching the repo root.

## Files
- `voiceissues/voice-issues.md`: local checklist captured from voice; Codex reads and updates this file.
- `voiceissues/VoiceIssuesAgent.md`: guidance for Codex on how to process the backlog.

## Capture Issues
Run the Voice Issue Recorder app and point it at this repo. It will append items to `voiceissues/voice-issues.md`.

Expected segmentation:
- "next issue" starts a new bullet.
- "end issues" stops ingestion.

## Review Issues with Codex
When the user asks to fix issues:
1) Read `voiceissues/voice-issues.md`.
2) Apply fixes, then mark each resolved item `[x]` with a short note.
3) Do not delete resolved items without explicit user confirmation.
