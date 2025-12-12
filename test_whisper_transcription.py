#!/usr/bin/env python3
"""
Offline whisper sanity test for a single audio file.

Requires:
  - torch
  - torchaudio
  - soundfile
  - transformers

Example:
  python scripts/test_whisper_transcription.py --audio TestVoice.wav
"""

from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf
import torch
import torchaudio.functional as taf
from transformers import WhisperForConditionalGeneration, WhisperProcessor


def load_audio(audio_path: Path, target_rate: int = 16000) -> tuple[torch.Tensor, int]:
    """
    Load audio as mono tensor and resample to the target rate if needed.
    """
    audio, sample_rate = sf.read(str(audio_path), always_2d=False)
    waveform = torch.from_numpy(audio).float()
    if waveform.ndim > 1:
        # Average stereo/mono channel dimension into a single track.
        waveform = waveform.mean(dim=-1)
    if sample_rate != target_rate:
        waveform = taf.resample(waveform, sample_rate, target_rate)
        sample_rate = target_rate
    return waveform, sample_rate


def transcribe_with_whisper(
    audio_path: Path, model_name: str = "openai/whisper-tiny.en", language: str = "en"
) -> str:
    """
    Transcribe a WAV file with a small Whisper model. Downloads the model on first run.
    """
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = WhisperProcessor.from_pretrained(model_name)
    model = WhisperForConditionalGeneration.from_pretrained(model_name).to(device)

    waveform, sample_rate = load_audio(audio_path)
    input_features = processor(
        waveform.numpy(), sampling_rate=sample_rate, return_tensors="pt"
    ).input_features.to(device)

    decoder_prompt = processor.get_decoder_prompt_ids(language=language, task="transcribe")
    with torch.inference_mode():
        predicted_ids = model.generate(input_features, forced_decoder_ids=decoder_prompt)
    transcription = processor.batch_decode(predicted_ids, skip_special_tokens=True)[0]
    return transcription.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a quick Whisper transcription test.")
    parser.add_argument(
        "--audio", type=Path, required=True, help="Path to a WAV file to transcribe."
    )
    parser.add_argument(
        "--model",
        type=str,
        default="openai/whisper-tiny.en",
        help="Hugging Face model id (default: openai/whisper-tiny.en).",
    )
    parser.add_argument(
        "--language",
        type=str,
        default="en",
        help="Language hint passed to Whisper (default: en).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    transcript = transcribe_with_whisper(args.audio, model_name=args.model, language=args.language)
    print(transcript)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
