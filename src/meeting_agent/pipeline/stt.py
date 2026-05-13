"""Stage 3 — STT + Diarization: WhisperX ASR + Pyannote speaker diarization."""

import json
import time
import uuid
import warnings
from pathlib import Path

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import STAGE_LATENCY
from meeting_agent.schemas.transcript import TranscriptTurn


class STTError(Exception):
    pass


def _word_majority_speaker(words: list[dict]) -> str | None:
    counts: dict[str, int] = {}
    for word in words:
        speaker = word.get("speaker")
        if speaker:
            counts[str(speaker)] = counts.get(str(speaker), 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda item: item[1])[0]


def transcribe_and_diarize(
    audio_path: Path,
    artifact_sink: list[dict] | None = None,
) -> tuple[list[TranscriptTurn], int]:
    """
    Run WhisperX ASR + Pyannote diarization on a preprocessed WAV file.

    Returns:
        - list of TranscriptTurn (one per speaker segment)
        - audio duration in milliseconds
    """
    try:
        import whisperx  # type: ignore
        from whisperx.diarize import DiarizationPipeline  # type: ignore
    except ImportError as e:
        raise STTError("whisperx not installed. Run: pip install whisperx") from e

    t0 = time.monotonic()

    # ── Load model ────────────────────────────────────────────────────────────
    model = whisperx.load_model(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
        language=settings.whisper_language,
    )

    audio = whisperx.load_audio(str(audio_path))
    duration_ms = int(len(audio) / 16000 * 1000)  # 16kHz

    # ── ASR ───────────────────────────────────────────────────────────────────
    result = model.transcribe(audio, batch_size=settings.whisper_batch_size)

    # ── Word-level alignment ──────────────────────────────────────────────────
    align_model, metadata = whisperx.load_align_model(
        language_code=result["language"],
        device=settings.whisper_device,
    )
    result = whisperx.align(
        result["segments"],
        align_model,
        metadata,
        audio,
        settings.whisper_device,
        return_char_alignments=False,
    )

    stt_ms = int((time.monotonic() - t0) * 1000)
    STAGE_LATENCY.labels(stage="stt").observe(stt_ms / 1000)

    # ── Diarization (optional for low-resource smoke tests) ──────────────────
    if settings.enable_diarization:
        t1 = time.monotonic()
        if not settings.hf_token:
            raise STTError(
                "HF_TOKEN is required for speaker diarization. "
                "Set it in .env after accepting pyannote/speaker-diarization-3.1 terms. "
                "Or set ENABLE_DIARIZATION=false for non-diarized testing."
            )

        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="torchcodec is not installed correctly.*",
                category=UserWarning,
            )
            diarize_pipeline = DiarizationPipeline(
                token=settings.hf_token,
                device=settings.whisper_device,
            )
            # Pass the already-loaded waveform instead of a path so pyannote
            # does not need torchcodec for audio decoding inside the container.
            diarize_segments = diarize_pipeline(audio)
        if artifact_sink is not None:
            artifact_sink.append({
                "artifact_type": "diarization_raw",
                "payload": {
                    "segments": json.loads(diarize_segments.to_json(orient="records")),
                },
                "metadata": {
                    "model": "pyannote/speaker-diarization-3.1",
                    "audio_path": str(audio_path),
                },
            })
        result = whisperx.assign_word_speakers(
            diarize_segments,
            result,
            fill_nearest=True,
        )

        diarize_ms = int((time.monotonic() - t1) * 1000)
        STAGE_LATENCY.labels(stage="diarize").observe(diarize_ms / 1000)

    if artifact_sink is not None:
        artifact_sink.append({
            "artifact_type": "asr_raw",
            "payload": json.loads(json.dumps(result, default=str)),
            "metadata": {
                "whisper_model": settings.whisper_model,
                "language": result.get("language"),
                "audio_path": str(audio_path),
            },
        })

    # ── Build TranscriptTurn list ─────────────────────────────────────────────
    turns: list[TranscriptTurn] = []
    for seg in result["segments"]:
        words = seg.get("words", [])
        speaker_id = seg.get("speaker") or _word_majority_speaker(words) or "SPEAKER_UNKNOWN"
        confidences = [w.get("score", 1.0) for w in words if "score" in w]
        avg_conf = float(sum(confidences) / len(confidences)) if confidences else 1.0

        turn = TranscriptTurn(
            turn_id=str(uuid.uuid4()),
            speaker_id=speaker_id,
            start_ms=int(seg["start"] * 1000),
            end_ms=int(seg["end"] * 1000),
            text=seg["text"].strip(),
            asr_confidence=round(avg_conf, 4),
        )
        turns.append(turn)

    return turns, duration_ms
