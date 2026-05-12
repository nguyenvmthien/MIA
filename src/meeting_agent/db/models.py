"""ORM models — meetings, tasks, and feedback corrections."""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Meeting(Base):
    """One row per meeting submission. Persisted immediately on upload (status=pending),
    updated in-place once the Celery pipeline completes."""

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    owner_user_id: Mapped[str | None] = mapped_column(String(255))
    audio_filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    participants: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    summary_text: Mapped[str | None] = mapped_column(Text)
    run_metrics: Mapped[dict | None] = mapped_column(JSONB)
    transcript_turns: Mapped[list | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str | None] = mapped_column(String(100))  # e.g. "qwen2.5:3b" or "meeting-agent-v1"

    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="meeting", cascade="all, delete-orphan"
    )
    corrections: Mapped[list["FeedbackCorrection"]] = relationship(
        "FeedbackCorrection", back_populates="meeting", cascade="all, delete-orphan"
    )
    meeting_participants: Mapped[list["MeetingParticipant"]] = relationship(
        "MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan"
    )
    calendar_events: Mapped[list["CalendarEvent"]] = relationship(
        "CalendarEvent", back_populates="meeting", cascade="all, delete-orphan"
    )
    transcript_rows: Mapped[list["TranscriptTurnRow"]] = relationship(
        "TranscriptTurnRow", back_populates="meeting", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["MeetingArtifact"]] = relationship(
        "MeetingArtifact", back_populates="meeting", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_meetings_status", "status"),
        Index("ix_meetings_created_at", "created_at"),
        Index("ix_meetings_owner_user_id", "owner_user_id"),
    )


class WorkerRecord(Base):
    """Registered worker/participant profile scoped to a user or team."""

    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_user_id: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    skills: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("owner_user_id", "worker_id", name="uq_workers_owner_worker"),
        Index("ix_workers_owner_user_id", "owner_user_id"),
        Index("ix_workers_name", "name"),
    )


class Task(Base):
    """Individual action item extracted from a meeting. Bucket separates the three lists
    returned by the pipeline (action / unresolved / human_review)."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(255))
    assignee_id: Mapped[str | None] = mapped_column(String(100))
    due_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="open")
    extraction_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    source_turn_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text)
    # "action" | "unresolved" | "human_review"
    bucket: Mapped[str] = mapped_column(String(20), nullable=False, default="action")

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("meeting_id", "task_id", name="uq_tasks_meeting_task"),
        Index("ix_tasks_meeting_id", "meeting_id"),
        Index("ix_tasks_bucket", "bucket"),
    )


class MeetingParticipant(Base):
    """One row per unique participant per meeting.

    speaker_id is the raw diarization label (e.g. SPEAKER_01).
    display_name is the resolved name (from RAG/roster) or falls back to speaker_id.
    worker_id is set when the participant matched a roster entry; NULL for unknown attendees.
    """

    __tablename__ = "meeting_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    speaker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="meeting_participants")

    __table_args__ = (
        UniqueConstraint("meeting_id", "speaker_id", name="uq_participants_meeting_speaker"),
        Index("ix_participants_meeting_id", "meeting_id"),
        Index("ix_participants_worker_id", "worker_id"),
    )


class FeedbackCorrection(Base):
    """User correction for a single extracted task.
    Populated by both explicit API calls and implicit diffs captured in the frontend."""

    __tablename__ = "feedback_corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str | None] = mapped_column(String(100))
    reviewer: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)

    original_description: Mapped[str | None] = mapped_column(Text)
    corrected_description: Mapped[str | None] = mapped_column(Text)
    original_assignee: Mapped[str | None] = mapped_column(String(255))
    corrected_assignee: Mapped[str | None] = mapped_column(String(255))
    original_due_date: Mapped[date | None] = mapped_column(Date)
    corrected_due_date: Mapped[date | None] = mapped_column(Date)
    is_false_positive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="corrections")

    __table_args__ = (
        Index("ix_feedback_meeting_id", "meeting_id"),
        Index("ix_feedback_submitted_at", "submitted_at"),
    )

class CalendarEvent(Base):
    """Calendar provider event created from a meeting action item."""

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="google")
    provider_event_id: Mapped[str | None] = mapped_column(String(255))
    html_link: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="calendar_events")

    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "task_id",
            "user_id",
            "provider",
            name="uq_calendar_events_meeting_task_user_provider",
        ),
        Index("ix_calendar_events_meeting_id", "meeting_id"),
        Index("ix_calendar_events_user_id", "user_id"),
    )


class TranscriptTurnRow(Base):
    """Normalized transcript turn for application queries and training export."""

    __tablename__ = "transcript_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[str] = mapped_column(String(100), nullable=False)
    speaker_id: Mapped[str] = mapped_column(String(100), nullable=False)
    speaker_name: Mapped[str | None] = mapped_column(String(255))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    asr_confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="transcript_rows")

    __table_args__ = (
        UniqueConstraint("meeting_id", "turn_id", name="uq_transcript_turns_meeting_turn"),
        Index("ix_transcript_turns_meeting_id", "meeting_id"),
    )


class MeetingArtifact(Base):
    """Auditable raw or derived artifact linked to a meeting."""

    __tablename__ = "meeting_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    storage_uri: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    checksum: Mapped[str | None] = mapped_column(String(128))
    artifact_metadata: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="artifacts")

    __table_args__ = (
        Index("ix_meeting_artifacts_meeting_id", "meeting_id"),
        Index("ix_meeting_artifacts_type", "artifact_type"),
    )
