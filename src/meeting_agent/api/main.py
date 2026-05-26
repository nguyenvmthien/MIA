"""FastAPI application — entry point for the Meeting AI Agent REST API."""

import json
import logging
import os
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

# Import metrics so they are registered in the API process (required for /metrics to expose them)
import meeting_agent.monitoring.metrics  # noqa: F401
from meeting_agent.api.auth import Principal, auth_is_configured, require_admin, require_user
from meeting_agent.api.calendar_router import router as calendar_router
from meeting_agent.config import settings
from meeting_agent.db.repository import (
    delete_meeting as db_delete_meeting,
)
from meeting_agent.db.repository import (
    fail_stale_pending_meetings as db_fail_stale_pending_meetings,
)
from meeting_agent.db.repository import (
    get_business_metrics as db_get_business_metrics,
)
from meeting_agent.db.repository import (
    get_meeting as db_get_meeting,
)
from meeting_agent.db.repository import (
    insert_meeting_stub,
    upsert_meeting_result,
)
from meeting_agent.db.repository import (
    list_meetings as db_list_meetings,
)
from meeting_agent.db.repository import (
    resolve_participant as db_resolve_participant,
)
from meeting_agent.pipeline.feedback import FeedbackSubmission, feedback_stats, save_feedback
from meeting_agent.pipeline.ingest import (
    MAX_BYTES,
    SUPPORTED_FORMATS,
    IngestError,
    validate_audio_content,
)
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


_LEGACY_SEED_WORKER_IDS = {"w1", "w2", "w3"}

