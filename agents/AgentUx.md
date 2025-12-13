# AgentUx — Native UI Experience Principles

Goals: make the app obvious, low-friction, and trustworthy. Favor legibility, minimal clicks, and immediate feedback. Avoid hidden behaviors and surprise states. Always apply this guidance when changing UX; explicitly note when/why it is used.

## NativeUXAgent (sub-agent)
- Scope: enforce native/desktop UX guidance for this project.
- Use: consult these principles when designing/changing UI or UX flows.

1) Information clarity
   - Show full device names and important paths; never truncate critical identifiers.
   - Group context succinctly (repo path, issues file, status) near the top; keep it scannable.
   - Use plain language labels: “Start Recording”, “Stop & Transcribe”, “Selected device”.

2) Layout & density
   - Single-column flow for primary actions; avoid sprawling grids.
   - Keep controls vertically stacked with consistent spacing; align labels left, inputs fill width.
   - Prioritize above-the-fold essentials: device picker, level meter, start/stop, status/log.

3) Feedback & state
   - Always indicate current state: recording vs idle, selected device, file write result.
   - Show a live level meter during recording; clear to zero when idle.
   - Emit concise log lines for start/stop, transcription success/fail, file write, and errors.
   - Use status text instead of blocking modals; errors should state action + failing resource.

4) Controls & defaults
   - Make the primary action obvious (Start Recording). Pair with a clear Stop/Transcribe.
   - Default to sensible choices (first input device) but let users change easily.
   - Never hide critical actions behind menus or hotkeys alone.

5) Copy & labeling
   - Prefer short, action-oriented labels and messages.
   - Include counts and targets in success messages (e.g., “Appended 2 issue(s) to …”).
   - Avoid jargon; if a term is domain-specific, pair it with a brief hint in the log.

6) Error handling
   - State the operation and the failing resource (e.g., “Transcribe failed: binary missing at …”).
   - Keep users in control: don’t exit on recoverable errors; allow retry after showing the issue.
   - Avoid pop-ups unless the app can’t proceed; use inline status/log instead.

7) Visual restraint
   - Use system or neutral fonts; keep font sizes readable.
   - Minimal color usage; reserve emphasis for status/log (info/warn/error) and the level meter.
   - No animations beyond the level meter update; avoid distracting motion.

8) Persistence & safety (UX-facing)
   - Write increments immediately (per “next issue”); confirm success in the log.
   - Never depend on unsaved buffers; always read/write from disk.
   - Show the target file path to reassure users where output goes.

9) Accessibility-minded basics
   - Ensure tab order follows the visual flow.
   - Provide sufficient contrast; avoid tiny touch targets.
   - Use text for meaning; don’t rely solely on color or icons.
