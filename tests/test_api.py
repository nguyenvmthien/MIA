"""Integration tests for the FastAPI application."""

import json
import uuid
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api.main import app
from meeting_agent.schemas.meeting import JobStatus, MeetingSummary
from meeting_agent.schemas.task import ExtractedTask, TaskPriority, TaskStatus


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def sample_roster_json():
    return json.dumps({
        "workers": [
            {"worker_id": "w1", "name": "Alice Chen", "aliases": ["Alice"],
             "role": "PM", "email": "alice@example.com"},
            {"worker_id": "w2", "name": "Bob Kim", "aliases": ["Bob"],
             "role": "Dev", "email": "bob@example.com"},
        ]
    })


@pytest.fixture
def sample_audio_bytes():
    """Minimal WAV header (44 bytes) — just enough for upload validation."""
    return b"RIFF" + b"\x00" * 40


@pytest.fixture
def completed_summary():
    return MeetingSummary(
        meeting_id="test-meeting-123",
        job_status=JobStatus.completed,
        audio_filename="upload.wav",
        participants=["Alice Chen", "Bob Kim"],
        summary_text="Alice will send the report. Bob will fix the bug.",
        action_items=[
            ExtractedTask(
                task_id="test-meeting-123_c0_0",
                description="Send quarterly report",
                assignee="Alice Chen",
                assignee_id="w1",
                due_date=None,
                priority=TaskPriority.high,
                status=TaskStatus.open,
                extraction_confidence=0.9,
            )
        ],
    ).model_dump()


# ── Health ────────────────────────────────────────────────────────────────────

def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "meeting_" in resp.text or "process_" in resp.text


# ── Submit meeting ─────────────────────────────────────────────────────────────

def test_submit_meeting_accepted(client, sample_roster_json, sample_audio_bytes):
    with patch("meeting_agent.api.main.process_meeting_task") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-abc")
        resp = client.post(
            "/meetings",
            files={"audio": ("meeting.wav", BytesIO(sample_audio_bytes), "audio/wav")},
            data={"roster_json": sample_roster_json},
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert "meeting_id" in body


def test_submit_meeting_invalid_roster(client, sample_audio_bytes):
    resp = client.post(
        "/meetings",
        files={"audio": ("meeting.wav", BytesIO(sample_audio_bytes), "audio/wav")},
        data={"roster_json": "not valid json"},
    )
    assert resp.status_code == 422


def test_submit_meeting_empty_roster(client, sample_audio_bytes):
    """Empty roster is valid — workers default to empty list."""
    with patch("meeting_agent.api.main.process_meeting_task") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-xyz")
        resp = client.post(
            "/meetings",
            files={"audio": ("meeting.wav", BytesIO(sample_audio_bytes), "audio/wav")},
            data={"roster_json": "{}"},
        )
    assert resp.status_code == 202


# ── Poll results ──────────────────────────────────────────────────────────────

def test_get_meeting_pending(client):
    with patch("meeting_agent.api.main.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = MagicMock(state="PENDING")
        resp = client.get("/meetings/some-id")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_get_meeting_processing(client):
    with patch("meeting_agent.api.main.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = MagicMock(state="STARTED")
        resp = client.get("/meetings/some-id")
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"


def test_get_meeting_failed(client):
    mock_result = MagicMock(state="FAILURE")
    mock_result.result = RuntimeError("STT crashed")
    with patch("meeting_agent.api.main.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = mock_result
        resp = client.get("/meetings/some-id")
    assert resp.status_code == 500
    assert resp.json()["status"] == "failed"


def test_get_meeting_completed(client, completed_summary):
    mock_result = MagicMock(state="SUCCESS", result=completed_summary)
    with patch("meeting_agent.api.main.celery_app") as mock_celery:
        mock_celery.AsyncResult.return_value = mock_result
        resp = client.get("/meetings/test-meeting-123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["job_status"] == "completed"
    assert len(body["action_items"]) == 1
    assert body["action_items"][0]["assignee"] == "Alice Chen"


# ── Feedback ──────────────────────────────────────────────────────────────────

def test_submit_feedback(client):
    payload = {
        "corrections": [
            {
                "meeting_id": "meet-1",
                "task_id": "meet-1_c0_0",
                "original_assignee": "Alice",
                "corrected_assignee": "Bob Kim",
                "original_description": "write docs",
                "corrected_description": "Write API documentation",
            }
        ],
        "reviewer": "Carol",
    }
    with patch("meeting_agent.api.main.save_feedback", return_value=1):
        resp = client.post("/meetings/meet-1/feedback", json=payload)
    assert resp.status_code == 200
    assert resp.json()["corrections_saved"] == 1


# ── GDPR delete ───────────────────────────────────────────────────────────────

def test_delete_meeting_no_data(client, tmp_path):
    """Delete on a non-existent meeting returns empty deleted_paths."""
    with patch("meeting_agent.api.main.settings") as mock_settings:
        mock_settings.audio_storage_path = str(tmp_path / "audio")
        mock_settings.transcript_storage_path = str(tmp_path / "transcripts")
        resp = client.delete("/meetings/nonexistent-id")
    assert resp.status_code == 200
    assert resp.json()["deleted_paths"] == []


# ── Guardrail: assignee name normalisation ────────────────────────────────────

def test_guardrail_strips_prompt_format_from_assignee():
    """LLM copies 'Alice Chen (aka Alice) [PM]' from prompt — must still resolve."""
    from meeting_agent.pipeline.guardrails import parse_and_validate
    from meeting_agent.schemas.transcript import TranscriptTurn
    from meeting_agent.schemas.worker import Worker, WorkerRoster

    roster = WorkerRoster(workers=[
        Worker(worker_id="w1", name="Alice Chen", aliases=["Alice"], role="PM"),
    ])
    turns = [
        TranscriptTurn(turn_id="t1", speaker_id="S0", start_ms=0, end_ms=3000,
                       text="Alice can you send the report by Friday?"),
    ]
    # LLM copies the formatted name exactly as shown in the prompt
    raw = json.dumps([{
        "description": "Send quarterly report",
        "assignee": "Alice Chen (aka Alice) [PM]",
        "due_date": "2026-04-18",
        "priority": "high",
        "notes": None,
    }])
    tasks = parse_and_validate(raw, roster, turns, ["t1"], "m1")
    assert len(tasks) == 1
    assert tasks[0].assignee == "Alice Chen"
    assert tasks[0].assignee_id == "w1"
    assert tasks[0].status == TaskStatus.open
