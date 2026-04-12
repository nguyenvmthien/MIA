"""Stage 5 — Task Assignment: resolve speakers to workers and score confidence."""

import time
from difflib import SequenceMatcher

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import STAGE_LATENCY
from meeting_agent.schemas.task import ExtractedTask, TaskStatus
from meeting_agent.schemas.worker import Worker, WorkerRoster


def _fuzzy_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _resolve_by_fuzzy(name: str, roster: WorkerRoster, threshold: float = 0.8) -> Worker | None:
    """Fuzzy name match as fallback when exact match fails."""
    best_score = 0.0
    best_worker: Worker | None = None
    for worker in roster.workers:
        for candidate in worker.all_names():
            score = _fuzzy_score(name, candidate)
            if score > best_score:
                best_score = score
                best_worker = worker
    if best_score >= threshold:
        return best_worker
    return None


def _confidence_score(task: ExtractedTask) -> float:
    """
    Heuristic confidence score for an extracted task:
    - Starts at 1.0
    - Penalized for missing assignee, missing due date, unresolved status
    """
    score = 1.0
    if task.assignee is None:
        score -= 0.2
    if task.due_date is None:
        score -= 0.1
    if task.status == TaskStatus.unresolved:
        score -= 0.3
    if task.status == TaskStatus.human_review:
        score -= 0.5
    return max(0.0, round(score, 2))


def resolve_assignments(
    tasks: list[ExtractedTask],
    roster: WorkerRoster,
) -> list[ExtractedTask]:
    """
    For each task:
    1. Attempt exact roster match (already done in guardrails)
    2. If unresolved, attempt fuzzy match
    3. Score confidence; move below-threshold tasks to human_review
    4. Return updated task list
    """
    t0 = time.monotonic()
    resolved: list[ExtractedTask] = []

    for task in tasks:
        # Attempt fuzzy resolution for unresolved tasks
        if task.status == TaskStatus.unresolved and task.assignee:
            worker = _resolve_by_fuzzy(task.assignee, roster)
            if worker:
                task = task.model_copy(
                    update={
                        "assignee": worker.name,
                        "assignee_id": worker.worker_id,
                        "status": TaskStatus.open,
                        "notes": f"Fuzzy-matched '{task.assignee}' → '{worker.name}'",
                    }
                )
            else:
                # Could not resolve even with fuzzy → escalate to human review
                task = task.model_copy(update={"status": TaskStatus.human_review})

        # Score confidence
        confidence = _confidence_score(task)
        task = task.model_copy(update={"extraction_confidence": confidence})

        # Route low-confidence to human review
        if confidence < settings.task_confidence_threshold:
            task = task.model_copy(update={"status": TaskStatus.human_review})

        resolved.append(task)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    STAGE_LATENCY.labels(stage="assignment").observe(elapsed_ms / 1000)
    return resolved
