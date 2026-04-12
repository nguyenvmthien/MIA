"""ExtractedTask schema — the primary output of the LLM extraction stage."""

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class TaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TaskStatus(str, Enum):
    open = "open"
    unresolved = "unresolved"   # assignee could not be matched to roster
    human_review = "human_review"  # confidence below threshold


class ExtractedTask(BaseModel):
    task_id: str = Field(description="Unique identifier for this task")
    description: str = Field(description="Clear, actionable task description")
    assignee: str | None = Field(
        default=None,
        description="Name exactly as it appears in the worker roster (None if unassigned)",
    )
    assignee_id: str | None = Field(
        default=None,
        description="Resolved worker_id from roster (None if unresolved)",
    )
    due_date: date | None = Field(
        default=None,
        description="ISO 8601 date when the task is due",
    )
    priority: TaskPriority = Field(default=TaskPriority.medium)
    source_turn_ids: list[str] = Field(
        default_factory=list,
        description="IDs of TranscriptTurns that evidence this task",
    )
    extraction_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Model confidence score for this task extraction",
    )
    status: TaskStatus = Field(default=TaskStatus.open)
    notes: str | None = Field(
        default=None,
        description="Optional guardrail or assignment notes",
    )
