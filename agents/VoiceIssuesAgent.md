# VoiceIssues Agent - Repo-Local Guidance

Purpose: keep Codex focused on the repo-local voice issues workflow stored under `voiceissues/`.

Use these files:
- `voiceissues/voice-issues.md` as the task list.
- `voiceissues/VOICE_ISSUE_WORKFLOW.md` for the workflow steps.
- `voiceissues/.gitignore` to keep local artifacts out of git.

Workflow:
1) List outstanding items from `voiceissues/voice-issues.md` and work through them in order until each is resolved or deferred.
   - When the user requests “fix issues,” start working immediately; do not pause to ask for permission or clarification before making progress.
2) Before starting a task, change its checkbox to `[working on]` so the UI shows progress; after implementing a fix, change it to `[x]` with a short note in the issues file.
3) If an item cannot be resolved, leave it `[ ]` and explain why in the response.
4) Re-open `voiceissues/voice-issues.md` after finishing to catch any new items, then continue.
5) Do not delete items without user confirmation.