_SEED_WORKERS = [
    Worker(worker_id="e365fb28", name="Carol White", role="UX Designer", email="carol.white@example.com", aliases=["Carol", "White", "carol"]),
    Worker(worker_id="02946910", name="David Lee", role="QA Engineer", email="david.lee@example.com", aliases=["David", "Lee", "david"]),
    Worker(worker_id="1977d792", name="Eva Martinez", role="DevOps Engineer", email="eva.martinez@example.com", aliases=["Eva", "Martinez", "eva"]),
    Worker(worker_id="4a3985f7", name="Frank Nguyen", role="Frontend Developer", email="frank.nguyen@example.com", aliases=["Frank", "Nguyen", "frank"]),
    Worker(worker_id="809c3ce2", name="Grace Park", role="Engineering Manager", email="grace.park@example.com", aliases=["Grace", "Park", "grace"]),
    Worker(worker_id="f651c2a5", name="Henry Zhou", role="Data Engineer", email="henry.zhou@example.com", aliases=["Henry", "Zhou", "henry"]),
    Worker(worker_id="613b2885", name="Isabelle Durand", role="Marketing Manager", email="isabelle.durand@example.com", aliases=["Isabelle", "Durand", "isabelle"]),
    Worker(worker_id="16b89e06", name="Jake Thompson", role="Content Strategist", email="jake.thompson@example.com", aliases=["Jake", "Thompson", "jake"]),
    Worker(worker_id="72280322", name="Karen Patel", role="Brand Designer", email="karen.patel@example.com", aliases=["Karen", "Patel", "karen"]),
    Worker(worker_id="e9ed1a02", name="Liam O'Brien", role="Growth Marketer", email="liam.obrien@example.com", aliases=["Liam", "O'Brien", "liam"]),
    Worker(worker_id="21daa3f8", name="Maya Singh", role="Social Media Manager", email="maya.singh@example.com", aliases=["Maya", "Singh", "maya"]),
    Worker(worker_id="1051d317", name="Nathan Brooks", role="SEO Specialist", email="nathan.brooks@example.com", aliases=["Nathan", "Brooks", "nathan"]),
    Worker(worker_id="43a8ec9b", name="Olivia Zhang", role="CFO", email="olivia.zhang@example.com", aliases=["Olivia", "Zhang", "olivia"]),
    Worker(worker_id="15451f0e", name="Peter Walsh", role="Financial Analyst", email="peter.walsh@example.com", aliases=["Peter", "Walsh", "peter"]),
    Worker(worker_id="490b21dd", name="Quinn Adams", role="Accountant", email="quinn.adams@example.com", aliases=["Quinn", "Adams", "quinn"]),
    Worker(worker_id="c0a8df2d", name="Rachel Kim", role="Budget Controller", email="rachel.kim@example.com", aliases=["Rachel", "Kim", "rachel"]),
    Worker(worker_id="03f79533", name="Samuel Torres", role="Treasury Manager", email="samuel.torres@example.com", aliases=["Samuel", "Torres", "samuel"]),
    Worker(worker_id="b18aabf6", name="Tina Muller", role="Sales Director", email="tina.muller@example.com", aliases=["Tina", "Muller", "tina"]),
    Worker(worker_id="aacccab6", name="Umar Hassan", role="Account Executive", email="umar.hassan@example.com", aliases=["Umar", "Hassan", "umar"]),
    Worker(worker_id="507d3978", name="Vanessa Li", role="Customer Success Manager", email="vanessa.li@example.com", aliases=["Vanessa", "Li", "vanessa"]),
    Worker(worker_id="8aa0e74c", name="William Clark", role="Business Development Manager", email="william.clark@example.com", aliases=["William", "Clark", "william"]),
    Worker(worker_id="132d49a3", name="Xiao Feng", role="Partnership Manager", email="xiao.feng@example.com", aliases=["Xiao", "Feng", "xiao"]),
    Worker(worker_id="0e991bdb", name="Yuki Tanaka", role="Operations Manager", email="yuki.tanaka@example.com", aliases=["Yuki", "Tanaka", "yuki"]),
    Worker(worker_id="602577cc", name="Zoe Hernandez", role="HR Manager", email="zoe.hernandez@example.com", aliases=["Zoe", "Hernandez", "zoe"]),
    Worker(worker_id="d7af6df0", name="Aaron Scott", role="Supply Chain Manager", email="aaron.scott@example.com", aliases=["Aaron", "Scott", "aaron"]),
    Worker(worker_id="8398f771", name="Bella Johnson", role="Talent Acquisition", email="bella.johnson@example.com", aliases=["Bella", "Johnson", "bella"]),
    Worker(worker_id="e37fbb2f", name="Carlos Rivera", role="Office Manager", email="carlos.rivera@example.com", aliases=["Carlos", "Rivera", "carlos"]),
    Worker(worker_id="14c549c7", name="Diana Moore", role="Legal Counsel", email="diana.moore@example.com", aliases=["Diana", "Moore", "diana"]),
    Worker(worker_id="fc57e13b", name="Edward Hill", role="Compliance Officer", email="edward.hill@example.com", aliases=["Edward", "Hill", "edward"]),
    Worker(worker_id="a9f54575", name="Fiona Campbell", role="CEO", email="fiona.campbell@example.com", aliases=["Fiona", "Campbell", "fiona"]),
    Worker(worker_id="ac9db293", name="George Baker", role="COO", email="george.baker@example.com", aliases=["George", "Baker", "george"]),
    Worker(worker_id="c624f6ce", name="Hannah Morris", role="Product Manager", email="hannah.morris@example.com", aliases=["Hannah", "Morris", "hannah"]),
    Worker(worker_id="d939e2f0", name="Ian Wright", role="Backend Developer", email="ian.wright@example.com", aliases=["Ian", "Wright", "ian"]),
]

_STALE_PENDING_ERROR = (
    "Meeting processing did not start before the pending timeout. "
    "The job may have been lost during a service restart; please submit the file again."
)


