# AgentExpertCoding — Expert Coding Practice

- **Primary intent:** keep all new logic inside `voice_app/` while treating each file as a self-contained module that is easy to reason about, test, and reuse.

- **Structure expectations**
  - `voice_app/app.py` orchestrates services, UI, and persistence. No new major classes should stay outside `voice_app/` unless they are small CLI stubs (e.g., `voice_gui.py`).  
  - Services (audio, transcription, issue persistence, bootstrap helpers, realtime) must live under `voice_app/services/`. UI widgets, layouts, and styles belong in `voice_app/ui/`. Generic config models belong in `voice_app/config.py`.
  - Avoid global state; pass collaborators explicitly (construct objects in one place and inject them where needed).

- **Code hygiene**
  - Prefer short helper functions over huge monolithic methods. Keep each `voice_app` module under ~400 lines if possible by extracting helpers.
  - Imports must be explicit and grouped (stdlib → third-party → local). Do not rely on implicit `sys.path` shenanigans.
  - Document non-obvious logic with brief comments or docstrings; avoid redundant commentary that restates the code.

- **Safety & reliability**
  - Wrap IO with try/except when failure is possible, log the failure, and mention which agent guard triggered the handling.  
  - When adding persistence (config, issue files, whisper assets), follow `AgentPersistence` and ensure every change path is deterministic and recoverable.

- **Testing & verification**
  - Run the relevant `python -m py_compile …` check on modules you touched. Mention this in your final reply along with any additional manual tests required.
  - If you change UI behavior, describe how to exercise the new flow (e.g., "open GUI, trigger hotkey, confirm log line").

- **Commit/step discipline**
  - Keep changes small and focused; update one service or UI group per turn. Break large refactors into multiple commits (if you were committing).
  - When you rerun commands or tests triggered by agent guidance, disclose which ones you re-ran in your reply so the context is traceable.
