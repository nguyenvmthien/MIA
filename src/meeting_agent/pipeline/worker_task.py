"""Celery task definition for async meeting processing."""

import logging
import sys
from datetime import datetime
from pathlib import Path

from celery import Celery

from meeting_agent.config import settings

log = logging.getLogger(__name__)

_TRAIN_DIR = str(Path(__file__).parent.parent.parent.parent / "train")


def _ensure_train_path() -> None:
    if _TRAIN_DIR not in sys.path:
        sys.path.insert(0, _TRAIN_DIR)

celery_app = Celery(
    "meeting_agent",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Celery Beat — periodic retraining check every 24 hours
    beat_schedule={
        "check-retrain-daily": {
            "task": "meeting_agent.check_retrain",
            "schedule": 60 * 60 * 24,
        },
        "drift-check-weekly": {
            "task": "meeting_agent.drift_check",
            "schedule": 60 * 60 * 24 * 7,
        },
    },
)


@celery_app.task(name="meeting_agent.check_retrain")
def check_retrain_task() -> dict:
    """Periodic task: check feedback threshold and trigger retraining if met."""
    _ensure_train_path()
    from retrain import run_retrain  # type: ignore
    result = run_retrain()
    return result


@celery_app.task(name="meeting_agent.drift_check")
def drift_check_task() -> dict:
    """Weekly task: compute PSI drift and weekly correction/FP rate comparison."""
    from meeting_agent.monitoring.anomaly import check_weekly_drift

    weekly = check_weekly_drift()
    log.info("Weekly drift check: status=%s alerts=%s", weekly.get("status"), weekly.get("alerts"))
    if weekly.get("status") == "alert":
        log.warning("WEEKLY DRIFT ALERT: %s", weekly.get("alerts"))

    # Also run PSI-based drift check if train/ is available
    try:
        _ensure_train_path()
        from drift_detector import run_drift_check  # type: ignore
        psi = run_drift_check()
        log.info("PSI drift check: overall=%s max_psi=%.4f",
                 psi.get("overall_level"), psi.get("max_psi", 0))
        weekly["psi"] = psi
    except Exception as exc:
        log.debug("PSI drift check skipped: %s", exc)

    return weekly


@celery_app.task(bind=True, name="meeting_agent.process_meeting")
def process_meeting_task(self, audio_path: str, roster_dict: dict, meeting_id: str) -> dict:
    """
    Celery task: run the full pipeline and return MeetingSummary as a dict.
    Called by the API after accepting an upload.
    """
    from meeting_agent.monitoring.metrics import JOBS_IN_FLIGHT, JOBS_TOTAL
    from meeting_agent.pipeline.run import run_pipeline
    from meeting_agent.schemas.worker import WorkerRoster

    JOBS_IN_FLIGHT.inc()
    try:
        roster = WorkerRoster.model_validate(roster_dict)
        result = run_pipeline(audio_path, roster, meeting_id=meeting_id)
        JOBS_TOTAL.labels(status="completed").inc()
        result_dict = result.model_dump(mode="json")

        # Persist full result to PostgreSQL (primary store)
        _persist_to_db(result_dict, meeting_id)

        # Log drift features for PSI monitoring
        _log_drift_record(result_dict, meeting_id)

        return result_dict
    except Exception as exc:
        JOBS_TOTAL.labels(status="failed").inc()
        # Mark the meeting as failed in the DB before propagating
        _mark_failed_in_db(meeting_id, str(exc))
        raise self.retry(exc=exc, max_retries=0)  # no retry at job level
    finally:
        JOBS_IN_FLIGHT.dec()


def _persist_to_db(result_dict: dict, meeting_id: str) -> None:
    """Write the completed MeetingSummary to PostgreSQL (best-effort, non-fatal)."""
    try:
        from meeting_agent.db.repository import upsert_meeting_result
        upsert_meeting_result(result_dict)
    except Exception as exc:
        log.error("Failed to persist meeting %s to DB (result still in Redis): %s", meeting_id, exc)


def _mark_failed_in_db(meeting_id: str, error: str) -> None:
    """Update the meeting row to status=failed (best-effort)."""
    try:
        from meeting_agent.db.repository import upsert_meeting_result
        upsert_meeting_result({
            "meeting_id": meeting_id,
            "job_status": "failed",
            "processed_at": datetime.utcnow().isoformat(),
            "error": error,
            "action_items": [],
            "unresolved_items": [],
            "human_review_items": [],
        })
    except Exception:
        pass


def _log_drift_record(result_dict: dict, meeting_id: str) -> None:
    try:
        _ensure_train_path()
        from drift_detector import append_record  # type: ignore

        tasks = result_dict.get("action_items", [])
        n_tasks = len(tasks)
        token_counts = [t.get("token_count", 0) for t in tasks if t.get("token_count")]
        avg_tokens = sum(token_counts) / len(token_counts) if token_counts else 0
        hallucinated = sum(1 for t in tasks if t.get("hallucination_flag", False))
        assigned = sum(1 for t in tasks if t.get("assignee"))
        halluc_rate = hallucinated / n_tasks if n_tasks > 0 else 0.0
        assignee_rate = assigned / n_tasks if n_tasks > 0 else 0.0

        append_record({
            "meeting_id": meeting_id,
            "tasks_extracted": n_tasks,
            "avg_token_count": avg_tokens,
            "hallucination_rate": halluc_rate,
            "assignee_hit_rate": assignee_rate,
        })
    except Exception as e:
        log.debug("Drift record logging failed (non-fatal): %s", e)
