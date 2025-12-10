# Voice Issue Workflow

This repo uses a voice-driven issues file that Codex can consume and update.

## Files
- `.voice/voice-issues.md`: living checklist captured from voice; Codex both reads and updates this file.
- `scripts/codex_review_issues.ps1`: Windows helper to run Codex against the checklist.
- `scripts/codex_review_issues.sh`: Bash helper for the same flow.

## Capture Issues by Voice
1. Start the daemon (desktop app or service) that listens for the hotkey (e.g., `Ctrl+Alt+I`).
2. Speak issues; say “next issue” to start a new bullet; say “end issues” to finish.
3. The daemon writes/updates `.voice/voice-issues.md` with unchecked items:
   ```
   - [ ] Issue description
   ```

## Review Issues with Codex
- PowerShell: `./scripts/codex_review_issues.ps1`
- Bash: `./scripts/codex_review_issues.sh`

These scripts:
1. Verify `.voice/voice-issues.md` exists.
2. Invoke `codex --full-auto` with instructions to:
   - Use the checklist as the task list.
   - For each addressed issue: modify the codebase, then change `[ ]` to `[x]` in `.voice/voice-issues.md` with a short note (e.g., `(fixed in file X)`).
   - Avoid ticking items that weren’t actually worked on.

## Acceptance Options
- Trust mode: Codex fixes and ticks items in one run. If you revert changes, manually untick the item.
- Two-step mode: Adjust the prompt to ask Codex to propose completed items first, then run a second command to tick them after you agree.

## Repo Pointer
The remote repository URL is stored in `RepoPointer.md.txt` if needed.
