"""Tests for the Guardrail Engine."""

import json
import pytest
from datetime import date

from meeting_agent.pipeline.guardrails import (
    GuardrailError,
    _strip_json_fences,
    _find_json_array,
    _validate_due_date,
    _check_hallucination,
    parse_and_validate,
)
from meeting_agent.schemas.transcript import TranscriptTurn
from meeting_agent.schemas.task import TaskStatus
from meeting_agent.schemas.worker import Worker, WorkerRoster


# ── Helpers ───────────────────────────────────────────────────────────────────

def test_strip_json_fences_with_markdown():
    raw = "```json\n[{\"a\": 1}]\n```"
    assert _strip_json_fences(raw) == '[{"a": 1}]'


def test_strip_json_fences_plain():
    raw = '[{"a": 1}]'
    assert _strip_json_fences(raw) == '[{"a": 1}]'


def test_find_json_array_extracts_array():
    text = 'some text [{"key": "val"}] more text'
    assert _find_json_array(text) == '[{"key": "val"}]'


def test_find_json_array_raises_on_missing():
    with pytest.raises(GuardrailError):
        _find_json_array("no array here")


def test_validate_due_date_valid():
    d = _validate_due_date("2026-06-01")
    assert d == date(2026, 6, 1)


def test_validate_due_date_too_old_returns_none():
    d = _validate_due_date("2020-01-01")
    assert d is None


def test_validate_due_date_unparseable_returns_none():
    d = _validate_due_date("next Friday")
    assert d is None


def test_validate_due_date_none_input():
    d = _validate_due_date(None)
    assert d is None


def test_check_hallucination_name_in_transcript():
    turns = [
        TranscriptTurn(turn_id="t1", speaker_id="S1", start_ms=0, end_ms=1000,
                       text="Alice should handle the report."),
    ]
    assert _check_hallucination("write report", "Alice", turns) is False


def test_check_hallucination_name_missing_from_transcript():
    from meeting_agent.schemas.worker import Worker
    # Worker "Charlie" resolved from roster but NOT mentioned in the transcript → hallucination
    charlie = Worker(worker_id="w9", name="Charlie", aliases=["Chuck"])
    turns = [
        TranscriptTurn(turn_id="t1", speaker_id="S1", start_ms=0, end_ms=1000,
                       text="We need to finish the report."),
    ]
    assert _check_hallucination("finish report", "Charlie", turns, worker=charlie) is True


def test_check_hallucination_null_assignee_never_flags():
    turns = [
        TranscriptTurn(turn_id="t1", speaker_id="S1", start_ms=0, end_ms=1000,
                       text="Someone should do this."),
    ]
    assert _check_hallucination("do something", None, turns) is False


# ── parse_and_validate ────────────────────────────────────────────────────────

@pytest.fixture
def roster():
    return WorkerRoster(workers=[
        Worker(worker_id="w1", name="Alice Chen", aliases=["Alice"]),
        Worker(worker_id="w2", name="Bob Kim", aliases=["Bob"]),
    ])


@pytest.fixture
def turns():
    return [
        TranscriptTurn(turn_id="t1", speaker_id="S1", speaker_name="Alice Chen",
                       start_ms=0, end_ms=5000,
                       text="Alice can you write the API docs by Friday?"),
    ]


def test_parse_valid_output(roster, turns):
    raw = json.dumps([{
        "description": "Write API docs",
        "assignee": "Alice",
        "due_date": "2026-04-18",
        "priority": "high",
        "notes": None,
    }])
    tasks = parse_and_validate(raw, roster, turns, ["t1"], "meet1")
    assert len(tasks) == 1
    assert tasks[0].assignee == "Alice Chen"
    assert tasks[0].assignee_id == "w1"
    assert tasks[0].status == TaskStatus.open


def test_parse_unresolved_assignee(roster, turns):
    raw = json.dumps([{
        "description": "Review the PR",
        "assignee": "Charlie",
        "due_date": None,
        "priority": "medium",
        "notes": None,
    }])
    tasks = parse_and_validate(raw, roster, turns, ["t1"], "meet1")
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.unresolved


def test_parse_empty_array(roster, turns):
    tasks = parse_and_validate("[]", roster, turns, [], "meet1")
    assert tasks == []


def test_parse_invalid_json_raises(roster, turns):
    with pytest.raises(GuardrailError):
        parse_and_validate("not json at all", roster, turns, [], "meet1")


def test_parse_markdown_fenced_output(roster, turns):
    raw = "```json\n[{\"description\": \"Send email\", \"assignee\": \"Bob\", \"due_date\": null, \"priority\": \"low\", \"notes\": null}]\n```"
    tasks = parse_and_validate(raw, roster, turns, ["t1"], "meet1")
    assert len(tasks) == 1
    assert tasks[0].assignee == "Bob Kim"


def test_parse_skips_empty_descriptions(roster, turns):
    raw = json.dumps([
        {"description": "", "assignee": "Alice", "due_date": None, "priority": "low", "notes": None},
        {"description": "Valid task", "assignee": None, "due_date": None, "priority": "low", "notes": None},
    ])
    tasks = parse_and_validate(raw, roster, turns, ["t1"], "meet1")
    assert len(tasks) == 1
    assert tasks[0].description == "Valid task"
