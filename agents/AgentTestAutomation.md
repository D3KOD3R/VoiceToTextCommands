# AgentTestAutomation - Automated Smoke Tests

Purpose: run automated smoke tests that validate the core voice-issues flow without touching production repos.

Workflow:
1) Run `python scripts/run_smoke_tests.py` to exercise the `test repo/` fixture.
2) Confirm the script reports success and leaves the test repo clean (unless `--keep` is used).
3) If failures occur, fix them before shipping and document the outcome.
