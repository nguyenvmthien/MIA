"""Tests for prompt template rendering."""

from meeting_agent.prompts.templates import EXTRACT_TASKS_SYSTEM, EXTRACT_TASKS_USER, PROMPT_VERSION
from meeting_agent.schemas.worker import Worker, WorkerRoster


def test_prompt_version_is_string():
    assert isinstance(PROMPT_VERSION, str)
    assert len(PROMPT_VERSION) > 0


def test_extract_system_prompt_renders():
    roster = WorkerRoster(workers=[
        Worker(worker_id="w1", name="Alice Chen", aliases=["Alice"]),
    ])
    prompt = EXTRACT_TASKS_SYSTEM.format(
        roster=roster.names_for_prompt(),
        friday="2026-04-17",
    )
    assert "Alice Chen" in prompt
    assert "WORKER ROSTER" in prompt
    assert "assignee" in prompt
    assert "due_date" in prompt


def test_extract_user_prompt_renders():
    prompt = EXTRACT_TASKS_USER.format(
        meeting_date="2026-04-12",
        participants="Alice Chen, Bob Kim",
        transcript="[Alice Chen]: Bob, can you write the report?",
    )
    assert "2026-04-12" in prompt
    assert "Alice Chen" in prompt
    assert "Bob, can you write the report?" in prompt


def test_system_prompt_contains_guardrail_rules():
    prompt = EXTRACT_TASKS_SYSTEM.format(roster="- Alice", friday="2026-04-17")
    assert "Do NOT invent" in prompt
    assert "null" in prompt
    assert "empty array" in prompt.lower() or "[]" in prompt
