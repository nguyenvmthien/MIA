"""
WhisperX singleton for streaming transcription.

Loads the WhisperX model once at process start and reuses it across
WebSocket sessions. Thread-safe: a lock guards the transcribe() call since
WhisperX is not re-entrant.

Usage:
    from meeting_agent.pipeline.streaming_stt import transcribe_segment
    text = transcribe_segment(audio_np)  # audio_np: float32 [-1,1], 16 kHz mono
"""

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)

_lock = threading.Lock()
_model = None
_model_name = "base"   # override via WHISPER_STREAMING_MODEL env var


def _get_model():
    global _model
    if _model is not None:
        return _model
    import os
    model_name = os.environ.get("WHISPER_STREAMING_MODEL", _model_name)
    try:
        import whisperx  # type: ignore
        device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                device = "cuda"
        except ImportError:
            pass
        log.info("Loading WhisperX model '%s' on %s for streaming…", model_name, device)
        _model = whisperx.load_model(model_name, device=device, compute_type="int8")
        log.info("WhisperX streaming model ready")
    except ImportError as e:
        raise RuntimeError("whisperx not installed — pip install whisperx") from e
    return _model


def transcribe_segment(audio: np.ndarray, language: str = "vi") -> str:
    """
    Transcribe a single speech segment.

    Args:
        audio:    float32 numpy array, values in [-1, 1], 16 kHz mono
        language: ISO-639-1 language code (default 'vi' for Vietnamese)

    Returns:
        Concatenated transcript text, or empty string on failure.
    """
    if audio.dtype != np.float32:
        audio = audio.astype(np.float32) / 32768.0
    if audio.size == 0:
        return ""

    with _lock:
        model = _get_model()
        try:
            result = model.transcribe(audio, language=language, batch_size=4)
            segments = result.get("segments", [])
            return " ".join(s.get("text", "").strip() for s in segments).strip()
        except Exception as e:
            log.warning("WhisperX transcription failed: %s", e)
            return ""
