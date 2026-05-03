"""Celery task definition for async meeting processing."""

from celery import Celery

from meeting_agent.config import settings

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
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "train"))
    from retrain import run_retrain  # type: ignore
    result = run_retrain()
    return result


@celery_app.task(name="meeting_agent.drift_check")
def drift_check_task() -> dict:
    """Weekly task: compute PSI drift and log alert if threshold exceeded."""
    import sys
    from pathlib import Path
    import logging
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "train"))
    from drift_detector import run_drift_check  # type: ignore
    report = run_drift_check()
    _log = logging.getLogger(__name__)
    _log.info("Drift check: overall=%s max_psi=%.4f",
              report.get("overall_level"), report.get("max_psi", 0))
    if report.get("overall_level") == "alert":
        _log.warning("DRIFT ALERT detected — consider retraining. max_psi=%.4f", report.get("max_psi", 0))
    return report


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

        # Log drift features for PSI monitoring
        _log_drift_record(result_dict, meeting_id)

        return result_dict
    except Exception as exc:
        JOBS_TOTAL.labels(status="failed").inc()
        raise self.retry(exc=exc, max_retries=0)  # no retry at job level
    finally:
        JOBS_IN_FLIGHT.dec()


def _log_drift_record(result_dict: dict, meeting_id: str) -> None:
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "train"))
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
        import logging
        logging.getLogger(__name__).debug("Drift record logging failed (non-fatal): %s", e)
