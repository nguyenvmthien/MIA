"""Tests for canonical data schemas."""

from datetime import date

import pytest
from pydantic import ValidationError

from meeting_agent.schemas.meeting import RunMetrics, StageTiming
from meeting_agent.schemas.task import ExtractedTask, TaskPriority, TaskStatus
from meeting_agent.schemas.transcript import TranscriptTurn
from meeting_agent.schemas.worker import Worker, WorkerRoster

# ── TranscriptTurn ────────────────────────────────────────────────────────────

def test_transcript_turn_valid():
    t = TranscriptTurn(
        turn_id="t1",
        speaker_id="SPEAKER_01",
        start_ms=0,
        end_ms=5000,
        text="Hello everyone.",
    )
    assert t.duration_ms == 5000
    assert t.display_name == "SPEAKER_01"


def test_transcript_turn_with_resolved_name():
    t = TranscriptTurn(
        turn_id="t2",
        speaker_id="SPEAKER_01",
        speaker_name="Alice Chen",
        start_ms=0,
        end_ms=3000,
        text="Let's get started.",
    )
    assert t.display_name == "Alice Chen"


def test_transcript_turn_end_before_start_raises():
    with pytest.raises(ValidationError, match="end_ms"):
        TranscriptTurn(
            turn_id="t3",
            speaker_id="SPEAKER_01",
            start_ms=5000,
            end_ms=1000,
            text="Bad timing.",
        )


# ── WorkerRoster ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_roster():
    return WorkerRoster(workers=[
        Worker(worker_id="w1", name="Alice Chen", aliases=["Alice"], role="Lead"),
        Worker(worker_id="w2", name="Bob Kim", aliases=["Bob", "Bobby"], role="Dev"),
    ])


def test_roster_exact_name_match(sample_roster):
    w = sample_roster.find_by_name("Alice Chen")
    assert w is not None
    assert w.worker_id == "w1"


def test_roster_alias_match(sample_roster):
    w = sample_roster.find_by_name("Bobby")
    assert w is not None
    assert w.worker_id == "w2"


def test_roster_case_insensitive(sample_roster):
    w = sample_roster.find_by_name("ALICE CHEN")
    assert w is not None


def test_roster_no_match_returns_none(sample_roster):
    w = sample_roster.find_by_name("Unknown Person")
    assert w is None


def test_roster_names_for_prompt(sample_roster):
    prompt = sample_roster.names_for_prompt()
    assert "Alice Chen" in prompt
    assert "Bob Kim" in prompt
    assert "aka" in prompt  # aliases shown


# ── ExtractedTask ─────────────────────────────────────────────────────────────

def test_extracted_task_defaults():
    task = ExtractedTask(
        task_id="t1",
        description="Write the report",
    )
    assert task.priority == TaskPriority.medium
    assert task.status == TaskStatus.open
    assert task.assignee is None
    assert task.due_date is None


def test_extracted_task_with_all_fields():
    task = ExtractedTask(
        task_id="t2",
        description="Deploy to staging",
        assignee="Bob Kim",
        assignee_id="w2",
        due_date=date(2026, 4, 20),
        priority=TaskPriority.high,
        status=TaskStatus.open,
    )
    assert task.due_date.isoformat() == "2026-04-20"
    assert task.extraction_confidence == 1.0


# ── RunMetrics / StageTiming ──────────────────────────────────────────────────

def test_stage_timing_total():
    st = StageTiming(ingest_ms=100, stt_ms=5000, llm_ms=3000)
    assert st.total_ms == 8100


def test_run_metrics_defaults():
    m = RunMetrics()
    assert m.hallucination_flags == 0
    assert m.tasks_extracted == 0
