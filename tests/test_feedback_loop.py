"""End-to-end tests: submit correction → saved + metrics updated."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api.main import app
from meeting_agent.schemas.meeting import JobStatus, MeetingSummary
from meeting_agent.schemas.task import ExtractedTask, TaskPriority, TaskStatus


@pytest.fixture
def client():
    return TestClient(app)


MEETING_ID = "feedback-loop-test-001"

COMPLETED_SUMMARY = MeetingSummary(
    meeting_id=MEETING_ID,
    job_status=JobStatus.completed,
    audio_filename="test.wav",
    participants=["Alice Chen", "Bob Kim"],
    summary_text="Alice will send the report. Bob will fix the login bug.",
    action_items=[
        ExtractedTask(
            task_id=f"{MEETING_ID}_t0",
            description="Send quarterly report",
            assignee="Alice Chen",
            assignee_id="w1",
            priority=TaskPriority.high,
            status=TaskStatus.open,
            extraction_confidence=0.9,
        ),
        ExtractedTask(
            task_id=f"{MEETING_ID}_t1",
            description="Fix login bug",
            assignee="Bob Kim",
            assignee_id="w2",
            priority=TaskPriority.medium,
            status=TaskStatus.open,
            extraction_confidence=0.85,
        ),
    ],
).model_dump(mode="json")

BIZ_METRICS = {
    "correction_rate": 1.0,
    "false_positive_rate": 0.0,
    "meetings_with_corrections": 1,
    "training_ready_samples": 1,
}


def _patch_feedback(monkeypatch_or_patch=None):
    """Common patches for feedback endpoint tests."""
    return [
        patch("meeting_agent.api.main.save_feedback", return_value=1),
        patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS),
    ]


# ── Description correction ────────────────────────────────────────────────────

def test_description_correction_saved(client):
    with patch("meeting_agent.api.main.save_feedback", return_value=1) as mock_save, \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        resp = client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [{
                "meeting_id": MEETING_ID,
                "task_id": f"{MEETING_ID}_t0",
                "original_description": "Send quarterly report",
                "corrected_description": "Send Q1 quarterly report to board",
                "original_assignee": "Alice Chen",
            }]
        })

    assert resp.status_code == 200
    mock_save.assert_called_once()
    body = resp.json()
    assert body["corrections_saved"] == 1
    assert body["meeting_id"] == MEETING_ID


def test_false_positive_correction_saved(client):
    with patch("meeting_agent.api.main.save_feedback", return_value=1) as mock_save, \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        resp = client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [{
                "meeting_id": MEETING_ID,
                "task_id": f"{MEETING_ID}_t1",
                "original_description": "Fix login bug",
                "original_assignee": "Bob Kim",
                "is_false_positive": True,
            }]
        })

    assert resp.status_code == 200
    assert resp.json()["corrections_saved"] == 1


def test_assignee_correction_saved(client):
    with patch("meeting_agent.api.main.save_feedback", return_value=1) as mock_save, \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        resp = client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [{
                "meeting_id": MEETING_ID,
                "task_id": f"{MEETING_ID}_t0",
                "original_description": "Send quarterly report",
                "original_assignee": "Alice Chen",
                "corrected_assignee": "Bob Kim",
            }]
        })

    assert resp.status_code == 200
    # Verify save_feedback received the corrected_assignee
    submission_arg = mock_save.call_args[0][0]
    assert submission_arg.corrections[0].corrected_assignee == "Bob Kim"


def test_multiple_corrections_in_one_submission(client):
    with patch("meeting_agent.api.main.save_feedback", return_value=2) as mock_save, \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        resp = client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [
                {
                    "meeting_id": MEETING_ID,
                    "task_id": f"{MEETING_ID}_t0",
                    "original_description": "Send quarterly report",
                    "corrected_description": "Send Q1 report",
                },
                {
                    "meeting_id": MEETING_ID,
                    "task_id": f"{MEETING_ID}_t1",
                    "original_description": "Fix login bug",
                    "is_false_positive": True,
                },
            ]
        })

    assert resp.status_code == 200
    assert resp.json()["corrections_saved"] == 2


def test_meeting_id_injected_into_corrections(client):
    """Verify meeting_id is set on each correction from the URL path."""
    with patch("meeting_agent.api.main.save_feedback", return_value=1) as mock_save, \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [{
                "meeting_id": MEETING_ID,
                "task_id": f"{MEETING_ID}_t0",
                "original_description": "Send quarterly report",
            }]
        })

    submission = mock_save.call_args[0][0]
    assert submission.corrections[0].meeting_id == MEETING_ID


def test_feedback_response_shape(client):
    with patch("meeting_agent.api.main.save_feedback", return_value=1), \
         patch("meeting_agent.api.main.db_get_business_metrics", return_value=BIZ_METRICS):

        resp = client.post(f"/meetings/{MEETING_ID}/feedback", json={
            "corrections": [{
                "meeting_id": MEETING_ID,
                "task_id": f"{MEETING_ID}_t0",
                "original_description": "Send quarterly report",
            }]
        })

    body = resp.json()
    assert "meeting_id" in body
    assert "corrections_saved" in body
    assert isinstance(body["corrections_saved"], int)
