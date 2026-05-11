"""FastAPI application — entry point for the Meeting AI Agent REST API."""

import json
import logging
import os
import shutil
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

# Import metrics so they are registered in the API process (required for /metrics to expose them)
import meeting_agent.monitoring.metrics  # noqa: F401
from meeting_agent.api.calendar_router import router as calendar_router
from meeting_agent.config import settings
from meeting_agent.db.repository import (
    delete_meeting as db_delete_meeting,
)
from meeting_agent.db.repository import (
    get_business_metrics as db_get_business_metrics,
)
from meeting_agent.db.repository import (
    get_meeting as db_get_meeting,
)
from meeting_agent.db.repository import (
    insert_meeting_stub,
)
from meeting_agent.db.repository import (
    list_meetings as db_list_meetings,
)
from meeting_agent.db.repository import (
    resolve_participant as db_resolve_participant,
)
from meeting_agent.pipeline.feedback import FeedbackSubmission, feedback_stats, save_feedback
from meeting_agent.pipeline.router import router_stats
from meeting_agent.pipeline.worker_registry import (
    add_worker,
    delete_worker,
    list_workers,
    update_worker,
)
from meeting_agent.pipeline.worker_task import celery_app, check_retrain_task, process_meeting_task
from meeting_agent.schemas.worker import Worker, WorkerRoster

# ── HTTP instrumentation metrics ──────────────────────────────────────────────
_HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests",
    labelnames=["method", "endpoint", "status_code"],
)
_HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    labelnames=["method", "endpoint"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5],
)

    
STATIC_DIR = Path(__file__).parent / "static"


_SEED_WORKERS = [
    Worker(worker_id="w1", name="Alice Chen", role="Manager",
           email="thien792003@gmail.com", aliases=["Alice"]),
    Worker(worker_id="w2", name="Bob Kim", role="Engineer",
           email="jamesnguyen070903@gmail.com", aliases=["Bob", "Bobby"]),
    Worker(worker_id="w3", name="Carol Davis", role="Engineer",
           email="minhthien792003@gmail.com", aliases=["Carol"]),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.audio_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.transcript_storage_path).mkdir(parents=True, exist_ok=True)
    # Seed worker DB with example workers if empty
    if not list_workers():
        for w in _SEED_WORKERS:
            try:
                add_worker(w)
            except ValueError:
                pass
    yield


