# AgentTest — Testing & Verification Plan

Purpose: provide a repeatable checklist to verify the app end-to-end. Every change should run through these steps; any warnings/errors must be fed back to the main agent for resolution before shipping.
Always reference this checklist and state what was or was not run; do not skip test reasoning.

0) Preflight
- Confirm `.voice_config.json` exists and paths resolve: whisper binary, model, issues file directory.
- Ensure `.tools/whisper/main.exe` and `.tools/whisper/ggml-*.bin` exist.

1) Installer sanity
- Run `powershell -ExecutionPolicy Bypass -File install_whisper.ps1 -NoConfigUpdate` in a clean state.
- Verify `.tools/whisper/main.exe` and model downloaded; config untouched when `-NoConfigUpdate` is set.
- If warnings/errors appear, capture them and resolve before proceeding.

2) Device enumeration
- Run: `python - <<'PY'\nfrom voice_gui_app import list_input_devices\nprint(list_input_devices())\nPY`
- Confirm only active input devices appear; allow/deny filters honored from `.voice_config.json`.
- If unexpected devices appear or expected ones are missing, log and resolve.

3) GUI hotkeys
- Run `python voice_gui.py`; confirm hotkey indicator shows “ready”.
- Press the toggle hotkey; confirm indicator changes to “pressed/recording”. Stop and confirm it returns to “ready”.
- If the `keyboard` module install fails, capture the warning and fix.

4) GUI mic test
- In GUI, select device, click “Test Selected Mic”, speak ~2 seconds; expect waterfall activity, raw level updates, status “OK (voice detected >1s)”. Stop test; status returns to idle.
- If mic test fails (sample rate, device error), log and resolve.

5) GUI recording
- Start Recording, speak “first issue next issue second issue end issues”, Stop & Transcribe. Verify `.voice/voice-issues.md` appended with two items.
- If sample rate errors occur, ensure fallbacks succeed; otherwise log and fix.

6) Hotkey daemon
- `python voice_hotkey_daemon.py`, use configured hotkey to start/stop recording; speak the same phrase; confirm issues appended. Quit with quit hotkey. Check log for errors.

7) Transcription helper
- `python test_whisper_transcription.py --audio TestVoice.wav` and confirm expected text output (sanity check of Whisper stack).

8) Error handling
- Temporarily point config to a missing model/binary; run GUI/daemon to ensure clear error message (path missing) and no crash.
- If errors are unclear or crashes occur, log and resolve.

9) Config filters
- Set `devices.allowlist` to a known device name; rerun `list_input_devices` and GUI to ensure only that device appears. Clear it afterwards.

Reporting loop
- Any warning/error observed in steps above must be surfaced to the main agent and fixed before sign-off. Document the fix or rationale if a warning is intentional.
