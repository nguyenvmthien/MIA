"""Repository — all database operations in one place.

Calling convention: every public function opens its own session via `get_session()`.
This makes them safe to call from both the FastAPI process and the Celery worker
without sharing connection objects across OS threads.
"""

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from meeting_agent.db.engine import engine, get_session
from meeting_agent.db.models import FeedbackCorrection, Meeting, MeetingParticipant, Task

log = logging.getLogger(__name__)


# ── Meeting ───────────────────────────────────────────────────────────────────

def insert_meeting_stub(meeting_id: str, audio_filename: str | None) -> None:
    """Insert a pending meeting row immediately when the upload is accepted.

    This ensures the meeting is queryable even before the Celery task starts,
    which matters when the API and worker are on separate machines.
    """
    with get_session() as session:
        meeting = Meeting(
            id=meeting_id,
            status="pending",
            audio_filename=audio_filename,
        )
        session.add(meeting)
    log.debug("Inserted meeting stub %s", meeting_id)


def upsert_meeting_result(summary_dict: dict) -> None:
    """Write (or overwrite) the full pipeline result for a meeting.

    Uses PostgreSQL's INSERT … ON CONFLICT DO UPDATE so the Celery worker
    can call this idempotently on retries.
    """
    meeting_id = summary_dict["meeting_id"]

    # Coerce date strings → date objects for the Task rows
    def _parse_date(val: Any) -> date | None:
        if not val:
            return None
        if isinstance(val, date):
            return val
        try:
            return date.fromisoformat(str(val))
        except ValueError:
            return None

    # Build flat metric dict (drop the nested StageTiming object if present)
    raw_metrics = summary_dict.get("run_metrics") or {}
    if isinstance(raw_metrics, dict):
        stage = raw_metrics.pop("stage_timings", None)
        if isinstance(stage, dict):
            raw_metrics["stage_timings"] = stage
        elif hasattr(stage, "model_dump"):
            raw_metrics["stage_timings"] = stage.model_dump()

    # ── Upsert meeting row ────────────────────────────────────────────────────
    stmt = (
        pg_insert(Meeting)
        .values(
            id=meeting_id,
            status=summary_dict.get("job_status", "completed"),
            audio_filename=summary_dict.get("audio_filename"),
            created_at=summary_dict.get("created_at") or datetime.utcnow(),
            processed_at=summary_dict.get("processed_at") or datetime.utcnow(),
            duration_ms=summary_dict.get("duration_ms"),
            participants=summary_dict.get("participants") or [],
            summary_text=summary_dict.get("summary_text"),
            run_metrics=raw_metrics or None,
            transcript_turns=summary_dict.get("transcript_turns") or None,
            error=summary_dict.get("error"),
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "status": summary_dict.get("job_status", "completed"),
                "processed_at": summary_dict.get("processed_at") or datetime.utcnow(),
                "duration_ms": summary_dict.get("duration_ms"),
                "participants": summary_dict.get("participants") or [],
                "summary_text": summary_dict.get("summary_text"),
                "run_metrics": raw_metrics or None,
                "transcript_turns": summary_dict.get("transcript_turns") or None,
                "error": summary_dict.get("error"),
            },
        )
    )

    with get_session() as session:
        session.execute(stmt)

        # ── Delete existing tasks and participants, then re-insert ───────────
        session.query(Task).filter_by(meeting_id=meeting_id).delete()
        session.query(MeetingParticipant).filter_by(meeting_id=meeting_id).delete()

        for p in summary_dict.get("meeting_participants") or []:
            session.add(MeetingParticipant(
                meeting_id=meeting_id,
                speaker_id=p.get("speaker_id", ""),
                display_name=p.get("display_name", p.get("speaker_id", "")),
                worker_id=p.get("worker_id"),
                email=p.get("email"),
            ))

        buckets = {
            "action": summary_dict.get("action_items") or [],
            "unresolved": summary_dict.get("unresolved_items") or [],
            "human_review": summary_dict.get("human_review_items") or [],
        }
        for bucket, items in buckets.items():
            for raw in items:
                t = Task(
                    meeting_id=meeting_id,
                    task_id=raw.get("task_id", ""),
                    description=raw.get("description", ""),
                    assignee=raw.get("assignee"),
                    assignee_id=raw.get("assignee_id"),
                    due_date=_parse_date(raw.get("due_date")),
                    priority=raw.get("priority", "medium"),
                    status=raw.get("status", "open"),
                    extraction_confidence=raw.get("extraction_confidence", 1.0),
                    source_turn_ids=raw.get("source_turn_ids") or [],
                    notes=raw.get("notes"),
                    bucket=bucket,
                )
                session.add(t)

    log.info("Upserted meeting %s with status=%s", meeting_id, summary_dict.get("job_status"))


