#!/usr/bin/env python3
"""
Bridge `.voice/voice-issues.md` to GitHub issues using the `gh` CLI.

Default behavior is a dry run that prints which pending issues would be created.
Use `--apply` to actually create issues, optionally tagging them with labels and
annotating the backlog lines with the created issue numbers. Use `--list` to
show existing GitHub issues for the target repo.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from voice_issue_daemon import ConfigLoader, DEFAULT_CONFIG_PATH, IssueWriter


GITHUB_TAG = re.compile(r"\(gh#(?P<num>\d+)\)", re.IGNORECASE)


@dataclass
class BacklogEntry:
    line_no: int
    state: str
    text: str
    gh_number: int | None


def normalize_repo_spec(raw: str) -> str:
    raw = raw.strip()
    if raw.endswith(".git"):
        raw = raw[:-4]
    for prefix in ("https://github.com/", "http://github.com/", "git@github.com:"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    if raw.startswith("github.com/"):
        raw = raw[len("github.com/") :]
    if raw.count("/") >= 2:
        parts = raw.strip("/").split("/")
        raw = "/".join(parts[-2:])
    return raw


def resolve_repo_spec(cli_repo: str | None) -> str | None:
    if cli_repo:
        return normalize_repo_spec(cli_repo)
    pointer = ROOT / "RepoPointer.md.txt"
    if pointer.exists():
        data = pointer.read_text(encoding="utf-8").strip()
        if data:
            return normalize_repo_spec(data)
    git_dir = ROOT / ".git"
    if git_dir.exists():
        try:
            proc = subprocess.run(
                ["git", "-C", str(ROOT), "config", "--get", "remote.origin.url"],
                capture_output=True,
                text=True,
                check=False,
            )
            url = proc.stdout.strip()
            if url:
                return normalize_repo_spec(url)
        except Exception:
            pass
    return None


def default_issues_file() -> Path:
    try:
        cfg = ConfigLoader.load(DEFAULT_CONFIG_PATH)
        repo_cfg = ConfigLoader.select_repo(cfg, cfg.default_repo)
        return repo_cfg.issues_file
    except Exception:
        return ROOT / ".voice" / "voice-issues.md"


def parse_backlog(path: Path) -> tuple[list[BacklogEntry], list[str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    entries: list[BacklogEntry] = []
    for idx, line in enumerate(lines):
        match = re.match(r"^\s*[-*]\s*\[(?P<state>[ xX])\]\s*(?P<body>.+)", line)
        if not match:
            continue
        body = match.group("body").strip()
        gh_number = None
        tag = GITHUB_TAG.search(body)
        if tag:
            gh_number = int(tag.group("num"))
        entries.append(BacklogEntry(line_no=idx, state=match.group("state").lower(), text=body, gh_number=gh_number))
    return entries, lines


def add_github_tag(line: str, gh_number: int) -> str:
    if GITHUB_TAG.search(line):
        return line
    return line.rstrip() + f" (gh#{gh_number})"


def format_issue_body(entry: BacklogEntry) -> str:
    return f"{entry.text}\n\n_Imported from .voice/voice-issues.md line {entry.line_no + 1}_"


def create_github_issue(repo: str, entry: BacklogEntry, labels: list[str], dry_run: bool) -> int | None:
    safe_title = entry.text.splitlines()[0]
    safe_title = safe_title[:77] + "..." if len(safe_title) > 80 else safe_title
    cmd = ["gh", "issue", "create", "--repo", repo, "--title", safe_title, "--body", format_issue_body(entry)]
    for label in labels:
        cmd.extend(["--label", label])
    if dry_run:
        print(f"[dry-run] gh issue create --repo {repo} --title \"{safe_title}\"")
        return None
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:  # noqa: BLE001
        raise RuntimeError("GitHub CLI (gh) is not installed or not on PATH.") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh issue create failed")
    output = proc.stdout.strip() or proc.stderr.strip()
    match = re.search(r"/issues/(?P<num>\d+)", output)
    if not match:
        raise RuntimeError(f"gh issue create succeeded but issue number could not be parsed from: {output}")
    return int(match.group("num"))


def update_backlog(path: Path, lines: list[str], created: Iterable[tuple[BacklogEntry, int]]) -> None:
    updated = lines[:]
    for entry, number in created:
        updated[entry.line_no] = add_github_tag(updated[entry.line_no], number)
    text = "\n".join(updated)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def ensure_cli_available() -> None:
    if shutil.which("gh"):
        return
    raise RuntimeError("GitHub CLI (gh) is required but was not found on PATH.")


def list_github_issues(repo: str, limit: int | None) -> None:
    limit_val = str(limit) if limit else "20"
    cmd = ["gh", "issue", "list", "--repo", repo, "--json", "number,title,state", "--limit", limit_val]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:  # noqa: BLE001
        raise RuntimeError("GitHub CLI (gh) is not installed or not on PATH.") from exc
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "gh issue list failed")
    try:
        issues = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse gh issue list output: {exc}") from exc
    for issue in issues:
        num = issue.get("number")
        state = issue.get("state")
        title = issue.get("title")
        print(f"#{num} [{state}] {title}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync pending voice issues to GitHub using gh.")
    parser.add_argument("--repo", help="GitHub repo (owner/name or URL). Defaults to RepoPointer or origin remote.")
    parser.add_argument("--issues-file", type=Path, help="Path to the voice issues file (defaults from .voice_config.json).")
    parser.add_argument("--label", action="append", default=[], help="Label to apply to created issues (repeatable).")
    parser.add_argument("--limit", type=int, help="Only send this many pending issues.")
    parser.add_argument("--apply", action="store_true", help="Actually create GitHub issues (default is dry-run).")
    parser.add_argument("--no-annotate", action="store_true", help="Do not append (gh#NNN) tags to created issues.")
    parser.add_argument("--list", action="store_true", help="List current GitHub issues before any creation.")
    args = parser.parse_args()

    issues_path = (args.issues_file or default_issues_file()).expanduser()
    writer = IssueWriter(issues_path)
    writer.ensure_file()

    repo = resolve_repo_spec(args.repo)
    if not repo:
        raise SystemExit("No GitHub repo could be determined. Pass --repo or set RepoPointer.md.txt.")
    entries, lines = parse_backlog(issues_path)
    pending = [e for e in entries if e.state != "x"]
    pending_no_gh = [e for e in pending if e.gh_number is None]
    if args.limit is not None:
        pending_no_gh = pending_no_gh[: args.limit]

    print(f"Pending issues: {len(pending)} (without GitHub tag: {len(pending_no_gh)})")

    if args.list:
        ensure_cli_available()
        print(f"Listing GitHub issues for {repo}:")
        list_github_issues(repo, args.limit)
        if not args.apply:
            return

    if not pending_no_gh:
        return

    if args.apply:
        ensure_cli_available()

    created: list[tuple[BacklogEntry, int]] = []
    for entry in pending_no_gh:
        number = create_github_issue(repo, entry, args.label, dry_run=not args.apply)
        if number:
            created.append((entry, number))

    if created and args.apply and not args.no_annotate:
        update_backlog(issues_path, lines, created)
        print(f"[ok] Annotated {len(created)} backlog item(s) with GitHub issue numbers.")
    elif created:
        print(f"[info] Created {len(created)} issue(s); backlog left untouched (per --no-annotate or dry-run).")


if __name__ == "__main__":
    main()
