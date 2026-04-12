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
        return result.model_dump(mode="json")
    except Exception as exc:
        JOBS_TOTAL.labels(status="failed").inc()
        raise self.retry(exc=exc, max_retries=0)  # no retry at job level
    finally:
        JOBS_IN_FLIGHT.dec()