app = FastAPI(
    title="Meeting AI Agent",
    description="Upload meeting audio → get structured action items",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", os.environ.get("FRONTEND_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(calendar_router)


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    # Normalise dynamic path segments so cardinality stays low
    path = request.url.path
    if path.startswith("/meetings/") and len(path.split("/")) > 2:
        path = "/meetings/{meeting_id}"
    elif path.startswith("/workers/") and len(path.split("/")) > 2:
        path = "/workers/{worker_id}"
    _HTTP_REQUESTS.labels(  # noqa: E501
        method=request.method, endpoint=path, status_code=response.status_code
    ).inc()
    _HTTP_DURATION.labels(method=request.method, endpoint=path).observe(duration)
    return response


@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Meeting AI Agent API", "docs": "/docs", "ui": "http://localhost:8501"}


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

    # Insert a pending row in the DB immediately so the meeting is queryable
    # even before the Celery worker picks up the job.
    try:
        insert_meeting_stub(meeting_id, audio.filename)
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not insert meeting stub (non-fatal): %s", exc)

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

    Strategy:
      1. If the job is still in-flight (Redis says PENDING/STARTED), return live status.
      2. Once complete, serve the persisted result from PostgreSQL (canonical, permanent).
      3. Fall back to the Redis Celery result if the DB row isn't there yet.
    """
    celery_result = celery_app.AsyncResult(meeting_id)

    # Job is still running — skip DB lookup
    if celery_result.state in ("PENDING", "STARTED"):
        status_str = "pending" if celery_result.state == "PENDING" else "processing"
        return {"meeting_id": meeting_id, "status": status_str}

    # Job failed according to Celery
    if celery_result.state == "FAILURE":
        db_row = db_get_meeting(meeting_id)
        if db_row:
            return db_row
        return JSONResponse(
            status_code=500,
            content={"meeting_id": meeting_id, "status": "failed", "error": str(celery_result.result)},
        )

    # Job succeeded — serve from DB (authoritative, survives Redis TTL expiry)
    if celery_result.state == "SUCCESS":
        db_row = db_get_meeting(meeting_id)
        if db_row:
            db_row.setdefault("status", db_row.get("job_status", "completed"))
            return db_row
        # DB persist may still be in-flight — fall back to Redis payload
        data = celery_result.result
        data.setdefault("status", data.get("job_status", "completed"))
        return data

    # Unknown state — try DB, then return raw state
    db_row = db_get_meeting(meeting_id)
    if db_row:
        return db_row
    return {"meeting_id": meeting_id, "status": celery_result.state.lower()}


@app.post("/meetings/{meeting_id}/feedback", tags=["meetings"])
async def submit_feedback(meeting_id: str, submission: FeedbackSubmission):
    """
    Submit corrections to extracted tasks for a completed meeting.

    Corrections are stored and consumed by the retraining pipeline to
    continuously improve extraction quality (feedback loop).
    """
    from meeting_agent.monitoring.metrics import (
        CORRECTION_RATE,
        FALSE_POSITIVE_RATE,
        TASKS_CONFIRMED,
        TASKS_DISMISSED,
        TASKS_EDITED,
        TRAINING_SAMPLES_READY,
    )
    for correction in submission.corrections:
        correction.meeting_id = meeting_id
    count = save_feedback(submission)

    # Fire interaction metrics per correction
    for c in submission.corrections:
        if getattr(c, "is_false_positive", False):
            TASKS_DISMISSED.inc()
        else:
            TASKS_CONFIRMED.inc()
            if getattr(c, "corrected_description", None):
                TASKS_EDITED.labels(field="description").inc()
            if getattr(c, "corrected_assignee", None):
                TASKS_EDITED.labels(field="assignee").inc()
            if getattr(c, "corrected_due_date", None):
                TASKS_EDITED.labels(field="due_date").inc()

    # Update rolling business KPI gauges from DB (async-safe: lightweight query)
    try:
        biz = db_get_business_metrics()
        CORRECTION_RATE.set(biz["correction_rate"])
        FALSE_POSITIVE_RATE.set(biz["false_positive_rate"])
        TRAINING_SAMPLES_READY.set(biz["training_ready_samples"])
    except Exception:
        pass

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
    state_file = Path("data/training/.retrain_state.json")
    if not state_file.exists():
        return {"last_correction_count": 0, "last_retrain_at": None, "runs": []}
    return json.loads(state_file.read_text())


@app.get("/admin/router-stats", tags=["ops"])
async def get_router_stats():
    """Per-endpoint health, in-flight count, and error rate for the inference router."""
    return router_stats()


# ── A/B test admin endpoints ──────────────────────────────────────────────────

_TRAIN_DIR = str(Path(__file__).parent.parent.parent.parent.parent / "train")


def _ab_module():
    if _TRAIN_DIR not in sys.path:
        sys.path.insert(0, _TRAIN_DIR)
    import ab_test
    return ab_test


@app.get("/admin/ab-test/status", tags=["ops"])
async def ab_test_status():
    """Return current A/B test state."""
    ab = _ab_module()
    return ab.load_state()


class ABTestStartRequest(BaseModel):
    model_b: str
    traffic: float = 0.1


@app.post("/admin/ab-test/start", tags=["ops"])
async def ab_test_start(req: ABTestStartRequest):
    """Start an A/B test between the current champion and a challenger model."""
    if req.traffic <= 0 or req.traffic >= 1:
        raise HTTPException(status_code=422, detail="traffic must be between 0 and 1 exclusive")
    ab = _ab_module()
    model_a = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")
    experiment_id = f"ab_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
    state = {
        "active": True,
        "experiment_id": experiment_id,
        "model_a": model_a,
        "model_b": req.model_b,
        "traffic_b": req.traffic,
        "started_at": datetime.utcnow().isoformat(),
    }
    ab.save_state(state)
    return state


@app.delete("/admin/ab-test/stop", tags=["ops"])
async def ab_test_stop():
    """Stop the active A/B test and return aggregated results."""
    ab = _ab_module()
    state = ab.load_state()
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="No active A/B test")
    state["active"] = False
    state["stopped_at"] = datetime.utcnow().isoformat()
    ab.save_state(state)
    results = ab.get_results(state["experiment_id"])
    return {"state": state, "results": results}


@app.get("/admin/ab-test/results", tags=["ops"])
async def ab_test_results():
    """Return aggregated A/B test results for the current (or last) experiment."""
    ab = _ab_module()
    results = ab.get_results()
    if not results:
        raise HTTPException(status_code=404, detail="No experiment results found")
    return results


@app.get("/metrics/business", tags=["ops"])
async def business_metrics():
    """
    Business KPIs computed from DB — suitable for Grafana JSON datasource panels.

    Returns correction rate, false positive rate, training data accumulation,
    and per-model-version breakdown for drift detection.
    """
    return db_get_business_metrics()


@app.get("/feedback/stats", tags=["meetings"])
async def get_feedback_stats():
    """Return aggregate statistics about accumulated user feedback."""
    return feedback_stats()


@app.get("/feedback/export", tags=["meetings"])
async def export_feedback_for_finetuning(limit: int = 500, format: str = "raw"):
    """
    Export human-reviewed meeting data as fine-tuning examples.

    format=raw   → full objects (default, for inspection)
    format=jsonl → instruction/input/output format ready for finetune.py
    format=rlhf  → chosen/rejected pairs for preference training
    """
    from meeting_agent.db.engine import get_session
    from meeting_agent.db.models import FeedbackCorrection, Meeting, Task

    SYSTEM_INSTRUCTION = (
        "You are an AI assistant that extracts action items from meeting transcripts. "
        "Given the meeting transcript below, extract all action items as a JSON array. "
        "Each item must have: description, assignee (null if unknown), due_date (YYYY-MM-DD or null), priority (high/medium/low)."
    )

    with get_session() as session:
        meeting_ids = [
            row[0]
            for row in session.query(FeedbackCorrection.meeting_id)
            .distinct()
            .limit(limit)
            .all()
        ]

        examples = []
        for mid in meeting_ids:
            meeting = session.get(Meeting, mid)
            if meeting is None or meeting.status not in ("completed", "done"):
                continue

            tasks = (
                session.query(Task)
                .filter_by(meeting_id=mid)
                .filter(Task.bucket == "action")
                .filter(Task.status != "dismissed")
                .all()
            )
            corrections = session.query(FeedbackCorrection).filter_by(meeting_id=mid).all()

            ground_truth = [
                {
                    "description": t.description,
                    "assignee": t.assignee,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                    "priority": t.priority,
                }
                for t in tasks
            ]

            # Build transcript text from stored turns, fall back to summary
            turns = meeting.transcript_turns or []
            if turns:
                transcript_text = "\n".join(
                    f"[{t.get('speaker_name', t.get('speaker_id', 'Speaker'))}]: {t.get('text', '')}"
                    for t in turns
                )
            else:
                transcript_text = meeting.summary_text or ""

            if format == "jsonl":
                examples.append({
                    "instruction": SYSTEM_INSTRUCTION,
                    "input": transcript_text,
                    "output": json.dumps(ground_truth, ensure_ascii=False),
                    "model_version": meeting.model_version,
                })
            elif format == "rlhf":
                # Chosen = human-corrected ground truth
                # Rejected = original model output (before corrections)
                original_tasks = [
                    {
                        "description": c.original_description,
                        "assignee": c.original_assignee,
                        "due_date": c.original_due_date.isoformat() if c.original_due_date else None,
                    }
                    for c in corrections if not c.is_false_positive and c.original_description
                ]
                if ground_truth and original_tasks:
                    examples.append({
                        "prompt": f"{SYSTEM_INSTRUCTION}\n\nTranscript:\n{transcript_text}",
                        "chosen": json.dumps(ground_truth, ensure_ascii=False),
                        "rejected": json.dumps(original_tasks, ensure_ascii=False),
                        "meeting_id": mid,
                        "model_version": meeting.model_version,
                        "num_corrections": len(corrections),
                        "has_false_positives": any(c.is_false_positive for c in corrections),
                    })
            else:
                examples.append({
                    "meeting_id": mid,
                    "summary_text": meeting.summary_text,
                    "transcript_turns": len(turns),
                    "participants": meeting.participants,
                    "ground_truth_tasks": ground_truth,
                    "corrections_applied": len(corrections),
                    "has_false_positives": any(c.is_false_positive for c in corrections),
                    "has_missing_tasks": any(c.is_missing for c in corrections),
                    "model_version": meeting.model_version,
                })

    return {"count": len(examples), "examples": examples}


# ── Worker registry endpoints ─────────────────────────────────────────────────

@app.get("/workers", tags=["workers"])
async def get_workers():
    """List all registered workers (the participant database)."""
    return {"workers": [w.model_dump() for w in list_workers()]}


class WorkerCreate(BaseModel):
    name: str
    aliases: list[str] = []
    role: str | None = None
    email: str | None = None
    skills: list[str] = []


@app.post("/workers", status_code=status.HTTP_201_CREATED, tags=["workers"])
async def create_worker(body: WorkerCreate):
    """
    Add a new worker to the participant database.

    If a worker with the same name already exists, returns 409 Conflict.
    The worker_id is auto-generated.
    """
    worker = Worker(
        worker_id=str(uuid.uuid4())[:8],
        name=body.name,
        aliases=body.aliases,
        role=body.role,
        email=body.email,
        skills=body.skills,
    )
    try:
        created = add_worker(worker)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return created.model_dump()


@app.put("/workers/{worker_id}", tags=["workers"])
async def edit_worker(worker_id: str, worker: Worker):
    """Update an existing worker's fields by worker_id."""
    result = update_worker(worker_id, worker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return result.model_dump()


@app.delete("/workers/{worker_id}", tags=["workers"])
async def remove_worker(worker_id: str):
    """Remove a worker from the participant database by worker_id."""
    found = delete_worker(worker_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return {"worker_id": worker_id, "deleted": True}


@app.get("/meetings", tags=["meetings"])
async def list_meetings(limit: int = 50, offset: int = 0):
    """List all meetings, newest first. Returns summary cards (no tasks/transcripts)."""
    return {"meetings": db_list_meetings(limit=limit, offset=offset)}


class ResolveParticipantRequest(BaseModel):
    worker_id: str
    display_name: str


@app.post("/meetings/{meeting_id}/participants/{speaker_id}/resolve", tags=["meetings"])
async def resolve_participant(meeting_id: str, speaker_id: str, body: ResolveParticipantRequest):
    """Map an unresolved speaker label to a roster worker."""
    ok = db_resolve_participant(meeting_id, speaker_id, body.worker_id, body.display_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Participant '{speaker_id}' not found in meeting '{meeting_id}'.")
    return {"meeting_id": meeting_id, "speaker_id": speaker_id, "resolved_to": body.display_name}


@app.delete("/meetings/{meeting_id}", tags=["meetings"])
async def delete_meeting_data(meeting_id: str):
    """Delete stored audio, transcript data, and DB rows for a meeting (GDPR compliance)."""
    audio_dir = Path(settings.audio_storage_path) / meeting_id
    transcript_dir = Path(settings.transcript_storage_path) / meeting_id

    deleted = []
    for d in [audio_dir, transcript_dir]:
        if d.exists():
            shutil.rmtree(d)
            deleted.append(str(d))

    db_deleted = db_delete_meeting(meeting_id)

    return {"meeting_id": meeting_id, "deleted_paths": deleted, "db_deleted": db_deleted}
