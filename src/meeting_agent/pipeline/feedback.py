"""Feedback loop — stores user corrections to extracted tasks.

Corrections are written to two sinks:
  1. PostgreSQL (primary)  — queryable, indexed, used for stats and retrain pipeline
  2. JSONL flat file (secondary) — append-only backup; existing retrain scripts read this
"""

import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import FEEDBACK_SUBMITTED

log = logging.getLogger(__name__)

FEEDBACK_STORE = Path(settings.transcript_storage_path) / "_feedback.jsonl"


class TaskCorrection(BaseModel):
    meeting_id: str
    task_id: str
    original_description: str
    corrected_description: str | None = None
    original_assignee: str | None = None
    corrected_assignee: str | None = None
    original_due_date: str | None = None
    corrected_due_date: str | None = None
    is_false_positive: bool = False
    is_missing: bool = False
    submitted_at: datetime | None = None

    def model_post_init(self, __context) -> None:
        if self.submitted_at is None:
            self.submitted_at = datetime.utcnow()


class FeedbackSubmission(BaseModel):
    corrections: list[TaskCorrection]
    reviewer: str | None = None
    notes: str | None = None


def _increment_feedback_metrics(submission: FeedbackSubmission) -> None:
    for correction in submission.corrections:
        if correction.is_false_positive:
            FEEDBACK_SUBMITTED.labels(type="false_positive").inc()
        elif correction.is_missing:
            FEEDBACK_SUBMITTED.labels(type="missing").inc()
        else:
            FEEDBACK_SUBMITTED.labels(type="correction").inc()


def save_feedback(submission: FeedbackSubmission) -> int:
    """Persist corrections to PostgreSQL (primary) and JSONL (backup).
    Returns the number of corrections saved.
    """
    if not submission.corrections:
        return 0

    count, jsonl_written = _write_to_db(submission)
    if not jsonl_written:
        _write_to_jsonl(submission)
    return count


def _write_to_db(submission: FeedbackSubmission) -> tuple[int, bool]:
    """Write corrections to PostgreSQL and apply them to the tasks table.

    Returns (count, jsonl_written). On DB failure falls back to JSONL and
    signals that JSONL has already been written so the caller doesn't double-write.
    """
    try:
        from meeting_agent.db.repository import apply_corrections_to_tasks, save_corrections_to_db

        corrections_dicts = [c.model_dump() for c in submission.corrections]
        by_meeting: dict[str, list] = {}
        for d in corrections_dicts:
            by_meeting.setdefault(d["meeting_id"], []).append(d)

        total = 0
        for meeting_id, items in by_meeting.items():
            total += save_corrections_to_db(
                meeting_id=meeting_id,
                corrections=items,
                reviewer=submission.reviewer,
                notes=submission.notes,
            )
            apply_corrections_to_tasks(meeting_id, items)

        _increment_feedback_metrics(submission)
        return total, False
    except Exception:
        log.exception("Failed to write feedback to database — falling back to JSONL only")
        count = _write_to_jsonl_count(submission)
        return count, True  # JSONL already written inside _write_to_jsonl_count


def _write_to_jsonl(submission: FeedbackSubmission) -> None:
    """Append corrections to the backup JSONL file (best-effort)."""
    try:
        FEEDBACK_STORE.parent.mkdir(parents=True, exist_ok=True)
        with FEEDBACK_STORE.open("a") as f:
            for correction in submission.corrections:
                f.write(correction.model_dump_json() + "\n")
    except Exception:
        log.warning("Could not write feedback to JSONL backup at %s", FEEDBACK_STORE)


def _write_to_jsonl_count(submission: FeedbackSubmission) -> int:
    _write_to_jsonl(submission)
    _increment_feedback_metrics(submission)
    return len(submission.corrections)


def load_feedback(limit: int = 1000) -> list[TaskCorrection]:
    """Load recent corrections — tries DB first, falls back to JSONL."""
    try:
        from meeting_agent.db.engine import get_session
        from meeting_agent.db.models import FeedbackCorrection

        with get_session() as session:
            rows = (
                session.query(FeedbackCorrection)
                .order_by(FeedbackCorrection.submitted_at.desc())
                .limit(limit)
                .all()
            )
            return [
                TaskCorrection(
                    meeting_id=r.meeting_id,
                    task_id=r.task_id or "",
                    original_description=r.original_description or "",
                    corrected_description=r.corrected_description,
                    original_assignee=r.original_assignee,
                    corrected_assignee=r.corrected_assignee,
                    original_due_date=r.original_due_date.isoformat() if r.original_due_date else None,
                    corrected_due_date=r.corrected_due_date.isoformat() if r.corrected_due_date else None,
                    is_false_positive=r.is_false_positive,
                    is_missing=r.is_missing,
                    submitted_at=r.submitted_at,
                )
                for r in rows
            ]
    except Exception:
        log.warning("DB unavailable for load_feedback — reading JSONL fallback")
        return _load_from_jsonl(limit)


def _load_from_jsonl(limit: int) -> list[TaskCorrection]:
    if not FEEDBACK_STORE.exists():
        return []
    corrections = []
    with FEEDBACK_STORE.open() as f:
        for line in f:
            line = line.strip()
            if line:
                corrections.append(TaskCorrection.model_validate_json(line))
    return corrections[-limit:]


def feedback_stats() -> dict:
    """Return aggregate statistics — tries DB first, falls back to JSONL."""
    try:
        from meeting_agent.db.repository import get_feedback_stats_from_db
        return get_feedback_stats_from_db()
    except Exception:
        log.warning("DB unavailable for feedback_stats — computing from JSONL")
        return _stats_from_jsonl()


def _stats_from_jsonl() -> dict:
    corrections = _load_from_jsonl(limit=10_000)
    if not corrections:
        return {"total": 0}
    return {
        "total": len(corrections),
        "false_positives": sum(1 for c in corrections if c.is_false_positive),
        "missing_tasks": sum(1 for c in corrections if c.is_missing),
        "assignee_corrections": sum(
            1 for c in corrections
            if c.corrected_assignee and c.corrected_assignee != c.original_assignee
        ),
    }
