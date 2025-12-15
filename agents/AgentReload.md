# AgentReload — Context Refresh Checklist

**Mandatory purpose:** Each time the project context reloads (new boot/session, `pwd` change, or after an extended pause), you **must** run this checklist before editing anything else so you have a reliable, up-to-date snapshot.

- **Starter commands (execute before touching source)** \
  1. `pwd` and `git status -sb` to confirm your working tree and branch state; record any unstaged/staged surprises. \
  2. Re-open `Agents.md` and walk through the ordered agent list so you remember the active rules. \
  3. Inspect `voice_app/`, `.gitignore`, and any fresh modules (e.g., `voice_app/bootstrap.py`); treat `voice_app` as the canonical entrypoint and do not recreate the deleted legacy scripts.

**Ongoing guardrails (do not skip)** \
  - All significant logic must live inside `voice_app/` (services, ui, bootstrap, config, etc.); do not recreate the old scripts. \
  - Document any failing commands or regressions in your final reply, explicitly noting which checklist step you reran to recover context. \
  - When new modules are added, ensure they live under `voice_app/` (services, ui, bootstrap, etc.) before creating entrypoints elsewhere.