def _parse_api_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fail_stale_pending_meeting(db_row: dict | None) -> dict | None:
    if not db_row or db_row.get("job_status") != "pending":
        return None
    created_at = _parse_api_datetime(db_row.get("created_at"))
    if created_at is None:
        return None
    timeout = timedelta(minutes=max(settings.pending_meeting_timeout_minutes, 1))
    if datetime.now(timezone.utc) - created_at < timeout:
        return None

    meeting_id = db_row["meeting_id"]
    upsert_meeting_result({
        "meeting_id": meeting_id,
        "job_status": "failed",
        "owner_user_id": db_row.get("owner_user_id"),
        "audio_filename": db_row.get("audio_filename"),
        "processed_at": datetime.now(timezone.utc),
        "error": _STALE_PENDING_ERROR,
    })
    refreshed = db_get_meeting(meeting_id, owner_user_id=db_row.get("owner_user_id"))
    return refreshed or {
        "meeting_id": meeting_id,
        "status": "failed",
        "job_status": "failed",
        "error": _STALE_PENDING_ERROR,
    }


def _owner_scope(principal: Principal) -> str | None:
    if not auth_is_configured() or principal.is_admin:
        return None
    return principal.user_id


def _validated_upload_suffix(filename: str | None) -> str:
    suffix = Path(filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in SUPPORTED_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_FORMATS))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported audio format '{suffix}'. Supported: {supported}",
        )
    return suffix


def _copy_upload_with_limit(upload: UploadFile, dest_path: Path) -> int:
    bytes_written = 0
    with dest_path.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            if bytes_written > MAX_BYTES:
                dest_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Uploaded file is too large. Max allowed for "
                        f"{settings.max_audio_duration_hours}h audio."
                    ),
                )
            f.write(chunk)
    return bytes_written


@asynccontextmanager
async def lifespan(app: FastAPI):
    Path(settings.audio_storage_path).mkdir(parents=True, exist_ok=True)
    Path(settings.transcript_storage_path).mkdir(parents=True, exist_ok=True)
    try:
        db_fail_stale_pending_meetings(
            settings.pending_meeting_timeout_minutes,
            _STALE_PENDING_ERROR,
        )
    except Exception as exc:
        logging.getLogger(__name__).debug("Stale pending cleanup skipped on startup: %s", exc)
    existing = list_workers()
    if existing and {w.worker_id for w in existing}.issubset(_LEGACY_SEED_WORKER_IDS):
        for worker in existing:
            delete_worker(worker.worker_id)
        existing = []
    existing_ids = {w.worker_id for w in existing}
    existing_names = {w.name.lower() for w in existing}
    for w in _SEED_WORKERS:
        if w.worker_id in existing_ids or w.name.lower() in existing_names:
            continue
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
    return {
        "message": "Meeting AI Agent API",
        "docs": "/docs",
        "ui": os.environ.get("FRONTEND_URL", "http://localhost:3001"),
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok"}


# ── Metrics (Prometheus) ──────────────────────────────────────────────────────

@app.get("/metrics", tags=["ops"], response_class=PlainTextResponse)
async def metrics():
    try:
        from meeting_agent.monitoring.metrics import (
            CORRECTION_RATE,
            DB_FEEDBACK_TOTAL,
            DB_MEETINGS_TOTAL,
            DB_MODEL_MEETINGS_TOTAL,
            DB_TASKS_TOTAL,
            FALSE_POSITIVE_RATE,
            TRAINING_SAMPLES_READY,
        )

        db_fail_stale_pending_meetings(
            settings.pending_meeting_timeout_minutes,
            _STALE_PENDING_ERROR,
        )
        biz = db_get_business_metrics()
        CORRECTION_RATE.set(biz["correction_rate"])
        FALSE_POSITIVE_RATE.set(biz["false_positive_rate"])
        TRAINING_SAMPLES_READY.set(biz["training_ready_samples"])
        for status_name in ("pending", "processing", "completed", "failed"):
            DB_MEETINGS_TOTAL.labels(status=status_name).set(
                biz.get("meetings_by_status", {}).get(status_name, 0)
            )
        for bucket in ("action", "unresolved", "human_review"):
            DB_TASKS_TOTAL.labels(bucket=bucket).set(
                biz.get("tasks_by_bucket", {}).get(bucket, 0)
            )
        for feedback_type in ("correction", "false_positive", "missing"):
            DB_FEEDBACK_TOTAL.labels(type=feedback_type).set(
                biz.get("feedback_by_type", {}).get(feedback_type, 0)
            )
        for row in biz.get("model_version_stats", []):
            model_version = row.get("model_version") or "unknown"
            DB_MODEL_MEETINGS_TOTAL.labels(model_version=model_version).set(row.get("meetings", 0))
    except Exception as exc:
        logging.getLogger(__name__).debug("Business metric gauge refresh failed: %s", exc)
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
    principal: Principal = Depends(require_user),
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
    suffix = _validated_upload_suffix(audio.filename)
    dest_dir = Path(settings.audio_storage_path) / meeting_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"upload{suffix}"

    _copy_upload_with_limit(audio, dest_path)
    try:
        validate_audio_content(dest_path)
    except IngestError as exc:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))

    # Insert a pending row in the DB immediately so the meeting is queryable
    # even before the Celery worker picks up the job.
    try:
        insert_meeting_stub(meeting_id, audio.filename, owner_user_id=_owner_scope(principal))
    except Exception as exc:
        logging.getLogger(__name__).warning("Could not insert meeting stub (non-fatal): %s", exc)

    # Dispatch async task
    process_meeting_task.apply_async(
        kwargs={
            "audio_path": str(dest_path),
            "roster_dict": roster.model_dump(),
            "meeting_id": meeting_id,
            "owner_user_id": _owner_scope(principal),
        },
        task_id=meeting_id,
    )

    return {"meeting_id": meeting_id, "status": "accepted"}


