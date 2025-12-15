"""Realtime streaming helpers (websocket listener)."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, Optional


class TranscriptListener:
    def __init__(self, url: str, on_message: Callable[[str], None], on_log: Callable[[str], None]):
        self.url = url
        self.on_message = on_message
        self.on_log = on_log
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread or not self.url:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        try:
            import websockets  # type: ignore
        except Exception as exc:  # noqa: BLE001
            self.on_log(f"[warn] Realtime disabled: websockets import failed ({exc})")
            return
        asyncio.run(self._listen(websockets))

    async def _listen(self, websockets) -> None:  # type: ignore[override]
        backoff = 1
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    self.on_log(f"[info] Connected to realtime server: {self.url}")
                    backoff = 1
                    while not self._stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        self.on_message(msg)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self.on_log(f"[warn] Realtime reconnecting in {backoff}s: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(10, backoff * 2)


__all__ = ["TranscriptListener"]