def get_meeting(meeting_id: str) -> dict | None:
    """Return a meeting as a plain dict, or None if not found."""
    with get_session() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            return None

        def _task_to_dict(t: Task) -> dict:
            return {
                "task_id": t.task_id,
                "description": t.description,
                "assignee": t.assignee,
                "assignee_id": t.assignee_id,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
                "status": t.status,
                "extraction_confidence": t.extraction_confidence,
                "source_turn_ids": t.source_turn_ids,
                "notes": t.notes,
            }

        tasks_by_bucket: dict[str, list] = {"action": [], "unresolved": [], "human_review": []}
        for t in meeting.tasks:
            tasks_by_bucket.setdefault(t.bucket, []).append(_task_to_dict(t))

        participants_detail = [
            {
                "speaker_id": p.speaker_id,
                "display_name": p.display_name,
                "worker_id": p.worker_id,
                "email": p.email,
            }
            for p in meeting.meeting_participants
        ]

        return {
            "meeting_id": meeting.id,
            "status": meeting.status,
            "job_status": meeting.status,
            "audio_filename": meeting.audio_filename,
            "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
            "processed_at": meeting.processed_at.isoformat() if meeting.processed_at else None,
            "duration_ms": meeting.duration_ms,
            "participants": [p["display_name"] for p in participants_detail],
            "participants_detail": participants_detail,
            "summary_text": meeting.summary_text,
            "action_items": tasks_by_bucket["action"],
            "unresolved_items": tasks_by_bucket["unresolved"],
            "human_review_items": tasks_by_bucket["human_review"],
            "run_metrics": meeting.run_metrics,
            "error": meeting.error,
        }


def apply_corrections_to_tasks(meeting_id: str, corrections: list[dict]) -> int:
    """Apply feedback corrections directly to the tasks table.

    This keeps `tasks` as the live ground-truth so fine-tuning exports always
    reflect the human-reviewed version without having to replay diffs.
    Returns the number of task rows updated.
    """
    updated = 0
    with get_session() as session:
        for c in corrections:
            task_id = c.get("task_id")
            if not task_id:
                continue
            task = (
                session.query(Task)
                .filter_by(meeting_id=meeting_id, task_id=task_id)
                .first()
            )
            if task is None:
                continue
            if c.get("is_false_positive"):
                task.status = "dismissed"
                updated += 1
                continue
            changed = False
            if c.get("corrected_description"):
                task.description = c["corrected_description"]
                changed = True
            if c.get("corrected_assignee") is not None:
                task.assignee = c["corrected_assignee"] or None
                changed = True
            if c.get("corrected_due_date"):
                try:
                    from datetime import date as _date
                    task.due_date = _date.fromisoformat(str(c["corrected_due_date"]))
                    changed = True
                except ValueError:
                    pass
            if changed:
                updated += 1
    log.info("Applied %d corrections to tasks for meeting %s", updated, meeting_id)
    return updated


def delete_meeting(meeting_id: str) -> bool:
    """Delete meeting and all related tasks/corrections (cascades via FK).
    Returns True if the row existed."""
    with get_session() as session:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            return False
        session.delete(meeting)
    return True


# ── Feedback ──────────────────────────────────────────────────────────────────

def save_corrections_to_db(
    meeting_id: str,
    corrections: list[dict],
    reviewer: str | None = None,
    notes: str | None = None,
) -> int:
    """Persist feedback corrections to the database.

    Each item in `corrections` is expected to match the TaskCorrection schema
    (dict form). Returns the number of rows inserted.
    """
    def _parse_date(val: Any) -> date | None:
        if not val:
            return None
        if isinstance(val, date):
            return val
        try:
            return date.fromisoformat(str(val))
        except ValueError:
            return None

    rows = []
    for c in corrections:
        rows.append(
            FeedbackCorrection(
                meeting_id=meeting_id,
                task_id=c.get("task_id"),
                reviewer=reviewer or c.get("reviewer"),
                notes=notes or c.get("notes"),
                original_description=c.get("original_description"),
                corrected_description=c.get("corrected_description"),
                original_assignee=c.get("original_assignee"),
                corrected_assignee=c.get("corrected_assignee"),
                original_due_date=_parse_date(c.get("original_due_date")),
                corrected_due_date=_parse_date(c.get("corrected_due_date")),
                is_false_positive=bool(c.get("is_false_positive", False)),
                is_missing=bool(c.get("is_missing", False)),
            )
        )

    if not rows:
        return 0

    with get_session() as session:
        session.add_all(rows)

    log.info("Saved %d feedback corrections for meeting %s", len(rows), meeting_id)
    return len(rows)


def get_feedback_stats_from_db() -> dict:
    """Aggregate feedback statistics from the database."""
    with get_session() as session:
        total = session.scalar(select(func.count()).select_from(FeedbackCorrection)) or 0
        if total == 0:
            return {"total": 0}
        fp = session.scalar(
            select(func.count()).where(FeedbackCorrection.is_false_positive.is_(True))
        ) or 0
        missing = session.scalar(
            select(func.count()).where(FeedbackCorrection.is_missing.is_(True))
        ) or 0
        assignee_fix = session.scalar(
            select(func.count()).where(
                FeedbackCorrection.corrected_assignee.isnot(None),
                FeedbackCorrection.corrected_assignee != FeedbackCorrection.original_assignee,
            )
        ) or 0
        desc_fix = session.scalar(
            select(func.count()).where(
                FeedbackCorrection.corrected_description.isnot(None),
                FeedbackCorrection.corrected_description != FeedbackCorrection.original_description,
            )
        ) or 0
        return {
            "total": total,
            "false_positives": fp,
            "missing_tasks": missing,
            "assignee_corrections": assignee_fix,
            "description_corrections": desc_fix,
        }
