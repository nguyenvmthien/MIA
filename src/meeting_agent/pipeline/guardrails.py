"""
Guardrail Engine — validates and sanitizes LLM input/output.

Responsibilities:
  - Input guardrails: jailbreak / prompt injection detection, PII scrub
  - Output guardrails: JSON schema validation, assignee whitelist,
    due date sanity check, hallucination detection
"""

import json
import logging
import re
import time
from datetime import date, timedelta

from pydantic import ValidationError

from meeting_agent.monitoring.metrics import (
    GUARDRAILS_DURATION,
    HALLUCINATION_FLAGS,
    SCHEMA_FAILURES,
)
from meeting_agent.pipeline.pii import mask_pii
from meeting_agent.schemas.task import ExtractedTask, TaskPriority, TaskStatus
from meeting_agent.schemas.transcript import TranscriptTurn
from meeting_agent.schemas.worker import Worker, WorkerRoster

log = logging.getLogger(__name__)


class GuardrailError(Exception):
    pass


# ── Jailbreak / prompt injection patterns ────────────────────────────────────
_JAILBREAK_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions",
        r"you\s+are\s+now\s+(a\s+)?(?:DAN|evil|unrestricted)",
        r"pretend\s+(you\s+are|to\s+be)\s+(?:a\s+)?(?:different|evil|unrestricted)",
        r"disregard\s+(your\s+)?(?:guidelines|rules|instructions)",
        r"<\s*script\b",                    # XSS attempt
        r"\bSYSTEM\s*:.*override\b",        # system override attempt
        r"jailbreak",
    ]
]


def sanitize_input(text: str) -> str:
    """
    Check transcript text for prompt injection / jailbreak patterns.
    Raises GuardrailError if a pattern is detected.
    Returns PII-masked text safe for injection into prompts.
    """
    for pattern in _JAILBREAK_PATTERNS:
        if pattern.search(text):
            log.warning("Jailbreak pattern detected in input: %s…", text[:80])
            raise GuardrailError(
                f"Input blocked by jailbreak guardrail: matched pattern '{pattern.pattern}'"
            )
    return mask_pii(text)


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences if the model wraps output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _find_json_array(text: str) -> str:
    """Extract the first JSON array from text."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        return match.group(0)
    raise GuardrailError(f"No JSON array found in LLM output: {text[:200]!r}")


def _validate_due_date(due_date_str: str | None) -> date | None:
    """Reject dates more than 1 year in the past or 5 years in the future."""
    if not due_date_str:
        return None
    try:
        d = date.fromisoformat(due_date_str)
    except ValueError:
        return None  # unparseable → treat as null
    today = date.today()
    if d < today - timedelta(days=365):
        return None  # suspiciously old — likely hallucinated
    if d > today + timedelta(days=365 * 5):
        return None  # too far future — likely hallucinated
    return d


def _check_hallucination(
    task_desc: str,
    assignee: str | None,
    turns: list[TranscriptTurn],
    worker: "Worker | None" = None,
) -> bool:
    """
    Flag a hallucination when the resolved worker's name (or any alias) does not
    appear anywhere in the transcript.  Only applied when the assignee was
    successfully matched to a known roster worker.

    Returns True if hallucination is suspected.
    """
    if assignee is None or worker is None:
        # Unresolved assignees are handled separately — not a hallucination signal.
        return False
    full_text = " ".join(t.text.lower() for t in turns)
    # Accept if any of the worker's known names appear in the transcript
    return not any(name in full_text for name in worker.all_names())


def parse_and_validate(
    raw_output: str,
    roster: WorkerRoster,
    turns: list[TranscriptTurn],
    source_turn_ids: list[str],
    task_id_prefix: str,
) -> list[ExtractedTask]:
    """
    Parse LLM JSON output and validate each extracted task.

    - Schema validation via Pydantic
    - Assignee whitelist against roster
    - Due date sanity check
    - Hallucination detection
    - Returns list of ExtractedTask (may be empty)
    """
    t0 = time.monotonic()
    cleaned = _strip_json_fences(raw_output)
    try:
        array_str = _find_json_array(cleaned)
        raw_items = json.loads(array_str)
    except (GuardrailError, json.JSONDecodeError) as exc:
        SCHEMA_FAILURES.inc()
        raise GuardrailError(f"Failed to parse LLM output as JSON: {exc}") from exc

    if not isinstance(raw_items, list):
        SCHEMA_FAILURES.inc()
        raise GuardrailError("LLM output is not a JSON array")

    tasks: list[ExtractedTask] = []

    for idx, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue

        task_id = f"{task_id_prefix}_{idx}"
        description = str(item.get("description", "")).strip()
        if not description:
            continue  # skip empty descriptions

        raw_assignee = item.get("assignee")
        assignee_name: str | None = None
        assignee_id: str | None = None
        status = TaskStatus.open

        matched_worker: Worker | None = None
        if raw_assignee:
            # LLM sometimes copies the prompt format "Alice Chen (aka Alice) [PM]".
            # Strip the "(aka ...)" and "[role]" suffixes before roster lookup.
            _raw = str(raw_assignee)
            normalized_assignee = re.sub(r'\s*\(aka[^)]*\)|\s*\[[^\]]*\]', '', _raw).strip()
            matched_worker = (
                roster.find_by_name(normalized_assignee) or roster.find_by_name(_raw)
            )
            if matched_worker:
                assignee_name = matched_worker.name
                assignee_id = matched_worker.worker_id
            else:
                # Name not in roster — mark unresolved + flag as invalid assignee
                assignee_name = str(raw_assignee)
                status = TaskStatus.unresolved
                HALLUCINATION_FLAGS.labels(reason="invalid_assignee").inc()

        # Hallucination check — only for roster-resolved workers
        if _check_hallucination(description, assignee_name, turns, worker=matched_worker):
            HALLUCINATION_FLAGS.labels(reason="no_evidence").inc()
            status = TaskStatus.human_review

        raw_due_date = item.get("due_date")
        due_date = _validate_due_date(raw_due_date)
        # Flag date hallucination when a due_date was provided but failed validation
        if raw_due_date and due_date is None:
            HALLUCINATION_FLAGS.labels(reason="date_hallucination").inc()

        raw_priority = item.get("priority", "medium")
        try:
            priority = TaskPriority(raw_priority)
        except ValueError:
            priority = TaskPriority.medium

        try:
            task = ExtractedTask(
                task_id=task_id,
                description=description,
                assignee=assignee_name,
                assignee_id=assignee_id,
                due_date=due_date,
                priority=priority,
                source_turn_ids=source_turn_ids,
                status=status,
                notes=item.get("notes"),
            )
        except ValidationError:
            SCHEMA_FAILURES.inc()
            continue

        tasks.append(task)

    GUARDRAILS_DURATION.observe(time.monotonic() - t0)
    return tasks
