"""FastAPI application — entry point for the Meeting AI Agent REST API."""

import json
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# Import metrics so they are registered in the API process (required for /metrics to expose them)
import meeting_agent.monitoring.metrics  # noqa: F401
from meeting_agent.api.calendar_router import router as calendar_router
from meeting_agent.api.ws_router import router as ws_router
from meeting_agent.config import settings
from meeting_agent.pipeline.feedback import FeedbackSubmission, feedback_stats, save_feedback
from meeting_agent.pipeline.router import router_stats
from meeting_agent.pipeline.worker_registry import add_worker, delete_worker, list_workers
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
    Worker(worker_id="w1", name="Alice Chen", role="PM",
           email="alice@example.com", aliases=["Alice"]),
    Worker(worker_id="w2", name="Bob Kim", role="Engineer",
           email="bob@example.com", aliases=["Bob"]),
    Worker(worker_id="w3", name="Carol Davis", role="Designer",
           email="carol@example.com", aliases=["Carol"]),
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
app.include_router(ws_router)


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


# ── A/B test admin endpoints ──────────────────────────────────────────────────

def _ab_module():
    import sys
    from pathlib import Path as _Path
    train_dir = str(_Path(__file__).parent.parent.parent.parent.parent / "train")
    if train_dir not in sys.path:
        sys.path.insert(0, train_dir)
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
    import uuid as _uuid
    import os as _os
    from datetime import datetime as _dt
    model_a = _os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")
    experiment_id = f"ab_{_dt.utcnow().strftime('%Y%m%d_%H%M%S')}"
    state = {
        "active": True,
        "experiment_id": experiment_id,
        "model_a": model_a,
        "model_b": req.model_b,
        "traffic_b": req.traffic,
        "started_at": _dt.utcnow().isoformat(),
    }
    ab.save_state(state)
    return state


@app.delete("/admin/ab-test/stop", tags=["ops"])
async def ab_test_stop():
    """Stop the active A/B test and return aggregated results."""
    ab = _ab_module()
    from datetime import datetime as _dt
    state = ab.load_state()
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="No active A/B test")
    state["active"] = False
    state["stopped_at"] = _dt.utcnow().isoformat()
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


@app.get("/feedback/stats", tags=["meetings"])
async def get_feedback_stats():
    """Return aggregate statistics about accumulated user feedback."""
    return feedback_stats()


# ── Worker registry endpoints ─────────────────────────────────────────────────

@app.get("/workers", tags=["workers"])
async def get_workers():
    """List all registered workers (the participant database)."""
    return {"workers": [w.model_dump() for w in list_workers()]}


@app.post("/workers", status_code=status.HTTP_201_CREATED, tags=["workers"])
async def create_worker(worker: Worker):
    """
    Add a new worker to the participant database.

    If a worker with the same name already exists, returns 409 Conflict.
    The worker_id is auto-generated if empty or not provided.
    """
    import uuid as _uuid
    if not worker.worker_id:
        worker = worker.model_copy(update={"worker_id": str(_uuid.uuid4())[:8]})
    try:
        created = add_worker(worker)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return created.model_dump()


@app.delete("/workers/{worker_id}", tags=["workers"])
async def remove_worker(worker_id: str):
    """Remove a worker from the participant database by worker_id."""
    found = delete_worker(worker_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return {"worker_id": worker_id, "deleted": True}


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
