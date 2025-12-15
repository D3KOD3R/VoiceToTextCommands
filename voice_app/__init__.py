"""Voice Issue Recorder application package."""

from __future__ import annotations

from typing import Any

__all__ = ["VoiceApp", "main"]


def __getattr__(name: str) -> Any:
    if name == "VoiceApp":
        from .app import VoiceApp as _VoiceApp

        return _VoiceApp
    if name == "main":
        from .app import main as _main

        return _main
    raise AttributeError(name)
