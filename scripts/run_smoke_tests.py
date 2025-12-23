#!/usr/bin/env python3
"""Automated smoke tests for the Voice Issue Recorder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_app.config import ConfigLoader, DEFAULT_CONFIG_PATH
from voice_app.gitignore import ensure_local_gitignore
from voice_issue_daemon import IssueWriter, append_issues_incremental, split_issues

VOICEISSUES_AGENT_SOURCE = ROOT / "agents" / "VoiceIssuesAgent.md"
VOICEISSUES_WORKFLOW_SOURCE = ROOT / "config" / "voiceissues_workflow.md"
VOICEISSUES_GITIGNORE_SOURCE = ROOT / "config" / "voiceissues_gitignore.txt"


def _copy_if_needed(source: Path, target: Path) -> None:
    if not source.exists():
        return
    try:
        if target.exists() and target.read_bytes() == source.read_bytes():
            return
    except Exception:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def _ensure_voiceissues_assets(issues_dir: Path) -> None:
    issues_dir.mkdir(parents=True, exist_ok=True)
    _copy_if_needed(VOICEISSUES_AGENT_SOURCE, issues_dir / "VoiceIssuesAgent.md")
    _copy_if_needed(VOICEISSUES_WORKFLOW_SOURCE, issues_dir / "VOICE_ISSUE_WORKFLOW.md")
    ensure_local_gitignore(issues_dir, VOICEISSUES_GITIGNORE_SOURCE)


def run_smoke(repo_path: Path, keep: bool) -> int:
    issues_dir = repo_path / "voiceissues"
    issues_file = issues_dir / "voice-issues.md"
    _ensure_voiceissues_assets(issues_dir)

    original = issues_file.read_text(encoding="utf-8") if issues_file.exists() else None

    try:
        config = ConfigLoader.load(DEFAULT_CONFIG_PATH)
        next_phrases = config.next_issue_phrases
        stop_phrases = config.stop_phrases
    except Exception:
        next_phrases = ["next issue", "next point"]
        stop_phrases = ["end issues", "stop issues"]

    transcript = "first issue next issue second issue end issues"
    issues = split_issues(transcript, next_phrases, stop_phrases)
    if len(issues) < 2:
        print("[error] Split issues failed to detect expected items.")
        return 1

    writer = IssueWriter(issues_file)
    append_issues_incremental(writer, issues)

    text = issues_file.read_text(encoding="utf-8")
    if "first issue" not in text or "second issue" not in text:
        print("[error] Issues were not appended as expected.")
        return 1

    if not keep:
        if original is None:
            issues_file.unlink(missing_ok=True)
        else:
            issues_file.write_text(original, encoding="utf-8")

    print("[ok] Smoke tests passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Voice Issue Recorder smoke tests.")
    parser.add_argument(
        "--repo",
        type=Path,
        default=ROOT / "test repo",
        help="Repo path to use for smoke tests (defaults to ./test repo).",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep appended issues instead of restoring the original file.",
    )
    args = parser.parse_args()
    repo_path = args.repo.expanduser().resolve()
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)
    return run_smoke(repo_path, args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
