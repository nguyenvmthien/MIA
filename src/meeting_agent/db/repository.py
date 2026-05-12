"""Repository — all database operations in one place.

Calling convention: every public function opens its own session via `get_session()`.
This makes them safe to call from both the FastAPI process and the Celery worker
without sharing connection objects across OS threads.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from meeting_agent.db.engine import get_session
from meeting_agent.db.models import (
    CalendarEvent,
    FeedbackCorrection,
    Meeting,
    MeetingArtifact,
    MeetingParticipant,
    Task,
    TranscriptTurnRow,
)

log = logging.getLogger(__name__)


# ── Meeting ───────────────────────────────────────────────────────────────────

def insert_meeting_stub(
    meeting_id: str,
    audio_filename: str | None,
    owner_user_id: str | None = None,
) -> None:
    """Insert a pending meeting row immediately when the upload is accepted.

    This ensures the meeting is queryable even before the Celery task starts,
    which matters when the API and worker are on separate machines.
    """
    with get_session() as session:
        meeting = Meeting(
            id=meeting_id,
            status="pending",
            owner_user_id=owner_user_id,
            audio_filename=audio_filename,
        )
        session.add(meeting)
    log.debug("Inserted meeting stub %s", meeting_id)


def fail_stale_pending_meetings(timeout_minutes: int, error_message: str) -> int:
    """Mark pending meetings older than timeout as failed.

    A Celery task can be lost if the API is restarted after creating the DB stub
    but before the broker keeps the task. Without this cleanup, clients poll a
    pending meeting forever and dashboards over-report queued work.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(timeout_minutes, 1))
    with get_session() as session:
        count = (
            session.query(Meeting)
            .filter(Meeting.status == "pending", Meeting.created_at < cutoff)
            .update(
                {
                    Meeting.status: "failed",
                    Meeting.processed_at: datetime.now(timezone.utc),
                    Meeting.error: error_message,
                },
                synchronize_session=False,
            )
        )
    if count:
        log.warning("Marked %d stale pending meetings as failed", count)
    return count


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
    owner_user_id = summary_dict.get("owner_user_id")
    insert_values = {
        "id": meeting_id,
        "status": summary_dict.get("job_status", "completed"),
        "owner_user_id": owner_user_id,
        "audio_filename": summary_dict.get("audio_filename"),
        "created_at": summary_dict.get("created_at") or datetime.now(timezone.utc),
        "processed_at": summary_dict.get("processed_at") or datetime.now(timezone.utc),
        "duration_ms": summary_dict.get("duration_ms"),
        "participants": summary_dict.get("participants") or [],
        "summary_text": summary_dict.get("summary_text"),
        "run_metrics": raw_metrics or None,
        "transcript_turns": summary_dict.get("transcript_turns") or None,
        "error": summary_dict.get("error"),
        "model_version": summary_dict.get("model_version"),
    }
    update_values = {
        "status": summary_dict.get("job_status", "completed"),
        "processed_at": summary_dict.get("processed_at") or datetime.now(timezone.utc),
        "duration_ms": summary_dict.get("duration_ms"),
        "participants": summary_dict.get("participants") or [],
        "summary_text": summary_dict.get("summary_text"),
        "run_metrics": raw_metrics or None,
        "transcript_turns": summary_dict.get("transcript_turns") or None,
        "error": summary_dict.get("error"),
        "model_version": summary_dict.get("model_version"),
    }
    if owner_user_id:
        update_values["owner_user_id"] = owner_user_id

    stmt = (
        pg_insert(Meeting)
        .values(**insert_values)
        .on_conflict_do_update(
            index_elements=["id"],
            set_=update_values,
        )
    )

    with get_session() as session:
        session.execute(stmt)

        # ── Delete existing tasks and participants, then re-insert ───────────
        session.query(Task).filter_by(meeting_id=meeting_id).delete()
        session.query(MeetingParticipant).filter_by(meeting_id=meeting_id).delete()
        session.query(TranscriptTurnRow).filter_by(meeting_id=meeting_id).delete()
        session.query(MeetingArtifact).filter_by(meeting_id=meeting_id).delete()

        for p in summary_dict.get("meeting_participants") or []:
            session.add(MeetingParticipant(
                meeting_id=meeting_id,
                speaker_id=p.get("speaker_id", ""),
                display_name=p.get("display_name", p.get("speaker_id", "")),
                worker_id=p.get("worker_id"),
                email=p.get("email"),
            ))

        for idx, turn in enumerate(summary_dict.get("transcript_turns") or []):
            session.add(TranscriptTurnRow(
                meeting_id=meeting_id,
                turn_id=turn.get("turn_id") or f"turn_{idx}",
                speaker_id=turn.get("speaker_id", ""),
                speaker_name=turn.get("speaker_name"),
                worker_id=turn.get("worker_id"),
                start_ms=turn.get("start_ms", 0) or 0,
                end_ms=turn.get("end_ms", 0) or 0,
                text=turn.get("text", ""),
                asr_confidence=turn.get("asr_confidence"),
            ))

        for artifact in summary_dict.get("meeting_artifacts") or []:
            session.add(MeetingArtifact(
                meeting_id=meeting_id,
                artifact_type=artifact.get("artifact_type", "unknown"),
                storage_uri=artifact.get("storage_uri"),
                payload=artifact.get("payload"),
                checksum=artifact.get("checksum"),
                artifact_metadata=artifact.get("metadata") or artifact.get("artifact_metadata"),
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


def get_meeting(meeting_id: str, owner_user_id: str | None = None) -> dict | None:
    """Return a meeting as a plain dict, or None if not found."""
    with get_session() as session:
        query = session.query(Meeting).filter(Meeting.id == meeting_id)
        if owner_user_id is not None:
            query = query.filter(Meeting.owner_user_id == owner_user_id)
        meeting = query.first()
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

        # Enrich email from current worker registry (may be null if worker added later)
        try:
            from meeting_agent.pipeline.worker_registry import get_worker
            def _enrich_email(p: MeetingParticipant) -> str | None:
                if p.email:
                    return p.email
                if p.worker_id:
                    w = get_worker(p.worker_id, owner_user_id=meeting.owner_user_id)
                    return w.email if w else None
                return None
        except Exception:
            def _enrich_email(p): return p.email  # type: ignore

        participants_detail = [
            {
                "speaker_id": p.speaker_id,
                "display_name": p.display_name,
                "worker_id": p.worker_id,
                "email": _enrich_email(p),
            }
            for p in meeting.meeting_participants
        ]

        transcript_turns = [
            {
                "turn_id": t.turn_id,
                "speaker_id": t.speaker_id,
                "speaker_name": t.speaker_name,
                "worker_id": t.worker_id,
                "start_ms": t.start_ms,
                "end_ms": t.end_ms,
                "text": t.text,
                "asr_confidence": t.asr_confidence,
            }
            for t in sorted(meeting.transcript_rows, key=lambda row: (row.start_ms, row.id))
        ]
        if not transcript_turns:
            transcript_turns = meeting.transcript_turns or []

        artifacts = [
            {
                "artifact_type": a.artifact_type,
                "storage_uri": a.storage_uri,
                "checksum": a.checksum,
                "metadata": a.artifact_metadata,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in meeting.artifacts
        ]

        return {
            "meeting_id": meeting.id,
            "owner_user_id": meeting.owner_user_id,
            "status": meeting.status,
            "job_status": meeting.status,
            "audio_filename": meeting.audio_filename,
            "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
            "processed_at": meeting.processed_at.isoformat() if meeting.processed_at else None,
            "duration_ms": meeting.duration_ms,
            "participants": [p["display_name"] for p in participants_detail],
            "participants_detail": participants_detail,
            "transcript_turns": transcript_turns,
            "summary_text": meeting.summary_text,
            "action_items": tasks_by_bucket["action"],
            "unresolved_items": tasks_by_bucket["unresolved"],
            "human_review_items": tasks_by_bucket["human_review"],
            "run_metrics": meeting.run_metrics,
            "error": meeting.error,
            "model_version": meeting.model_version,
            "artifacts": artifacts,
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


def list_meetings(
    limit: int = 50,
    offset: int = 0,
    owner_user_id: str | None = None,
) -> list[dict]:
    """Return a summary list of all meetings, newest first."""
    with get_session() as session:
        query = session.query(Meeting)
        if owner_user_id is not None:
            query = query.filter(Meeting.owner_user_id == owner_user_id)
        meetings = query.order_by(Meeting.created_at.desc()).offset(offset).limit(limit).all()
        result = []
        for m in meetings:
            task_count = sum(1 for t in m.tasks if t.bucket == "action")
            unresolved_speakers = [
                {"speaker_id": p.speaker_id, "display_name": p.display_name, "worker_id": p.worker_id}
                for p in m.meeting_participants
                if p.worker_id is None
            ]
            result.append({
                "meeting_id": m.id,
                "owner_user_id": m.owner_user_id,
                "status": m.status,
                "audio_filename": m.audio_filename,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "processed_at": m.processed_at.isoformat() if m.processed_at else None,
                "duration_ms": m.duration_ms,
                "summary_text": m.summary_text,
                "participants": [p.display_name for p in m.meeting_participants],
                "task_count": task_count,
                "unresolved_speaker_count": len(unresolved_speakers),
                "error": m.error,
            })
        return result


def resolve_participant(
    meeting_id: str,
    speaker_id: str,
    worker_id: str,
    display_name: str,
    owner_user_id: str | None = None,
) -> bool:
    """Assign a roster worker to an unresolved speaker label in a meeting."""
    with get_session() as session:
        meeting_query = session.query(Meeting).filter(Meeting.id == meeting_id)
        if owner_user_id is not None:
            meeting_query = meeting_query.filter(Meeting.owner_user_id == owner_user_id)
        if meeting_query.first() is None:
            return False
        p = session.query(MeetingParticipant).filter_by(
            meeting_id=meeting_id,
            speaker_id=speaker_id,
        ).first()
        if p is None:
            return False
        old_display_name = p.display_name  # e.g. "SPEAKER_00" or whatever pipeline set
        p.worker_id = worker_id
        p.display_name = display_name
        # Update tasks referencing this speaker by speaker_id OR the old display_name
        identifiers = {speaker_id}
        if old_display_name:
            identifiers.add(old_display_name)
        for identifier in identifiers:
            session.query(Task).filter_by(meeting_id=meeting_id, assignee=identifier).update(
                {"assignee": display_name, "assignee_id": worker_id}
            )
    return True


def delete_meeting(meeting_id: str, owner_user_id: str | None = None) -> bool:
    """Delete meeting and all related tasks/corrections (cascades via FK).
    Returns True if the row existed."""
    with get_session() as session:
        query = session.query(Meeting).filter(Meeting.id == meeting_id)
        if owner_user_id is not None:
            query = query.filter(Meeting.owner_user_id == owner_user_id)
        meeting = query.first()
        if meeting is None:
            return False
        session.delete(meeting)
    return True


# ── Calendar events ───────────────────────────────────────────────────────────

def _calendar_event_to_dict(event: CalendarEvent) -> dict:
    return {
        "meeting_id": event.meeting_id,
        "task_id": event.task_id,
        "user_id": event.user_id,
        "provider": event.provider,
        "event_id": event.provider_event_id,
        "html_link": event.html_link,
        "status": event.status,
        "last_error": event.last_error,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }


def get_calendar_event(
    meeting_id: str,
    task_id: str,
    user_id: str,
    provider: str = "google",
) -> dict | None:
    with get_session() as session:
        event = (
            session.query(CalendarEvent)
            .filter_by(
                meeting_id=meeting_id,
                task_id=task_id,
                user_id=user_id,
                provider=provider,
            )
            .first()
        )
        return _calendar_event_to_dict(event) if event else None


def upsert_calendar_event(
    *,
    meeting_id: str,
    task_id: str,
    user_id: str,
    provider: str = "google",
    provider_event_id: str | None = None,
    html_link: str | None = None,
    status: str = "created",
    last_error: str | None = None,
) -> dict:
    with get_session() as session:
        event = (
            session.query(CalendarEvent)
            .filter_by(
                meeting_id=meeting_id,
                task_id=task_id,
                user_id=user_id,
                provider=provider,
            )
            .first()
        )
        if event is None:
            event = CalendarEvent(
                meeting_id=meeting_id,
                task_id=task_id,
                user_id=user_id,
                provider=provider,
            )
            session.add(event)
        event.provider_event_id = provider_event_id
        event.html_link = html_link
        event.status = status
        event.last_error = last_error
        session.flush()
        return _calendar_event_to_dict(event)


def list_calendar_events(meeting_id: str, user_id: str | None = None) -> list[dict]:
    with get_session() as session:
        query = session.query(CalendarEvent).filter(CalendarEvent.meeting_id == meeting_id)
        if user_id is not None:
            query = query.filter(CalendarEvent.user_id == user_id)
        return [_calendar_event_to_dict(event) for event in query.order_by(CalendarEvent.id).all()]


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


def get_business_metrics() -> dict:
    """Compute business KPIs from DB for the dashboard and training pipeline tracking."""
    with get_session() as session:
        total_meetings = session.scalar(select(func.count()).select_from(Meeting)) or 0
        completed = session.scalar(
            select(func.count()).where(Meeting.status == "completed")
        ) or 0
        status_rows = (
            session.query(Meeting.status, func.count(Meeting.id))
            .group_by(Meeting.status)
            .all()
        )
        meetings_by_status = {status or "unknown": count for status, count in status_rows}

        # Correction rate = total corrections / completed meetings
        total_corrections = session.scalar(
            select(func.count()).select_from(FeedbackCorrection)
        ) or 0
        correction_rate = round(total_corrections / completed, 3) if completed else 0.0

        # False positive rate = dismissed tasks / all action tasks
        total_action_tasks = session.scalar(
            select(func.count()).select_from(Task).where(Task.bucket == "action")
        ) or 0
        task_rows = (
            session.query(Task.bucket, func.count(Task.id))
            .group_by(Task.bucket)
            .all()
        )
        tasks_by_bucket = {bucket or "unknown": count for bucket, count in task_rows}
        dismissed_tasks = session.scalar(
            select(func.count()).select_from(Task).where(
                Task.bucket == "action", Task.status == "dismissed"
            )
        ) or 0
        fp_rate = round(dismissed_tasks / total_action_tasks, 3) if total_action_tasks else 0.0

        # Training data: meetings with ≥1 correction (usable for fine-tuning)
        meetings_with_corrections = session.scalar(
            select(func.count(FeedbackCorrection.meeting_id.distinct()))
        ) or 0

        # Calendar adoption: meetings that had corrections submitted (proxy for "reviewed")
        # A proper adoption rate needs calendar sync events — use corrections as proxy for now
        false_positives = session.scalar(
            select(func.count()).where(FeedbackCorrection.is_false_positive.is_(True))
        ) or 0
        missing_tasks = session.scalar(
            select(func.count()).where(FeedbackCorrection.is_missing.is_(True))
        ) or 0
        desc_corrections = session.scalar(
            select(func.count()).where(
                FeedbackCorrection.corrected_description.isnot(None)
            )
        ) or 0
        assignee_corrections = session.scalar(
            select(func.count()).where(
                FeedbackCorrection.corrected_assignee.isnot(None)
            )
        ) or 0
        due_date_corrections = session.scalar(
            select(func.count()).where(
                FeedbackCorrection.corrected_due_date.isnot(None)
            )
        ) or 0

        # Corrections by model version (for drift detection)
        from meeting_agent.db.models import Meeting as MeetingModel
        version_stats: list[dict] = []
        rows = (
            session.query(
                MeetingModel.model_version,
                func.count(MeetingModel.id).label("meetings"),
            )
            .filter(MeetingModel.model_version.isnot(None))
            .group_by(MeetingModel.model_version)
            .all()
        )
        for row in rows:
            version_stats.append({"model_version": row[0], "meetings": row[1]})

        return {
            "total_meetings": total_meetings,
            "completed_meetings": completed,
            "meetings_by_status": meetings_by_status,
            "total_corrections": total_corrections,
            "correction_rate": correction_rate,
            "false_positive_rate": fp_rate,
            "dismissed_tasks": dismissed_tasks,
            "total_action_tasks": total_action_tasks,
            "tasks_by_bucket": tasks_by_bucket,
            "meetings_with_corrections": meetings_with_corrections,
            "training_ready_samples": meetings_with_corrections,
            "corrections_breakdown": {
                "false_positives": false_positives,
                "missing_tasks": missing_tasks,
                "description_edits": desc_corrections,
                "assignee_edits": assignee_corrections,
                "due_date_edits": due_date_corrections,
            },
            "feedback_by_type": {
                "correction": max(total_corrections - false_positives - missing_tasks, 0),
                "false_positive": false_positives,
                "missing": missing_tasks,
            },
            "model_version_stats": version_stats,
        }


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
