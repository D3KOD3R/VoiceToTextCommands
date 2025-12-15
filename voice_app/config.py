"""Configuration models and helpers for the Voice Issue Recorder."""

from __future__ import annotations

import json
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

    @classmethod
    def from_json(cls, data: dict) -> "VoiceConfig":
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
        )


class ConfigLoader:
    @staticmethod
    def load(path: Path = DEFAULT_CONFIG_PATH) -> VoiceConfig:
        if not path.exists():
            legacy = Path.home() / ".voice_issues_config.json"
            if legacy.exists():
                data = legacy.read_text(encoding="utf-8-sig")
                path.write_text(data, encoding="utf-8")
                print(f"[warn] Migrated legacy config from {legacy} to {path}")
                return VoiceConfig.from_json(json.loads(data))
            raise FileNotFoundError(
                f"Config not found at {path}. Create it from .voice_config.sample.json in the repo."
            )
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return VoiceConfig.from_json(data)

    @staticmethod
    def select_repo(config: VoiceConfig, explicit_repo: Optional[str]) -> RepoConfig:
        repo_key = explicit_repo or config.default_repo
        if not repo_key:
            raise ValueError("No repo selected and no defaultRepo set in config.")
        repo_entry = config.repos.get(repo_key)
        repo_path = Path(repo_key).expanduser().resolve()
        if not repo_entry:
            for key, val in config.repos.items():
                try:
                    if Path(key).expanduser().resolve() == repo_path:
                        repo_entry = val
                        break
                except Exception:
                    continue
        if not repo_entry or "issuesFile" not in repo_entry:
            raise ValueError(f"Config for repo '{repo_key}' is missing or incomplete.")
        issues_file = repo_path / repo_entry["issuesFile"]
        return RepoConfig(repo_path=repo_path, issues_file=issues_file)


__all__ = [
    "ConfigLoader",
    "DEFAULT_CONFIG_PATH",
    "RepoConfig",
    "VoiceConfig",
]
