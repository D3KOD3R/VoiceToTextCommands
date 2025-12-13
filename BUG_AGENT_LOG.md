# Bug Agent Log

| Issue ID | First Seen (UTC) | Branch | Commit | Description | Status / Notes |
| --- | --- | --- | --- | --- | --- |
| GUI-001 | 2025-12-13T20:05:00Z | feat/gui-component-blocks | 3161838fde747f7363755f95d4f0421155ab409a | Waterfall viewport missing; user cannot see microphone waterfall spanning full width. | Verified fixed by component refactor/grid layout (user confirmation 2025-12-13). |
| GUI-002 | 2025-12-13T17:59:22Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | Issue list lacks numeric captions; user needs numbered labels matching spoken “issue 1/2/3”. | Fixed in working tree – headers now show live counts per bucket. |
| STT-001 | 2025-12-13T17:59:22Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | Saying “issue 2/3/4” is not treated as a new entry; transcript parser fails to split, also speech output panel stays empty. | Fixed in working tree – parser honors “issue N” and GUI logs local transcripts. |
| GUI-003 | 2025-12-13T17:59:22Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | Issue bucket columns do not stretch across the view; pending/completed/waitlist panes stay narrow. | Fixed 2025-12-13T18:24:00Z - issues panel now spans the full top row and controls sit beneath it. |
| GUI-004 | 2025-12-13T17:59:22Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | Apply settings button too small; user wants large square-style action. | Fixed in working tree – Apply button moved to a full-width CTA under paths. |
| GUI-005 | 2025-12-13T17:59:22Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | Duplicate "Test Selected Mic" button near waterfall should be removed (top button already exists). | Fixed in working tree - removed lower duplicate button. |
| PROC-002 | 2025-12-13T18:17:04Z | feat/gui-component-blocks | 815cda41a5c02f3b0b470f768d6ab65811e51623 | After resolving tasks, `.voice/voice-issues.md` entries remain unchecked. | Fixed 2025-12-13T18:24:00Z - checklist updated and workflow noted to keep marking items. |
| GUI-006 | 2025-12-13T19:06:51Z | feat/gui-component-blocks | 2e353a1 | Layout needs to match the latest mock: top controls inside the red span, level meter/ready inside the black span with the live speech output panel, and the waterfall should sit immediately below the recording controls. | Fixed 2025-12-13T19:15:10Z – live-level span, live speech output, and layout updates complete. |
| GUI-007 | 2025-12-13T19:27:04Z | feat/gui-component-blocks | 869e020 | Bucket entries aren’t editable; double-click should allow in-place editing and persistence. | Fixed 2025-12-13T19:27:04Z – introduced dialog that saves edited text back to the issues file. |

_Use `agents/AgentBug.md` workflow to add new entries._
