"""Helpers for keeping repo-local .gitignore rules in sync."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def load_gitignore_rules(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = data.get("rules", [])
    cleaned: list[str] = []
    for rule in rules:
        if not isinstance(rule, str):
            continue
        trimmed = rule.strip()
        if trimmed:
            cleaned.append(trimmed)
    return cleaned


def ensure_gitignore_rules(
    repo_root: Path, rules_path: Path, log: Callable[[str], None] | None = None
) -> list[str]:
    if not repo_root.exists():
        return []
    if not (repo_root / ".git").exists():
        return []
    rules = load_gitignore_rules(rules_path)
    if not rules:
        return []

    gitignore_path = repo_root / ".gitignore"
    existing = set()
    if gitignore_path.exists():
        for line in gitignore_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            existing.add(stripped)

    to_add = [rule for rule in rules if rule not in existing]
    if not to_add:
        return []

    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        newline_prefix = "" if not content or content.endswith("\n") else "\n"
    else:
        newline_prefix = ""

    with gitignore_path.open("a", encoding="utf-8") as fh:
        if newline_prefix:
            fh.write(newline_prefix)
        for rule in to_add:
            fh.write(rule)
            fh.write("\n")

    if log:
        log(f"[info] Added {len(to_add)} gitignore rule(s) in {repo_root}")
    return to_add


def ensure_local_gitignore(
    target_dir: Path, template_path: Path, log: Callable[[str], None] | None = None
) -> bool:
    if not template_path.exists():
        return False
    try:
        template_text = template_path.read_text(encoding="utf-8")
    except OSError:
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    gitignore_path = target_dir / ".gitignore"
    if gitignore_path.exists():
        try:
            if gitignore_path.read_text(encoding="utf-8") == template_text:
                return False
        except OSError:
            pass
    gitignore_path.write_text(template_text, encoding="utf-8")
    if log:
        log(f"[info] Updated gitignore template in {target_dir}")
    return True


__all__ = ["ensure_gitignore_rules", "ensure_local_gitignore", "load_gitignore_rules"]
