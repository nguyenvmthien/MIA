"""FastAPI application — entry point for the Meeting AI Agent REST API."""

import json
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from meeting_agent.config import settings
from meeting_agent.pipeline.feedback import FeedbackSubmission, feedback_stats, save_feedback
from meeting_agent.pipeline.router import router_stats
from meeting_agent.pipeline.worker_task import celery_app, check_retrain_task, process_meeting_task
from meeting_agent.schemas.worker import WorkerRoster


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.audio_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.transcript_storage_path).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Meeting AI Agent",
    description="Upload meeting audio → get structured action items",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


# ── Metrics (Prometheus) ──────────────────────────────────────────────────────

@app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
async def metrics():
    return PlainTextResponse(
        generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


# ── Meeting endpoints ─────────────────────────────────────────────────────────

@app.post("/meetings", status_code=status.HTTP_202_ACCEPTED, tags=["meetings"])
async def submit_meeting(
    audio: UploadFile = File(..., description="Audio or video file of the meeting"),
    roster_json: str = Form(
        default="{}",
        description='JSON WorkerRoster: {"workers": [{"worker_id": "w1", "name": "Alice", ...}]}',
    ),
):
    """
    Submit a meeting audio file for async processing.

    Returns a meeting_id that can be used to poll for results via GET /meetings/{id}.
    """
    # Validate roster JSON
    try:
        roster_dict = json.loads(roster_json)
        roster = WorkerRoster.model_validate(roster_dict)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid roster_json: {exc}")

    meeting_id = str(uuid.uuid4())

    # Save uploaded file to a temp path that the Celery worker can access
    suffix = Path(audio.filename or "audio.wav").suffix or ".wav"
    dest_dir = Path(settings.audio_storage_path) / meeting_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"upload{suffix}"

    with dest_path.open("wb") as f:
        shutil.copyfileobj(audio.file, f)

    # Dispatch async task
    process_meeting_task.apply_async(
        kwargs={
            "audio_path": str(dest_path),
            "roster_dict": roster.model_dump(),
            "meeting_id": meeting_id,
        },
        task_id=meeting_id,
    )

    return {"meeting_id": meeting_id, "status": "accepted"}


@app.get("/meetings/{meeting_id}", tags=["meetings"])
async def get_meeting(meeting_id: str):
    """
    Poll for the result of a previously submitted meeting job.

    Returns the full MeetingSummary JSON once processing is complete.
    """
    result = celery_app.AsyncResult(meeting_id)

    if result.state == "PENDING":
        return {"meeting_id": meeting_id, "status": "pending"}

    if result.state == "STARTED":
        return {"meeting_id": meeting_id, "status": "processing"}

    if result.state == "FAILURE":
        return JSONResponse(
            status_code=500,
            content={"meeting_id": meeting_id, "status": "failed", "error": str(result.result)},
        )

    if result.state == "SUCCESS":
        data = result.result  # already a dict (model_dump)
        data.setdefault("status", data.get("job_status", "completed"))
        return data

    return {"meeting_id": meeting_id, "status": result.state.lower()}


@app.post("/meetings/{meeting_id}/feedback", tags=["meetings"])
async def submit_feedback(meeting_id: str, submission: FeedbackSubmission):
    """
    Submit corrections to extracted tasks for a completed meeting.

    Corrections are stored and consumed by the retraining pipeline to
    continuously improve extraction quality (feedback loop).
    """
    for correction in submission.corrections:
        correction.meeting_id = meeting_id
    count = save_feedback(submission)
    return {"meeting_id": meeting_id, "corrections_saved": count}


@app.post("/admin/retrain", tags=["ops"])
async def trigger_retrain(force: bool = False):
    """
    Manually trigger the retraining pipeline.

    - force=false (default): only retrains if correction threshold is met
    - force=true: always retrain regardless of correction count

    The job runs asynchronously via Celery.
    """
    task = check_retrain_task.apply_async(kwargs={"force": force})
    return {"task_id": task.id, "status": "queued", "force": force}


@app.get("/admin/retrain/state", tags=["ops"])
async def get_retrain_state():
    """Return the current retraining state (last run, correction counts, history)."""
    import json
    from pathlib import Path
    state_file = Path("data/training/.retrain_state.json")
    if not state_file.exists():
        return {"last_correction_count": 0, "last_retrain_at": None, "runs": []}
    return json.loads(state_file.read_text())


@app.get("/admin/router-stats", tags=["ops"])
async def get_router_stats():
    """Per-endpoint health, in-flight count, and error rate for the inference router."""
    return router_stats()


@app.get("/feedback/stats", tags=["meetings"])
async def get_feedback_stats():
    """Return aggregate statistics about accumulated user feedback."""
    return feedback_stats()


@app.delete("/meetings/{meeting_id}", tags=["meetings"])
async def delete_meeting_data(meeting_id: str):
    """Delete stored audio and transcript data for a meeting (GDPR compliance)."""
    audio_dir = Path(settings.audio_storage_path) / meeting_id
    transcript_dir = Path(settings.transcript_storage_path) / meeting_id

    deleted = []
    for d in [audio_dir, transcript_dir]:
        if d.exists():
            shutil.rmtree(d)
            deleted.append(str(d))

    return {"meeting_id": meeting_id, "deleted_paths": deleted}
