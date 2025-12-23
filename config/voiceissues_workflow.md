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
1) Read `voiceissues/voice-issues.md` and begin work immediately; do not pause to request permission.
2) For each item, update it to `[working on]` before starting so the UI shows progress.
3) Work through each item in order until every entry present at the start is resolved or explicitly deferred.
4) Apply fixes, then mark each resolved item `[x]` with a short note in the issues file.
4) If an item cannot be resolved, leave it `[ ]` and explain why in the response.
5) Re-open `voiceissues/voice-issues.md` after completing the list to catch any newly added items, then repeat the process.
6) Do not delete resolved items without explicit user confirmation.