@app.get("/meetings/{meeting_id}", tags=["meetings"])
async def get_meeting(meeting_id: str, principal: Principal = Depends(require_user)):
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
        db_row = None
        try:
            db_row = db_get_meeting(
                meeting_id,
                owner_user_id=_owner_scope(principal),
            )
        except Exception as exc:
            if auth_is_configured():
                raise
            logging.getLogger(__name__).debug("Pending meeting DB lookup failed: %s", exc)
        if auth_is_configured() and db_row is None:
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        stale_row = _fail_stale_pending_meeting(db_row)
        if stale_row:
            return stale_row
        status_str = "pending" if celery_result.state == "PENDING" else "processing"
        return {"meeting_id": meeting_id, "status": status_str}

    # Job failed according to Celery
    if celery_result.state == "FAILURE":
        db_row = db_get_meeting(meeting_id, owner_user_id=_owner_scope(principal))
        if db_row:
            return db_row
        return JSONResponse(
            status_code=500,
            content={"meeting_id": meeting_id, "status": "failed", "error": str(celery_result.result)},
        )

    # Job succeeded — serve from DB (authoritative, survives Redis TTL expiry)
    if celery_result.state == "SUCCESS":
        db_row = db_get_meeting(meeting_id, owner_user_id=_owner_scope(principal))
        if db_row:
            db_row.setdefault("status", db_row.get("job_status", "completed"))
            return db_row
        if auth_is_configured():
            raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
        # DB persist may still be in-flight — fall back to Redis payload
        data = celery_result.result
        data.setdefault("status", data.get("job_status", "completed"))
        return data

    # Unknown state — try DB, then return raw state
    db_row = db_get_meeting(meeting_id, owner_user_id=_owner_scope(principal))
    if db_row:
        return db_row
    return {"meeting_id": meeting_id, "status": celery_result.state.lower()}


