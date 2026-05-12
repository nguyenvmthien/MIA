"""
Main pipeline runner — wires all stages together into a single batch job.

Called by the Celery worker or the CLI.
"""

import hashlib
import logging
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from meeting_agent.config import settings
from meeting_agent.monitoring.anomaly import check_run as anomaly_check
from meeting_agent.monitoring.metrics import (
    AUDIO_DURATION,
    PARTICIPANTS_COUNT,
    PIPELINE_ERRORS,
    TASKS_EXTRACTED,
    TASKS_PER_MEETING,
    TASKS_UNRESOLVED,
)
from meeting_agent.pipeline.assignment import resolve_assignments, resolve_participants
from meeting_agent.pipeline.ingest import ingest_audio
from meeting_agent.pipeline.orchestrator import extract_action_items, summarize_meeting
from meeting_agent.pipeline.preprocess import preprocess_audio
from meeting_agent.pipeline.stt import transcribe_and_diarize
from meeting_agent.schemas.meeting import JobStatus, MeetingSummary, RunMetrics, StageTiming
from meeting_agent.schemas.task import TaskStatus
from meeting_agent.schemas.worker import WorkerRoster

log = logging.getLogger(__name__)


def _file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_artifact(path: Path, artifact_type: str) -> dict:
    return {
        "artifact_type": artifact_type,
        "storage_uri": str(path),
        "checksum": _file_sha256(path),
        "metadata": {"bytes": path.stat().st_size if path.exists() else None},
    }


def run_pipeline(
    audio_path: str | Path,
    roster: WorkerRoster,
    meeting_id: str | None = None,
) -> MeetingSummary:
    """
    End-to-end pipeline: audio file → MeetingSummary with extracted action items.

    Stages:
        1. Ingest   — validate & store audio
        2. Preprocess — normalize to 16kHz mono WAV + noise reduction
        3. STT      — WhisperX ASR + Pyannote diarization
        4. Orchestrate — LLM summarization + action item extraction
        5. Assign   — worker resolution + confidence scoring
        6. Emit     — build MeetingSummary, record metrics
    """
    if meeting_id is None:
        meeting_id = str(uuid.uuid4())

    summary = MeetingSummary(
        meeting_id=meeting_id,
        audio_filename=Path(audio_path).name,
        job_status=JobStatus.processing,
        model_version=settings.ollama_llm_model,
    )
    timings = StageTiming()

    try:
        # ── Stage 1: Ingest ───────────────────────────────────────────────────
        t = time.monotonic()
        stored_path = ingest_audio(audio_path, meeting_id)
        summary.meeting_artifacts.append(_file_artifact(Path(stored_path), "uploaded_audio"))
        timings.ingest_ms = int((time.monotonic() - t) * 1000)

        # ── Stage 2: Preprocess ───────────────────────────────────────────────
        t = time.monotonic()
        clean_path = preprocess_audio(stored_path)
        raw_path = Path(stored_path).parent / "audio_raw.wav"
        if raw_path.exists():
            summary.meeting_artifacts.append(_file_artifact(raw_path, "raw_audio_wav"))
        summary.meeting_artifacts.append(_file_artifact(Path(clean_path), "clean_audio"))
        timings.preprocess_ms = int((time.monotonic() - t) * 1000)

        # ── Stage 3: STT + Diarization ────────────────────────────────────────
        t = time.monotonic()
        turns, duration_ms = transcribe_and_diarize(
            clean_path,
            artifact_sink=summary.meeting_artifacts,
        )
        timings.stt_ms = int((time.monotonic() - t) * 1000)

        summary.duration_ms = duration_ms
        participant_records = resolve_participants(turns, roster)
        summary.participants = sorted({p["display_name"] for p in participant_records})
        summary.meeting_participants = participant_records
        summary.transcript_turns = [
            {"speaker_id": t.speaker_id, "speaker_name": t.display_name,
             "start_ms": t.start_ms, "end_ms": t.end_ms, "text": t.text}
            for t in turns
        ]
        AUDIO_DURATION.observe(duration_ms / 1000)
        PARTICIPANTS_COUNT.observe(len(summary.participants))

        meeting_date = date.today().isoformat()

        # ── Stage 4: LLM — Summarize + Extract ───────────────────────────────
        t = time.monotonic()
        summary_text = summarize_meeting(
            turns,
            meeting_date,
            duration_ms,
            artifact_sink=summary.meeting_artifacts,
        )
        raw_tasks, total_tokens = extract_action_items(
            turns,
            roster,
            meeting_date,
            meeting_id,
            artifact_sink=summary.meeting_artifacts,
        )
        timings.llm_ms = int((time.monotonic() - t) * 1000)

        summary.summary_text = summary_text

        # ── Stage 5: Assignment ───────────────────────────────────────────────
        t = time.monotonic()
        resolved_tasks = resolve_assignments(raw_tasks, roster)
        timings.assignment_ms = int((time.monotonic() - t) * 1000)

        # ── Stage 6: Partition & emit ─────────────────────────────────────────
        for task in resolved_tasks:
            if task.status == TaskStatus.open:
                summary.action_items.append(task)
            elif task.status == TaskStatus.unresolved:
                summary.unresolved_items.append(task)
            else:
                summary.human_review_items.append(task)

        TASKS_EXTRACTED.inc(len(resolved_tasks))
        TASKS_UNRESOLVED.inc(
            len(summary.unresolved_items) + len(summary.human_review_items)
        )
        TASKS_PER_MEETING.observe(len(resolved_tasks))

        metrics = RunMetrics(
            total_tokens_used=total_tokens,
            tasks_extracted=len(resolved_tasks),
            tasks_unresolved=len(summary.unresolved_items),
            tasks_human_review=len(summary.human_review_items),
            stage_timings=timings,
        )
        summary.run_metrics = metrics

        # Anomaly detection on this run's metrics
        anomalies = anomaly_check(
            hallucination_flags=metrics.hallucination_flags,
            tasks_extracted=metrics.tasks_extracted,
            schema_failures=metrics.schema_validation_failures,
            llm_latency_ms=timings.llm_ms,
        )
        if anomalies:
            log.warning("Anomalies detected in meeting %s: %s", meeting_id, anomalies)

        summary.job_status = JobStatus.completed
        summary.processed_at = datetime.now(timezone.utc)

    except Exception as exc:
        summary.job_status = JobStatus.failed
        summary.error = str(exc)
        PIPELINE_ERRORS.labels(stage="run", error_type=type(exc).__name__).inc()
        raise

    return summary
