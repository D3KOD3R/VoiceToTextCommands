# Voice Issues Agent - Canonical Voice Workflow

This agent is the single source of truth whenever we're working through the `fix issues` command in this repo. 

## Primary files
- `.voice/voice-issues.md` is the canonical backlog for this repo (legacy location; every `fix issues` run begins here).
- `voiceissues/voice-issues.md` is the repo-local alternative when this repo opts into the `voiceissues/` directory.
- `voice_issue_daemon.py`, `voice_hotkey_daemon.py`, and `speech_server.py` are the helpers that feed these files; `codex_review_issues.ps1` / `codex_review_issues.sh` exercise them via `codex --full-auto`.
- `.voice_config.json` (or `.voice_config.sample.json`) keeps repo aliases, repo paths, stop phrases, and the URLs used by the real-time transcript server.

## Workflow
1. Always open the active checklist before touching any code. Prefer `voiceissues/voice-issues.md` when populated; otherwise work against `.voice/voice-issues.md` as configured via `.voice_config.json`. Summarize the outstanding entries so you know the remaining scope.
2. Follow the process described in this agent and the README: obey the `load repo <alias>` behaviour (which updates `defaultRepo` and `.voice/repo_history.json`), append new issues immediately, and do not delete items without explicit confirmation.
3. Never start work on `[~]` (waitlist) entries unless the user specifically asks for “work on waitlist”. Otherwise work through the unchecked `[ ]` entries in order.
4. Before editing related code, set the checkbox to `[working on]` so the UI shows progress. Implement the fix, then either:
   - Mark the entry `[x]` with a short clarifying note (e.g., `(fixed in voice_gui_app.py)`), or
   - Leave it `[ ]` and explain in the final response why it still needs attention.
5. Do not declare the task complete until every entry that was present at the start of the session is either resolved or explained.
6. If new issues appear while you work, append them immediately and keep them in scope; reopen the checklist after resolving the original queue to capture the additions.
7. Report in the final reply which issues were completed and which remain, citing their text and line number from `.voice/voice-issues.md` (or `voiceissues/voice-issues.md`, whichever you edited) so the user can verify the changes.
8. When the backlog is empty, mention the acceptance options in your reply: trust mode (fix and tick in one run) or the two-step mode (propose completions first, then mark them after confirmation).

## Tooling reminders
- `voice_issue_daemon.py` and `voice_hotkey_daemon.py` split transcripts by the configured `nextIssue` / `stop` phrases, honor `load repo <alias>`, and append to the issues file immediately.
- `speech_server.py` relays transcripts to websocket clients (`voice_gui.py` and the real-time pane); its backlog is intentionally capped so the server never hoards more than ~50 entries and stays light on RAM.
- `codex_review_issues.ps1` / `codex_review_issues.sh` resolve the active backlog and expect Codex to set `[working on]` / `[x]` as progress happens.
- `config/voiceissues_gitignore.txt` and `config/gitignore_rules.json` describe which `.voice` or `voiceissues/` artifacts should stay out of source control (copy the template contents when setting up a new repo folder).

## Promises
- The voice issues list is the first and last place we consult for this task; every code change needs a matching tick/note in the checklist.
- We never claim victory while any original entry remains unchecked.
- We do not delete entries without confirmation, and we do not tick issues we have not actually fixed.

## Templates
- Seeded repos get `voiceissues/VoiceIssuesAgent.md` and `config/voiceissues_workflow.md`. When you encounter a repo-local `voiceissues/` workflow, follow the template there and keep it in sync with this consolidated guidance.
