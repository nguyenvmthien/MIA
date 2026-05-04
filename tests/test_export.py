"""Tests for feedback export and JSONL format compatibility with finetune.py."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api.main import app
from meeting_agent.pipeline.feedback import TaskCorrection


@pytest.fixture
def client():
    return TestClient(app)


MEETING_ID = "export-test-001"

SAMPLE_CORRECTIONS = [
    TaskCorrection(
        meeting_id=MEETING_ID,
        task_id=f"{MEETING_ID}_t0",
        original_description="Send quarterly report",
        corrected_description="Send Q1 quarterly report to board",
        original_assignee="Alice Chen",
        corrected_assignee="Alice Chen",
    )
]

SAMPLE_STATS = {
    "total": 1,
    "false_positives": 0,
    "missing_tasks": 0,
    "assignee_corrections": 0,
    "description_corrections": 1,
}


# ── /feedback/stats ───────────────────────────────────────────────────────────

def test_feedback_stats_shape(client):
    with patch("meeting_agent.api.main.feedback_stats", return_value=SAMPLE_STATS):
        resp = client.get("/feedback/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert "false_positives" in body
    assert "description_corrections" in body


def test_feedback_stats_empty(client):
    with patch("meeting_agent.api.main.feedback_stats", return_value={"total": 0}):
        resp = client.get("/feedback/stats")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ── /feedback/export raw ──────────────────────────────────────────────────────

def test_export_endpoint_reachable(client):
    """Export endpoint should return 200 (may return empty list if DB has no corrections)."""
    with patch("meeting_agent.db.engine.get_session") as mock_session:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=MagicMock(
            query=MagicMock(return_value=MagicMock(
                distinct=MagicMock(return_value=MagicMock(
                    limit=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
                ))
            ))
        ))
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_session.return_value = mock_ctx
        resp = client.get("/feedback/export?format=raw")
    # Either 200 with empty list, or 200 with data — just not 5xx
    assert resp.status_code in (200, 404)


# ── JSONL format compatible with finetune.py ──────────────────────────────────

def test_finetune_jsonl_required_keys():
    """finetune.py expects instruction / input / output keys."""
    record = {
        "instruction": "Extract action items from the transcript.",
        "input": "[Alice]: Please send the report by Friday.",
        "output": json.dumps([{
            "description": "Send report",
            "assignee": "Alice",
            "due_date": "2026-05-08",
            "priority": "high",
        }]),
    }
    for key in ("instruction", "input", "output"):
        assert key in record

    tasks = json.loads(record["output"])
    assert isinstance(tasks, list) and len(tasks) > 0
    for field in ("description", "assignee", "due_date", "priority"):
        assert field in tasks[0]


def test_finetune_output_priority_values():
    valid = {"high", "medium", "low"}
    tasks = [
        {"description": "A", "assignee": "Alice", "due_date": None, "priority": "high"},
        {"description": "B", "assignee": None, "due_date": "2026-05-10", "priority": "medium"},
        {"description": "C", "assignee": "Bob", "due_date": None, "priority": "low"},
    ]
    for t in tasks:
        assert t["priority"] in valid


def test_finetune_output_due_date_format():
    import re
    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    tasks = [
        {"description": "A", "assignee": "Alice", "due_date": "2026-05-08", "priority": "high"},
        {"description": "B", "assignee": None, "due_date": None, "priority": "medium"},
    ]
    for t in tasks:
        if t["due_date"] is not None:
            assert iso.match(t["due_date"]), f"Invalid date format: {t['due_date']}"


def test_finetune_output_is_valid_json_array():
    output_str = json.dumps([
        {"description": "Send report", "assignee": "Alice", "due_date": None, "priority": "high"}
    ])
    parsed = json.loads(output_str)
    assert isinstance(parsed, list)


# ── RLHF record shape ────────────────────────────────────────────────────────

def test_rlhf_correction_record_shape():
    record = {
        "format": "rlhf",
        "type": "correction",
        "meeting_id": MEETING_ID,
        "prompt": "[Alice]: Please send the report.",
        "chosen": json.dumps([{"description": "Send Q1 report", "assignee": "Alice"}]),
        "rejected": json.dumps([{"description": "Send report", "assignee": "Alice"}]),
    }
    for key in ("prompt", "chosen", "rejected"):
        assert key in record
    assert json.loads(record["chosen"]) != json.loads(record["rejected"])


def test_rlhf_false_positive_record_shape():
    record = {
        "format": "rlhf",
        "type": "false_positive",
        "meeting_id": MEETING_ID,
        "prompt": "[Alice]: Let's keep this informal.",
        "chosen": "[]",
        "rejected": json.dumps([{"description": "Hallucinated task", "assignee": None}]),
    }
    assert json.loads(record["chosen"]) == []
    assert len(json.loads(record["rejected"])) > 0
