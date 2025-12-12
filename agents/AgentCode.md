# AGENT_CODE — Code Style

- Keep modules importable from repo root and from subdirs (prepend repo root to `sys.path` in script entrypoints as needed).
- Use explicit, small helper functions for IO-heavy tasks (recording, transcription, appends).
- Avoid unnecessary dependencies; prefer stdlib or already-included packages.
- Always confirm these code-style rules before coding and state that you followed them; do not skip.
