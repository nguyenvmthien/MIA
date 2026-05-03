"""Tests for the Task Assignment resolver."""

import pytest

from meeting_agent.pipeline.assignment import _confidence_score, _fuzzy_score, resolve_assignments
from meeting_agent.schemas.task import ExtractedTask, TaskStatus


# ── Fuzzy scoring ─────────────────────────────────────────────────────────────

def test_fuzzy_score_exact():
    assert _fuzzy_score("alice", "alice") == 1.0


def test_fuzzy_score_partial():
    score = _fuzzy_score("Alic", "Alice")
    assert score > 0.7


def test_fuzzy_score_unrelated():
    score = _fuzzy_score("xyz123", "Alice Chen")
    assert score < 0.5


# ── Confidence scoring ────────────────────────────────────────────────────────

def test_confidence_full_task():
    from datetime import date
    task = ExtractedTask(
        task_id="t1",
        description="Do something",
        assignee="Alice Chen",
        assignee_id="w1",
        due_date=date(2026, 5, 1),
        status=TaskStatus.open,
    )
    assert _confidence_score(task) == 1.0


def test_confidence_no_assignee_no_date():
    task = ExtractedTask(task_id="t2", description="Do something")
    score = _confidence_score(task)
    assert score == pytest.approx(0.7, abs=0.05)


def test_confidence_unresolved_status():
    task = ExtractedTask(
        task_id="t3",
        description="Do something",
        status=TaskStatus.unresolved,
    )
    score = _confidence_score(task)
    assert score < 0.7


# ── resolve_assignments ───────────────────────────────────────────────────────

def test_resolve_fuzzy_match(roster):
    """'Alise' should fuzzy-match to 'Alice Chen'."""
    task = ExtractedTask(
        task_id="t1",
        description="Write docs",
        assignee="Alise",   # typo
        status=TaskStatus.unresolved,
    )
    resolved = resolve_assignments([task], roster)
    assert resolved[0].assignee == "Alice Chen"
    assert resolved[0].assignee_id == "w1"
    assert resolved[0].status == TaskStatus.open


def test_resolve_no_match_stays_unresolved(roster):
    task = ExtractedTask(
        task_id="t2",
        description="Do something",
        assignee="Completely Unknown Name",
        status=TaskStatus.unresolved,
    )
    resolved = resolve_assignments([task], roster)
    # Still unresolved (or moved to human_review by confidence)
    assert resolved[0].status in {TaskStatus.unresolved, TaskStatus.human_review}


def test_resolve_open_task_unchanged(roster):
    task = ExtractedTask(
        task_id="t3",
        description="Send report",
        assignee="Alice Chen",
        assignee_id="w1",
        status=TaskStatus.open,
    )
    resolved = resolve_assignments([task], roster)
    assert resolved[0].assignee == "Alice Chen"
    assert resolved[0].status == TaskStatus.open


def test_resolve_low_confidence_routed_to_review(roster):
    """A task with no assignee and no date has low confidence → human_review."""
    task = ExtractedTask(
        task_id="t4",
        description="Handle something vague",
        status=TaskStatus.unresolved,
        assignee="Ghost Person",
    )
    resolved = resolve_assignments([task], roster)
    assert resolved[0].status == TaskStatus.human_review
