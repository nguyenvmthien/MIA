"""Stage 2 — Preprocess: normalize audio to 16kHz mono WAV with noise reduction."""

import subprocess
import time
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf

from meeting_agent.monitoring.metrics import STAGE_LATENCY


class PreprocessError(Exception):
    pass


def _ffmpeg_to_wav(source: Path, dest: Path) -> None:
    """Convert any audio format to 16kHz mono WAV via ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(source),
        "-ar", "16000",       # 16 kHz sample rate (required by Whisper)
        "-ac", "1",           # mono
        "-acodec", "pcm_s16le",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise PreprocessError(f"ffmpeg failed:\n{result.stderr}")


def preprocess_audio(audio_path: Path) -> Path:
    """
    Normalize audio: convert to 16kHz mono WAV, apply noise reduction.

    Returns path to the preprocessed WAV file (sibling of input with _clean suffix).
    """
    t0 = time.monotonic()
    wav_path = audio_path.parent / "audio_raw.wav"
    clean_path = audio_path.parent / "audio_clean.wav"

    # Step 1: convert to WAV 16kHz mono
    _ffmpeg_to_wav(audio_path, wav_path)

    # Step 2: noise reduction
    data, sr = sf.read(str(wav_path))
    if data.ndim > 1:
        data = data.mean(axis=1)  # safety: force mono
    reduced = nr.reduce_noise(y=data.astype(np.float32), sr=sr, prop_decrease=0.75)
    sf.write(str(clean_path), reduced, sr, subtype="PCM_16")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    STAGE_LATENCY.labels(stage="preprocess").observe(elapsed_ms / 1000)
    return clean_path
