"""Bootstrap helpers to ensure whisper.cpp assets exist before use."""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Optional
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
WHISPER_ZIP_URL = "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.2/whisper-bin-x64.zip"
MODEL_BASE_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
DEFAULT_MODEL_NAME = "ggml-base.en.bin"

LogFn = Optional[Callable[[str], None]]


def ensure_whisper_assets(config, config_path: Path, log: LogFn = None) -> None:
    """Download whisper binaries/models on demand so the GUI keeps working."""

    logger = log or (lambda msg: None)
    provider = (config.stt_provider or "stub").lower()
    if provider != "whisper_cpp":
        return

    binary_path = _resolve_optional_path(config.stt_binary)
    model_path = _resolve_optional_path(config.stt_model)
    install_dir = binary_path.parent if binary_path else REPO_ROOT / ".tools" / "whisper"
    if not binary_path:
        binary_path = install_dir / "main.exe"
    if not model_path:
        model_path = install_dir / DEFAULT_MODEL_NAME

    install_dir.mkdir(parents=True, exist_ok=True)

    binary_candidate = _find_existing_binary(binary_path)
    model_present = model_path.exists()
    changed = False

    if not binary_candidate:
        logger(f"[info] whisper: installing release into {install_dir}")
        _install_whisper_release(install_dir, logger)
        binary_candidate = _find_existing_binary(binary_path)
        changed = True

    if not model_present:
        logger(f"[info] whisper: downloading model {model_path.name}")
        _download_model(model_path, logger)
        model_present = True
        changed = True

    if not binary_candidate:
        raise FileNotFoundError(
            f"whisper.cpp binary not found after install. Expected under {install_dir}."
        )
    if not model_present:
        raise FileNotFoundError(f"whisper.cpp model not found after download at {model_path}")

    config.stt_binary = str(binary_candidate)
    config.stt_model = str(model_path)

    if changed:
        _update_config_file(config_path, binary_candidate, model_path, logger)
        logger(f"[ok] whisper assets ready in {binary_candidate.parent}")


def _resolve_optional_path(path_str: Optional[str]) -> Optional[Path]:
    if not path_str:
        return None
    try:
        return Path(path_str).expanduser().resolve()
    except Exception:
        return Path(path_str)


def _find_existing_binary(preferred: Path) -> Optional[Path]:
    candidates = [preferred]
    parent = preferred.parent
    std_candidates = [parent / "whisper-cli.exe", parent / "main.exe"]
    for cand in std_candidates:
        if cand not in candidates:
            candidates.append(cand)
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def _install_whisper_release(target_dir: Path, log: Callable[[str], None]) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        zip_path = tmp_path / "whisper.zip"
        _download_to(WHISPER_ZIP_URL, zip_path, log)
        extract_dir = tmp_path / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)
        release_dir = extract_dir / "Release"
        if not release_dir.exists():
            alt_dir = _locate_release_dir(extract_dir)
            if alt_dir is None:
                raise RuntimeError("Failed to locate Release folder inside whisper archive")
            release_dir = alt_dir
        for item in release_dir.iterdir():
            dest = target_dir / item.name
            if item.is_file():
                shutil.copy2(item, dest)
            elif item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)


def _locate_release_dir(root: Path) -> Optional[Path]:
    for candidate in root.rglob("main.exe"):
        return candidate.parent
    return None


def _download_model(dest: Path, log: Callable[[str], None]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{MODEL_BASE_URL}{dest.name}"
    _download_to(url, dest, log)


def _download_to(url: str, dest: Path, log: Callable[[str], None]) -> None:
    log(f"[info] whisper: downloading {url}")
    with urlopen(url) as response, open(dest, "wb") as out_file:
        shutil.copyfileobj(response, out_file)


def _update_config_file(config_path: Path, binary: Path, model: Path, log: Callable[[str], None]) -> None:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return
    except Exception as exc:  # noqa: BLE001
        log(f"[warn] whisper: failed to parse {config_path}: {exc}")
        return
    stt = data.setdefault("stt", {})
    stt["provider"] = "whisper_cpp"
    stt["binaryPath"] = str(binary)
    stt["model"] = str(model)
    data_str = json.dumps(data, indent=4)
    config_path.write_text(data_str + "\n", encoding="utf-8")


__all__ = ["ensure_whisper_assets"]
