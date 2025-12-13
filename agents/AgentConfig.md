# AGENT_CONFIG — Configuration

- Default config lives in the repo: `.voice_config.json` (template: `.voice_config.sample.json`).
- Keep paths relative to the repo when practical (e.g., `.tools/whisper/main.exe`).
- Ensure code tolerates legacy configs by auto-migrating to the repo-local config.
- Explicitly check this guidance when editing config defaults/migration and mention compliance; do not skip.
