"""Tests for the feedback loop store."""

import json

import pytest

from meeting_agent.pipeline.feedback import (
    FeedbackSubmission,
    TaskCorrection,
    feedback_stats,
    load_feedback,
    save_feedback,
)


@pytest.fixture
def feedback_store(tmp_path, monkeypatch):
    """Redirect feedback store to a temp file."""
    import meeting_agent.pipeline.feedback as fb_module
    store = tmp_path / "_feedback.jsonl"
    monkeypatch.setattr(fb_module, "FEEDBACK_STORE", store)
    return store


def _make_submission(**kwargs):
    defaults = dict(
        meeting_id="meet-1",
        task_id="meet-1_c0_0",
        original_description="Write report",
        corrected_description="Write quarterly report",
        original_assignee="Alice",
        corrected_assignee="Alice Chen",
    )
    defaults.update(kwargs)
    return FeedbackSubmission(corrections=[TaskCorrection(**defaults)])


def test_save_and_load(feedback_store):
    submission = _make_submission()
    count = save_feedback(submission)
    assert count == 1
    loaded = load_feedback()
    assert len(loaded) == 1
    assert loaded[0].task_id == "meet-1_c0_0"


def test_save_multiple(feedback_store):
    sub1 = _make_submission(task_id="meet-1_c0_0")
    sub2 = _make_submission(task_id="meet-1_c0_1")
    save_feedback(sub1)
    save_feedback(sub2)
    loaded = load_feedback()
    assert len(loaded) == 2


def test_load_empty_store(feedback_store):
    assert load_feedback() == []


def test_load_nonexistent_store(tmp_path, monkeypatch):
    import meeting_agent.pipeline.feedback as fb_module
    monkeypatch.setattr(fb_module, "FEEDBACK_STORE", tmp_path / "nope.jsonl")
    assert load_feedback() == []


def test_feedback_stats_empty(feedback_store):
    stats = feedback_stats()
    assert stats == {"total": 0}


def test_feedback_stats_with_data(feedback_store):
    submission = FeedbackSubmission(corrections=[
        TaskCorrection(
            meeting_id="m1", task_id="t1",
            original_description="do x", is_false_positive=True,
            original_assignee="Alice", corrected_assignee="Bob",
        ),
        TaskCorrection(
            meeting_id="m1", task_id="t2",
            original_description="do y", is_missing=True,
            original_assignee="Alice", corrected_assignee="Alice",
        ),
    ])
    save_feedback(submission)
    stats = feedback_stats()
    assert stats["total"] == 2
    assert stats["false_positives"] == 1
    assert stats["missing_tasks"] == 1
    assert stats["assignee_corrections"] == 1


def test_task_correction_auto_timestamp():
    c = TaskCorrection(
        meeting_id="m1", task_id="t1",
        original_description="x",
    )
    assert c.submitted_at is not None


def test_save_feedback_jsonl_format(feedback_store):
    save_feedback(_make_submission())
    lines = feedback_store.read_text().strip().split("\n")
    assert len(lines) == 1
    data = json.loads(lines[0])
    assert data["task_id"] == "meet-1_c0_0"
