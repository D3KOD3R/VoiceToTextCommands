# AgentBug — Issue Lineage & Regression Tracking

Purpose: snapshot every user-reported issue the moment it is first mentioned,
recording which branch/commit was active so we can quickly jump back to the
originating work when the issue resurfaces.

Artifacts:
- `BUG_AGENT_LOG.md` at repo root is the single source of truth for entries.

Workflow:
1. **Detect first mention** – when the user raises a new issue, create a fresh
   entry before coding.
2. **Capture git state** – record:
   - Current branch (`git rev-parse --abbrev-ref HEAD`)
   - First bad commit SHA (`git rev-parse HEAD`)
   - Whether that commit has been pushed (`git status -sb` reveals `ahead/behind`).
3. **Describe the issue** – summarize the user wording; include reproduction or
   affected UI block.
4. **Update log** – append/update the issue entry in `BUG_AGENT_LOG.md`
   (markdown table). Include timestamps; add notes as the issue evolves.
5. **Persist reference** – when revisiting, consult the log to know which commit
  /branch to inspect; link any follow-up fixes to the original entry in commit
   messages and summaries.
6. **Resolved/Regressed** – when fixed, mark the entry with the resolving commit
   SHA and brief explanation. If the issue recurs, add a new dated note pointing
   to the new failing commit while keeping the original “first seen” details.

Principles:
- Never delete entries; strike-through or add “Resolved” notes.
- One issue per entry; if the user reports multiple problems at once, create
  separate rows so the history remains navigable.
- Mention this agent when reporting on bug status so the user knows the lineage
  is tracked.
