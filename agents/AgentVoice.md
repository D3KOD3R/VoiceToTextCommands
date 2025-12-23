# AgentVoice — Voice Issue Backlog Enforcement

- **Purpose:** Treat `.voice/voice-issues.md` as the canonical backlog for every “fix issues” or “voice issues” task. When the user invokes the voice issue flow, the agent must check every item listed there and explicitly resolve, document, or defer each one before finishing the turn.
- **Workflow**
  1. Always open `.voice/voice-issues.md` at the start of a fix request. Summarize outstanding entries so we know the work that remains.
 2. Use `VOICE_ISSUE_WORKFLOW.md` as the high-level process reference. The workflow reinforces: append issues immediately, tick them only when addressed, never delete without confirmation.
 3. Prioritize issues in order. For each entry, mark it `[working on]` before starting work so the UI shows progress, implement the change, then either:
     - Mark the item `[x]` with a clarifying note (e.g., "(layout stacked button row)"), or
     - Explain in the response why it remains `[ ]` (e.g., "needs additional clarification / blocked on upstream change").
  4. Do not close the task until every entry that was present at the beginning of this session is accounted for (resolved or explained). If new issues are emitted during the work, capture them in the file and keep them in scope.
  5. Report in the final reply which voice issues were completed and which still require work, referencing their text and line number from `.voice/voice-issues.md`.

- **Agent promises**
  - I will not claim the voice issue work is done while any original entry from the backlog remains unchecked.
  - The voice issue list must be the first and last place I visit for guidance on what to fix; every code change that addresses a voice issue needs a matching tick/count update to the file.
