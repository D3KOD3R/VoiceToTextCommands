# AgentGitRules - Gitignore Rules for Local Artifacts

Purpose: keep per-user, auto-generated files out of git while the logic that defines them stays in the repo.

Workflow:
1) Treat `config/gitignore_rules.json` as the source of truth for ignore patterns created by the app.
2) Treat `config/voiceissues_gitignore.txt` as the template for repo-local `voiceissues/.gitignore`.
3) When new local artifacts are introduced, add their patterns to that file.
4) Ensure repo prep calls `voice_app.gitignore.ensure_gitignore_rules` so repo-root `.gitignore` stays in sync when needed.
5) Avoid ignoring shared artifacts (e.g., `.voice/voice-issues.md`) unless the user explicitly asks.
