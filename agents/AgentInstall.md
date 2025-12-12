# AGENT_INSTALL — Installation & Packaging

- All required assets (config, binary, model paths) should resolve inside the repo by default.
- Provide single-step bootstrap scripts (e.g., `scripts/install_whisper.*`) that download binaries/models into repo-local folders and update repo-local config.
- Avoid global installs or HOME-level config; if migrating legacy config, copy it into repo-local `.voice_config.json`.
- Always consider these rules when touching install/packaging and state that you did so; do not skip this agent.
