# AGENT_PERSISTENCE — Persistence & Safety

- Write outputs incrementally (e.g., append each issue immediately on detection).
- Never depend on unsaved editor state; always read/write from disk.
- Fail loudly and descriptively; errors should include the action and the missing/invalid path/device.
- Always verify persistence/safety rules when changing IO flows and note that this agent was applied.
