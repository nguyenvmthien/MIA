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

    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="meeting", cascade="all, delete-orphan"
    )
    corrections: Mapped[list["FeedbackCorrection"]] = relationship(
        "FeedbackCorrection", back_populates="meeting", cascade="all, delete-orphan"
    )
    meeting_participants: Mapped[list["MeetingParticipant"]] = relationship(
        "MeetingParticipant", back_populates="meeting", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_meetings_status", "status"),
        Index("ix_meetings_created_at", "created_at"),
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
