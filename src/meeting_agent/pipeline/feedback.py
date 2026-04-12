"""
Feedback loop — stores user corrections to extracted tasks.

Corrections are accumulated as a JSONL file that the retraining
pipeline consumes to improve the model over time.
"""

import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from meeting_agent.config import settings

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
    is_false_positive: bool = False  # task shouldn't have been extracted at all
    is_missing: bool = False          # task was missed and added manually
    submitted_at: datetime | None = None

    def model_post_init(self, __context) -> None:
        if self.submitted_at is None:
            self.submitted_at = datetime.utcnow()


class FeedbackSubmission(BaseModel):
    corrections: list[TaskCorrection]
    reviewer: str | None = None
    notes: str | None = None


def save_feedback(submission: FeedbackSubmission) -> int:
    """
    Append corrections to the feedback JSONL store.
    Returns number of corrections saved.
    """
    FEEDBACK_STORE.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with FEEDBACK_STORE.open("a") as f:
        for correction in submission.corrections:
            f.write(correction.model_dump_json() + "\n")
            count += 1
    log.info("Saved %d feedback corrections to %s", count, FEEDBACK_STORE)
    return count


def load_feedback(limit: int = 1000) -> list[TaskCorrection]:
    """Load recent corrections from the feedback store."""
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
    """Return summary statistics about accumulated feedback."""
    corrections = load_feedback(limit=10_000)
    if not corrections:
        return {"total": 0}
    false_positives = sum(1 for c in corrections if c.is_false_positive)
    missing = sum(1 for c in corrections if c.is_missing)
    assignee_fixes = sum(
        1 for c in corrections
        if c.corrected_assignee and c.corrected_assignee != c.original_assignee
    )
    return {
        "total": len(corrections),
        "false_positives": false_positives,
        "missing_tasks": missing,
        "assignee_corrections": assignee_fixes,
    }
