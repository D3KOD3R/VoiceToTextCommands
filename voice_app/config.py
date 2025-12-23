"""Configuration models and helpers for the Voice Issue Recorder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / ".voice_config.json"


@dataclass
class RepoConfig:
    repo_path: Path
    issues_file: Path


@dataclass
class VoiceConfig:
    repos: Dict[str, dict]
    default_repo: Optional[str]
    next_issue_phrases: List[str]
    stop_phrases: List[str]
    stt_provider: str
    stt_model: Optional[str]
    stt_binary: Optional[str]
    stt_language: Optional[str]
    stt_input_samplerate: Optional[int]
    stt_input_channels: Optional[int]
    hotkey_toggle: str
    hotkey_quit: str
    device_allowlist: List[str]
    device_denylist: List[str]
    realtime_ws_url: Optional[str]
    realtime_post_url: Optional[str]
    repo_root: Path

    @classmethod
    def from_json(cls, data: dict, repo_root: Path) -> "VoiceConfig":
        repos = data.get("repos") or {}
        default_repo = data.get("defaultRepo")
        phrases = data.get("phrases") or {}
        next_issue_phrases = phrases.get("nextIssue") or ["next issue", "next point"]
        stop_phrases = phrases.get("stop") or ["end issues", "stop issues"]
        stt = data.get("stt") or {}
        hotkeys = data.get("hotkeys") or {}
        devices = data.get("devices") or {}
        realtime = data.get("realtime") or {}
        return cls(
            repos=repos,
            default_repo=default_repo,
            next_issue_phrases=next_issue_phrases,
            stop_phrases=stop_phrases,
            stt_provider=stt.get("provider", "stub"),
            stt_model=stt.get("model"),
            stt_binary=stt.get("binaryPath"),
            stt_language=stt.get("language"),
            stt_input_samplerate=stt.get("inputSamplerate"),
            stt_input_channels=stt.get("inputChannels"),
            hotkey_toggle=hotkeys.get("toggle", "ctrl+alt+i"),
            hotkey_quit=hotkeys.get("quit", "ctrl+alt+q"),
            device_allowlist=devices.get("allowlist") or [],
            device_denylist=devices.get("denylist") or [],
            realtime_ws_url=realtime.get("wsUrl"),
            realtime_post_url=realtime.get("postUrl"),
            repo_root=repo_root,
        )


class ConfigLoader:
    """Utility helpers for working with the repo-local config."""

    LOCAL_ALIAS_BASE = "local"
    LEGACY_VOICE_DIR = ".voice"
    VOICEISSUES_DIR = "voiceissues"

    @staticmethod
    def load(path: Path = DEFAULT_CONFIG_PATH) -> VoiceConfig:
        if not path.exists():
            legacy = Path.home() / ".voice_issues_config.json"
            if legacy.exists():
                data = legacy.read_text(encoding="utf-8-sig")
                path.write_text(data, encoding="utf-8")
                print(f"[warn] Migrated legacy config from {legacy} to {path}")
                return VoiceConfig.from_json(json.loads(data), path.resolve().parent)
            raise FileNotFoundError(
                f"Config not found at {path}. Create it from .voice_config.sample.json in the repo."
            )
        raw_text = path.read_text(encoding="utf-8-sig")
        data = json.loads(raw_text)
        repo_root = path.resolve().parent
        if ConfigLoader._migrate_config(data, repo_root):
            path.write_text(json.dumps(data, indent=4) + "\n", encoding="utf-8")
        return VoiceConfig.from_json(data, repo_root)

    @staticmethod
    def select_repo(config: VoiceConfig, explicit_repo: Optional[str]) -> RepoConfig:
        repo_key = explicit_repo or config.default_repo
        if not repo_key:
            raise ValueError("No repo selected and no defaultRepo set in config.")
        repo_root = config.repo_root
        entry = config.repos.get(repo_key)
        if entry:
            return ConfigLoader._build_repo_config(repo_key, entry, repo_root)

        repo_path: Path | None = None
        try:
            candidate = Path(repo_key).expanduser()
            repo_path = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()
        except Exception:
            repo_path = None

        if repo_path:
            alias = ConfigLoader._find_alias_by_path(config.repos, repo_path, repo_root)
            if alias:
                return ConfigLoader._build_repo_config(alias, config.repos[alias], repo_root)

        local_alias = ConfigLoader._find_alias_by_path(config.repos, repo_root, repo_root)
        if local_alias:
            return ConfigLoader._build_repo_config(local_alias, config.repos[local_alias], repo_root)

        if repo_path:
            issues_file = ConfigLoader.default_issues_path(repo_path)
            return RepoConfig(repo_path=repo_path, issues_file=issues_file)

        raise ValueError(f"Config for repo '{repo_key}' is missing or incomplete.")

    @staticmethod
    def ensure_repo_entry(
        data: dict, repo_root: Path, repo_path: Path, issues_path: Path
    ) -> str:
        repos = data.setdefault("repos", {})
        alias = ConfigLoader._alias_for_path(repos, repo_root, repo_path)
        entry = repos.setdefault(alias, {})
        entry.update(ConfigLoader.build_repo_entry(repo_root, repo_path, issues_path))
        data["defaultRepo"] = alias
        return alias

    @staticmethod
    def build_repo_entry(repo_root: Path, repo_path: Path, issues_path: Path) -> dict:
        return {
            "path": ConfigLoader._path_for_storage(repo_root, repo_path),
            "issuesFile": ConfigLoader._issues_for_storage(repo_path, issues_path),
        }

    @staticmethod
    def default_issues_path(repo_path: Path) -> Path:
        voiceissues = (repo_path / ConfigLoader.VOICEISSUES_DIR / "voice-issues.md").resolve()
        legacy = (repo_path / ConfigLoader.LEGACY_VOICE_DIR / "voice-issues.md").resolve()
        if voiceissues.exists():
            return voiceissues
        if legacy.exists():
            return legacy
        return voiceissues

    @staticmethod
    def _migrate_config(data: dict, repo_root: Path) -> bool:
        changed = ConfigLoader._normalize_repos(data, repo_root)
        changed |= ConfigLoader._ensure_local_repo_alias(data, repo_root)
        return changed

    @staticmethod
    def _normalize_repos(data: dict, repo_root: Path) -> bool:
        repos = data.setdefault("repos", {})
        changed = False
        for alias in list(repos.keys()):
            entry = repos.get(alias)
            if not isinstance(entry, dict):
                entry = {}
                repos[alias] = entry
                changed = True
            repo_path = ConfigLoader._resolve_entry_path(alias, entry, repo_root)

            normalized_path = ConfigLoader._path_for_storage(repo_root, repo_path)
            if entry.get("path") != normalized_path:
                entry["path"] = normalized_path
                changed = True

            normalized_issues = ConfigLoader._normalize_issues_entry(repo_path, entry)
            if entry.get("issuesFile") != normalized_issues:
                entry["issuesFile"] = normalized_issues
                changed = True

            new_alias = alias
            if ConfigLoader._looks_like_path(alias) and repo_path == repo_root:
                new_alias = ConfigLoader._unique_alias(repos, ConfigLoader.LOCAL_ALIAS_BASE)
            if new_alias != alias:
                repos[new_alias] = entry
                del repos[alias]
                changed = True
        return changed

    @staticmethod
    def _ensure_local_repo_alias(data: dict, repo_root: Path) -> bool:
        repos = data.setdefault("repos", {})
        alias = ConfigLoader._find_alias_by_path(repos, repo_root, repo_root)
        changed = False
        if not alias:
            alias = ConfigLoader._unique_alias(repos, ConfigLoader.LOCAL_ALIAS_BASE)
            repos[alias] = {
                "path": ".",
                "issuesFile": ".voice/voice-issues.md",
            }
            changed = True
        else:
            entry = repos[alias]
            if entry.get("path") != ".":
                entry["path"] = "."
                changed = True
            normalized_issues = ConfigLoader._normalize_issues_entry(repo_root, entry)
            if entry.get("issuesFile") != normalized_issues:
                entry["issuesFile"] = normalized_issues
                changed = True
        if data.get("defaultRepo") != alias:
            data["defaultRepo"] = alias
            changed = True
        return changed

    @staticmethod
    def _build_repo_config(alias: str, entry: dict, repo_root: Path) -> RepoConfig:
        repo_path = ConfigLoader._resolve_entry_path(alias, entry, repo_root)
        issues_file = ConfigLoader._resolve_entry_issues(entry, repo_path)
        return RepoConfig(repo_path=repo_path, issues_file=issues_file)

    @staticmethod
    def _resolve_entry_path(alias: str, entry: dict, repo_root: Path) -> Path:
        raw_path = entry.get("path") or alias
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (repo_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    @staticmethod
    def _resolve_entry_issues(entry: dict, repo_path: Path) -> Path:
        raw = entry.get("issuesFile") or f"{ConfigLoader.VOICEISSUES_DIR}/voice-issues.md"
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = (repo_path / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return candidate

    @staticmethod
    def _normalize_issues_entry(repo_path: Path, entry: dict) -> str:
        candidate = ConfigLoader._resolve_entry_issues(entry, repo_path)
        try:
            return str(candidate.relative_to(repo_path))
        except ValueError:
            return str(candidate)

    @staticmethod
    def _path_for_storage(repo_root: Path, repo_path: Path) -> str:
        repo_path = repo_path.resolve()
        if repo_path == repo_root:
            return "."
        try:
            return str(repo_path.relative_to(repo_root))
        except ValueError:
            return str(repo_path)

    @staticmethod
    def _issues_for_storage(repo_path: Path, issues_path: Path) -> str:
        candidate = issues_path.resolve()
        try:
            return str(candidate.relative_to(repo_path))
        except ValueError:
            return str(candidate)

    @staticmethod
    def _alias_for_path(repos: dict, repo_root: Path, repo_path: Path) -> str:
        existing = ConfigLoader._find_alias_by_path(repos, repo_path, repo_root)
        if existing:
            return existing
        base = (
            ConfigLoader.LOCAL_ALIAS_BASE
            if repo_path.resolve() == repo_root
            else ConfigLoader._sanitize_alias(repo_path.name or "repo")
        )
        return ConfigLoader._unique_alias(repos, base)

    @staticmethod
    def _find_alias_by_path(repos: dict, target_path: Path, repo_root: Path) -> Optional[str]:
        for alias, entry in repos.items():
            try:
                candidate = ConfigLoader._resolve_entry_path(alias, entry, repo_root)
            except Exception:
                continue
            if candidate == target_path.resolve():
                return alias
        return None

    @staticmethod
    def _sanitize_alias(value: str) -> str:
        alias = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return alias or "repo"

    @staticmethod
    def _unique_alias(repos: dict, base: str) -> str:
        candidate = base
        index = 1
        while candidate in repos:
            candidate = f"{base}-{index}"
            index += 1
        return candidate

    @staticmethod
    def _looks_like_path(value: str) -> bool:
        if not value:
            return False
        if value.startswith(".") or value.startswith(".."):
            return True
        if ":" in value:
            return True
        return any(sep in value for sep in ("/", "\\"))


__all__ = [
    "ConfigLoader",
    "DEFAULT_CONFIG_PATH",
    "RepoConfig",
    "VoiceConfig",
]