@app.post("/meetings/{meeting_id}/feedback", tags=["meetings"])
async def submit_feedback(
    meeting_id: str,
    submission: FeedbackSubmission,
    principal: Principal = Depends(require_user),
):
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
    if auth_is_configured() and db_get_meeting(
        meeting_id,
        owner_user_id=_owner_scope(principal),
    ) is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")
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
async def trigger_retrain(
    force: bool = False,
    _principal: Principal = Depends(require_admin),
):
    """
    Manually trigger the retraining pipeline.

    - force=false (default): only retrains if correction threshold is met
    - force=true: always retrain regardless of correction count

    The job runs asynchronously via Celery.
    """
    task = check_retrain_task.apply_async(kwargs={"force": force}, queue="mlops")
    return {"task_id": task.id, "status": "queued", "force": force}


@app.get("/admin/retrain/state", tags=["ops"])
async def get_retrain_state(_principal: Principal = Depends(require_admin)):
    """Return the current retraining state (last run, correction counts, history)."""
    state_file = Path("data/training/.retrain_state.json")
    if not state_file.exists():
        return {"last_correction_count": 0, "last_retrain_at": None, "runs": []}
    return json.loads(state_file.read_text())


@app.get("/admin/router-stats", tags=["ops"])
async def get_router_stats(_principal: Principal = Depends(require_admin)):
    """Per-endpoint health, in-flight count, and error rate for the inference router."""
    return router_stats()


# ── A/B test admin endpoints ──────────────────────────────────────────────────

def _ab_module():
    from meeting_agent.mlops import ab_test

    return ab_test


@app.get("/admin/ab-test/status", tags=["ops"])
async def ab_test_status(_principal: Principal = Depends(require_admin)):
    """Return current A/B test state."""
    ab = _ab_module()
    state = ab.load_state()
    state["runtime_enabled"] = ab.runtime_enabled()
    return state


class ABTestStartRequest(BaseModel):
    model_b: str
    traffic: float = 0.1


@app.post("/admin/ab-test/start", tags=["ops"])
async def ab_test_start(
    req: ABTestStartRequest,
    _principal: Principal = Depends(require_admin),
):
    """Start an A/B test between the current champion and a challenger model."""
    if req.traffic <= 0 or req.traffic >= 1:
        raise HTTPException(status_code=422, detail="traffic must be between 0 and 1 exclusive")
    ab = _ab_module()
    model_a = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")
    now = datetime.now(timezone.utc)
    experiment_id = f"ab_{now.strftime('%Y%m%d_%H%M%S')}"
    state = {
        "active": True,
        "experiment_id": experiment_id,
        "model_a": model_a,
        "model_b": req.model_b,
        "traffic_b": req.traffic,
        "started_at": now.isoformat(),
        "requires_env": "AB_TEST_ENABLED=true",
    }
    ab.save_state(state)
    return {**state, "runtime_enabled": ab.runtime_enabled()}


@app.delete("/admin/ab-test/stop", tags=["ops"])
async def ab_test_stop(_principal: Principal = Depends(require_admin)):
    """Stop the active A/B test and return aggregated results."""
    ab = _ab_module()
    state = ab.load_state()
    if not state.get("active"):
        raise HTTPException(status_code=404, detail="No active A/B test")
    state["active"] = False
    state["stopped_at"] = datetime.now(timezone.utc).isoformat()
    ab.save_state(state)
    results = ab.get_results(state["experiment_id"])
    return {"state": state, "results": results}


@app.get("/admin/ab-test/results", tags=["ops"])
async def ab_test_results(_principal: Principal = Depends(require_admin)):
    """Return aggregated A/B test results for the current (or last) experiment."""
    ab = _ab_module()
    results = ab.get_results()
    if not results:
        raise HTTPException(status_code=404, detail="No experiment results found")
    return results


@app.get("/metrics/business", tags=["ops"])
async def business_metrics(_principal: Principal = Depends(require_admin)):
    """
    Business KPIs computed from DB — suitable for Grafana JSON datasource panels.

    Returns correction rate, false positive rate, training data accumulation,
    and per-model-version breakdown for drift detection.
    """
    return db_get_business_metrics()


