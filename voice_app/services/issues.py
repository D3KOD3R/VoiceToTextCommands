"""Issue list persistence helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_HEADER_TITLE = "Voice Issues"


class IssueWriter:
    def __init__(self, issues_file: Path):
        self.issues_file = issues_file

    def ensure_file(self) -> None:
        self.issues_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.issues_file.exists():
            header = f"# {DEFAULT_HEADER_TITLE}  {datetime.now():%Y-%m-%d %H:%M}\n\n"
            self.issues_file.write_text(header, encoding="utf-8")

    def append_issues(self, issues: Iterable[str]) -> None:
        cleaned = [issue.strip() for issue in issues if issue.strip()]
        if not cleaned:
            return
        self.ensure_file()
        with self.issues_file.open("a", encoding="utf-8") as handle:
            for issue in cleaned:
                handle.write(f"- [ ] {issue}\n")


def append_issues_incremental(writer: IssueWriter, issues: Iterable[str]) -> None:
    for issue in issues:
        writer.append_issues([issue])


__all__ = ["IssueWriter", "append_issues_incremental", "DEFAULT_HEADER_TITLE"]
