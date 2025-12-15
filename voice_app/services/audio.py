"""Audio capture helpers shared between GUI and daemon entrypoints."""

from __future__ import annotations

import queue
import re
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
import sounddevice as sd

NOISY_NAMES = re.compile(r"(hands[- ]?free|hf audio|bthhfenum|telephony|communications|loopback|primary sound capture)", re.I)
WATERFALL_WINDOW = 50


def normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def hostapi_priority(idx: Optional[int], hostapis: Optional[List[dict]] = None) -> int:
    hostapis = hostapis or sd.query_hostapis()
    if idx is None or idx >= len(hostapis):
        return 99
    name = hostapis[idx].get("name", "").lower()
    if "wasapi" in name:
        return 0
    if "mme" in name:
        return 1
    if "directsound" in name:
        return 2
    return 3


def apply_device_filters(devices: List[dict], allow: Optional[List[str]], deny: Optional[List[str]]) -> List[dict]:
    if allow:
        allow_set = {a.lower() for a in allow}
        devices = [d for d in devices if d["name"].lower() in allow_set]
    if deny:
        deny_set = {d.lower() for d in deny}
        devices = [d for d in devices if d["name"].lower() not in deny_set]
    return devices


def list_input_devices(allow: Optional[List[str]] = None, deny: Optional[List[str]] = None) -> List[dict]:
    hostapis = sd.query_hostapis()
    devices = sd.query_devices()
    best: dict[str, dict] = {}
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        name = dev.get("name", "")
        if NOISY_NAMES.search(name):
            continue
        priority = hostapi_priority(dev.get("hostapi"), hostapis)
        if priority >= 3:
            continue
        norm = normalize_name(name)
        cand = {
            "id": idx,
            "name": name,
            "max_input_channels": dev.get("max_input_channels", 0),
            "hostapi": dev.get("hostapi"),
            "hostapi_priority": priority,
        }
        existing_key = None
        for key in best:
            if norm in key or key in norm:
                existing_key = key
                break
        if existing_key:
            existing = best[existing_key]
            if cand["hostapi_priority"] < existing["hostapi_priority"]:
                best[existing_key] = cand
        else:
            best[norm] = cand
    filtered = list(best.values())
    filtered.sort(key=lambda d: (d["hostapi_priority"], d["name"].lower()))
    return apply_device_filters(filtered, allow, deny)


@dataclass
class Recorder:
    samplerate: int = 16000
    channels: int = 1
    device: Optional[int] = None

    def __post_init__(self) -> None:
        self.stream: Optional[sd.InputStream] = None
        self.wav_file: Optional[wave.Wave_write] = None
        self._level = 0.0
        self._lock = threading.Lock()

    @property
    def level(self) -> float:
        with self._lock:
            return self._level

    def start(self, output_path: Path, extra_settings=None) -> None:
        if self.stream:
            return
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self.wav_file = wave.open(str(output_path), "wb")
        self.wav_file.setnchannels(self.channels)
        self.wav_file.setsampwidth(2)
        self.wav_file.setframerate(self.samplerate)

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if status:
                pass
            self.wav_file.writeframes(indata.tobytes())
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            level = min(1.0, rms * 2.5 / 32768.0)
            with self._lock:
                self._level = level

        stream_kwargs = dict(
            device=self.device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        if extra_settings is not None:
            stream_kwargs["extra_settings"] = extra_settings
        self.stream = sd.InputStream(**stream_kwargs)
        self.stream.start()

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None
        with self._lock:
            self._level = 0.0

    def is_recording(self) -> bool:
        return self.stream is not None


class MicTester:
    def __init__(self, samplerate: int = 16000, channels: int = 1, device: Optional[int] = None):
        self.samplerate = samplerate
        self.channels = channels
        self.device = device
        self.stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._level = 0.0
        self.level_history: List[float] = []
        self.above_since: Optional[float] = None
        self.working = False
        self.threshold = 0.12
        self.min_duration = 1.0

    @property
    def level(self) -> float:
        with self._lock:
            return self._level

    def start(self, device: Optional[int], samplerate: Optional[int] = None, channels: Optional[int] = None) -> None:
        if self.stream:
            return
        self.device = device
        if samplerate:
            self.samplerate = samplerate
        if channels:
            self.channels = channels
        self.level_history = []
        self.above_since = None
        self.working = False

        def callback(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
            if status:
                pass
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            level = min(1.0, rms / 32768.0)
            level = min(1.0, level * 2.5)
            now = time.monotonic()
            with self._lock:
                self._level = level
                self.level_history.append(level)
                self.level_history = self.level_history[-WATERFALL_WINDOW:]
                if level > self.threshold:
                    if self.above_since is None:
                        self.above_since = now
                    elif now - self.above_since >= self.min_duration:
                        self.working = True
                else:
                    self.above_since = None

        self.stream = sd.InputStream(
            device=self.device,
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=callback,
        )
        self.stream.start()

    def stop(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        with self._lock:
            self._level = 0.0

    def is_testing(self) -> bool:
        return self.stream is not None


__all__ = [
    "Recorder",
    "MicTester",
    "list_input_devices",
    "apply_device_filters",
    "hostapi_priority",
    "normalize_name",
    "NOISY_NAMES",
    "WATERFALL_WINDOW",
]