@app.get("/feedback/stats", tags=["meetings"])
async def get_feedback_stats(_principal: Principal = Depends(require_admin)):
    """Return aggregate statistics about accumulated user feedback."""
    return feedback_stats()


@app.get("/feedback/export", tags=["meetings"])
async def export_feedback_for_finetuning(
    limit: int = 500,
    format: str = "raw",
    _principal: Principal = Depends(require_admin),
):
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
async def get_workers(principal: Principal = Depends(require_user)):
    """List all registered workers (the participant database)."""
    return {"workers": [w.model_dump() for w in list_workers(owner_user_id=_owner_scope(principal))]}


class WorkerCreate(BaseModel):
    name: str
    aliases: list[str] = []
    role: str | None = None
    email: str | None = None
    skills: list[str] = []


@app.post("/workers", status_code=status.HTTP_201_CREATED, tags=["workers"])
async def create_worker(
    body: WorkerCreate,
    principal: Principal = Depends(require_user),
):
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
        created = add_worker(worker, owner_user_id=_owner_scope(principal))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return created.model_dump()


@app.put("/workers/{worker_id}", tags=["workers"])
async def edit_worker(
    worker_id: str,
    worker: Worker,
    principal: Principal = Depends(require_user),
):
    """Update an existing worker's fields by worker_id."""
    result = update_worker(worker_id, worker, owner_user_id=_owner_scope(principal))
    if result is None:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return result.model_dump()


@app.delete("/workers/{worker_id}", tags=["workers"])
async def remove_worker(worker_id: str, principal: Principal = Depends(require_user)):
    """Remove a worker from the participant database by worker_id."""
    found = delete_worker(worker_id, owner_user_id=_owner_scope(principal))
    if not found:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return {"worker_id": worker_id, "deleted": True}


@app.get("/meetings", tags=["meetings"])
async def list_meetings(
    limit: int = 50,
    offset: int = 0,
    principal: Principal = Depends(require_user),
):
    """List all meetings, newest first. Returns summary cards (no tasks/transcripts)."""
    return {
        "meetings": db_list_meetings(
            limit=limit,
            offset=offset,
            owner_user_id=_owner_scope(principal),
        )
    }


class ResolveParticipantRequest(BaseModel):
    worker_id: str
    display_name: str


@app.post("/meetings/{meeting_id}/participants/{speaker_id}/resolve", tags=["meetings"])
async def resolve_participant(
    meeting_id: str,
    speaker_id: str,
    body: ResolveParticipantRequest,
    principal: Principal = Depends(require_user),
):
    """Map an unresolved speaker label to a roster worker."""
    ok = db_resolve_participant(
        meeting_id,
        speaker_id,
        body.worker_id,
        body.display_name,
        owner_user_id=_owner_scope(principal),
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Participant '{speaker_id}' not found in meeting '{meeting_id}'.")
    return {"meeting_id": meeting_id, "speaker_id": speaker_id, "resolved_to": body.display_name}


@app.delete("/meetings/{meeting_id}", tags=["meetings"])
async def delete_meeting_data(
    meeting_id: str,
    principal: Principal = Depends(require_user),
):
    """Delete stored audio, transcript data, and DB rows for a meeting (GDPR compliance)."""
    owner_scope = _owner_scope(principal)
    if db_get_meeting(meeting_id, owner_user_id=owner_scope) is None:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")

    audio_dir = Path(settings.audio_storage_path) / meeting_id
    transcript_dir = Path(settings.transcript_storage_path) / meeting_id

    deleted = []
    for d in [audio_dir, transcript_dir]:
        if d.exists():
            shutil.rmtree(d)
            deleted.append(str(d))

    db_deleted = db_delete_meeting(meeting_id, owner_user_id=owner_scope)

    return {"meeting_id": meeting_id, "deleted_paths": deleted, "db_deleted": db_deleted}
