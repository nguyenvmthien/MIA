"""MeetingSummary and RunMetrics — top-level output artifacts."""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from .task import ExtractedTask


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class StageTiming(BaseModel):
    ingest_ms: int = 0
    preprocess_ms: int = 0
    stt_ms: int = 0
    diarize_ms: int = 0
    llm_ms: int = 0
    assignment_ms: int = 0
    persist_ms: int = 0

    @property
    def total_ms(self) -> int:
        return (
            self.ingest_ms
            + self.preprocess_ms
            + self.stt_ms
            + self.diarize_ms
            + self.llm_ms
            + self.assignment_ms
            + self.persist_ms
        )


class RunMetrics(BaseModel):
    wer_estimate: float | None = Field(default=None, description="Word Error Rate (0-1)")
    diarization_error: float | None = Field(
        default=None, description="Diarization Error Rate (0-1)"
    )
    total_tokens_used: int = Field(default=0)
    llm_calls: int = Field(default=0)
    hallucination_flags: int = Field(default=0)
    schema_validation_failures: int = Field(default=0)
    tasks_extracted: int = Field(default=0)
    tasks_unresolved: int = Field(default=0)
    tasks_human_review: int = Field(default=0)
    stage_timings: StageTiming = Field(default_factory=StageTiming)


class MeetingSummary(BaseModel):
    meeting_id: str = Field(description="Unique meeting identifier")
    job_status: JobStatus = Field(default=JobStatus.pending)
    audio_filename: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
    duration_ms: int | None = None
    participants: list[str] = Field(default_factory=list)
    meeting_participants: list[dict] = Field(default_factory=list)
    transcript_turns: list[dict] = Field(default_factory=list)
    summary_text: str | None = None
    action_items: list[ExtractedTask] = Field(default_factory=list)
    unresolved_items: list[ExtractedTask] = Field(default_factory=list)
    human_review_items: list[ExtractedTask] = Field(default_factory=list)
    run_metrics: RunMetrics = Field(default_factory=RunMetrics)
    error: str | None = None
    model_version: str | None = None
