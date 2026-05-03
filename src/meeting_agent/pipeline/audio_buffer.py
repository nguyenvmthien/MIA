"""
VAD-aware audio buffer for streaming transcription.

Collects raw PCM frames, uses Silero VAD to detect speech boundaries,
and yields complete speech segments (numpy arrays) ready for WhisperX.

Silero VAD model is downloaded once and cached in memory.

Usage:
    buf = AudioBuffer(sample_rate=16000, silence_ms=800)
    buf.push(pcm_bytes)   # call for each incoming chunk
    for segment in buf.drain_segments():
        transcript = whisperx_transcribe(segment)
"""

import logging
import time
from collections import deque

import numpy as np

log = logging.getLogger(__name__)

# Silero VAD threshold and window
_VAD_THRESHOLD   = 0.5
_VAD_WINDOW_SIZE = 512   # samples (32 ms at 16 kHz — Silero requirement)

_vad_model = None
_vad_utils = None


def _load_vad():
    global _vad_model, _vad_utils
    if _vad_model is not None:
        return _vad_model, _vad_utils
    try:
        import torch
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        _vad_model = model
        _vad_utils = utils
        log.info("Silero VAD model loaded")
        return model, utils
    except Exception as e:
        log.warning("Silero VAD unavailable (%s) — falling back to energy VAD", e)
        return None, None


def _energy_vad(chunk: np.ndarray, threshold: float = 0.01) -> bool:
    """Fallback: simple RMS energy threshold."""
    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
    return rms > threshold * 32768


class AudioBuffer:
    """
    Accumulates raw PCM (int16, mono, 16 kHz) and segments by speech activity.

    Args:
        sample_rate:  must be 16000 for Silero VAD
        silence_ms:   milliseconds of silence to treat as end-of-utterance
        max_segment_ms: hard cap on segment length (flush regardless of VAD)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        silence_ms: int = 800,
        max_segment_ms: int = 30_000,
    ):
        self.sample_rate = sample_rate
        self._silence_samples = int(sample_rate * silence_ms / 1000)
        self._max_samples = int(sample_rate * max_segment_ms / 1000)
        self._buf: deque[np.ndarray] = deque()
        self._speech_buf: list[np.ndarray] = []
        self._silent_since: float | None = None
        self._in_speech = False
        self._ready_segments: list[np.ndarray] = []
        self._vad_model, self._vad_utils = _load_vad()

    def _is_speech(self, chunk: np.ndarray) -> bool:
        if self._vad_model is not None:
            try:
                import torch
                audio = torch.from_numpy(chunk.astype(np.float32) / 32768.0)
                if audio.shape[0] < _VAD_WINDOW_SIZE:
                    audio = torch.nn.functional.pad(audio, (0, _VAD_WINDOW_SIZE - audio.shape[0]))
                conf = self._vad_model(audio, self.sample_rate).item()
                return conf >= _VAD_THRESHOLD
            except Exception:
                pass
        return _energy_vad(chunk)

    def push(self, pcm_bytes: bytes) -> None:
        """
        Accept raw PCM bytes (int16 LE, mono, 16 kHz) and detect speech boundaries.
        Call drain_segments() after push() to retrieve completed segments.
        """
        if not pcm_bytes:
            return
        chunk = np.frombuffer(pcm_bytes, dtype=np.int16)
        speaking = self._is_speech(chunk)

        if speaking:
            self._in_speech = True
            self._silent_since = None
            self._speech_buf.append(chunk)
        else:
            if self._in_speech:
                if self._silent_since is None:
                    self._silent_since = time.monotonic()
                self._speech_buf.append(chunk)
                elapsed_silent = int((time.monotonic() - self._silent_since) * 1000)
                total_samples = sum(c.shape[0] for c in self._speech_buf)
                if elapsed_silent >= (self._silence_samples * 1000 // self.sample_rate) or \
                        total_samples >= self._max_samples:
                    self._flush_segment()

    def _flush_segment(self) -> None:
        if not self._speech_buf:
            return
        segment = np.concatenate(self._speech_buf)
        self._ready_segments.append(segment)
        self._speech_buf.clear()
        self._in_speech = False
        self._silent_since = None
        log.debug("Flushed speech segment: %.1f s", len(segment) / self.sample_rate)

    def flush_remaining(self) -> None:
        """Force-flush any buffered audio (call on stream end)."""
        if self._speech_buf:
            self._flush_segment()

    def drain_segments(self) -> list[np.ndarray]:
        """Return and clear all completed speech segments."""
        segs = list(self._ready_segments)
        self._ready_segments.clear()
        return segs
