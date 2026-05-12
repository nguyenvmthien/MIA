"""Tests for Google Calendar OAuth flow and calendar-sync endpoint."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api.main import app

MEETING_ID = "cal-test-001"
USER_ID = "user-alice"

COMPLETED_MEETING = {
    "meeting_id": MEETING_ID,
    "status": "completed",
    "action_items": [
        {
            "task_id": f"{MEETING_ID}_t0",
            "description": "Send quarterly report",
            "assignee": "Alice Chen",
            "due_date": "2026-05-10",
            "priority": "high",
            "status": "open",
        },
        {
            "task_id": f"{MEETING_ID}_t1",
            "description": "Fix login bug",
            "assignee": "Bob Kim",
            "due_date": None,
            "priority": "medium",
            "status": "open",
        },
    ],
}

FAKE_TOKEN = {"access_token": "ya29.fake_token", "token_type": "Bearer"}

FAKE_EVENT = {
    "id": "gcal_event_001",
    "htmlLink": "https://calendar.google.com/event?eid=gcal_event_001",
}


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ── Auth status ───────────────────────────────────────────────────────────────

def test_auth_status_no_token(client):
    with patch("meeting_agent.api.calendar_router.has_token", return_value=False):
        resp = client.get(f"/auth/google/status/{USER_ID}")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": USER_ID, "connected": False}


def test_auth_status_with_token(client):
    with patch("meeting_agent.api.calendar_router.has_token", return_value=True):
        resp = client.get(f"/auth/google/status/{USER_ID}")
    assert resp.status_code == 200
    assert resp.json()["connected"] is True


# ── Token direct store ────────────────────────────────────────────────────────

def test_store_token_direct(client):
    with patch("meeting_agent.api.calendar_router.save_token") as mock_save:
        resp = client.post("/auth/google/token-direct", json={
            "user_id": USER_ID,
            "access_token": "ya29.test_token",
        })
    assert resp.status_code == 200
    assert resp.json()["stored"] is True
    mock_save.assert_called_once_with(USER_ID, {"access_token": "ya29.test_token"})


# ── Revoke token ──────────────────────────────────────────────────────────────

def test_revoke_token_success(client):
    with patch("meeting_agent.api.calendar_router.delete_token", return_value=True):
        resp = client.delete(f"/auth/google/token/{USER_ID}")
    assert resp.status_code == 200
    assert resp.json()["disconnected"] is True


def test_revoke_token_not_found(client):
    with patch("meeting_agent.api.calendar_router.delete_token", return_value=False):
        resp = client.delete(f"/auth/google/token/{USER_ID}")
    assert resp.status_code == 404


# ── Calendar sync ─────────────────────────────────────────────────────────────

def _mock_db_session(corrections=None):
    """Return a context manager mock with empty correction query."""
    mock_session = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.all.return_value = corrections or []
    mock_session.query.return_value = mock_query
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_session)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


def test_calendar_sync_creates_events(client):
    with patch("meeting_agent.db.repository.get_meeting", return_value=COMPLETED_MEETING), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=FAKE_TOKEN), \
         patch("meeting_agent.api.calendar_router._get_existing_calendar_event", return_value=None), \
         patch("meeting_agent.api.calendar_router._upsert_calendar_event", return_value={
             "event_id": FAKE_EVENT["id"],
             "html_link": FAKE_EVENT["htmlLink"],
         }), \
         patch("meeting_agent.api.calendar_router.create_event_from_task", return_value=FAKE_EVENT), \
         patch("meeting_agent.db.engine.get_session", return_value=_mock_db_session()):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["events_created"] == 2
    assert len(body["events"]) == 2
    assert body["events"][0]["event_id"] == "gcal_event_001"


def test_calendar_sync_skips_existing_events(client):
    with patch("meeting_agent.db.repository.get_meeting", return_value=COMPLETED_MEETING), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=FAKE_TOKEN), \
         patch("meeting_agent.api.calendar_router._get_existing_calendar_event", return_value={
             "event_id": "existing-event",
             "html_link": "https://calendar.google.com/event?eid=existing-event",
             "status": "created",
         }), \
         patch("meeting_agent.api.calendar_router.create_event_from_task") as mock_create, \
         patch("meeting_agent.db.engine.get_session", return_value=_mock_db_session()):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["events_created"] == 2
    assert body["events"][0]["status"] == "already_synced"
    mock_create.assert_not_called()


def test_calendar_sync_no_token(client):
    with patch("meeting_agent.db.repository.get_meeting", return_value=COMPLETED_MEETING), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=None):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 401


def test_calendar_sync_meeting_not_found(client):
    with patch("meeting_agent.db.repository.get_meeting", return_value=None):
        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")
    assert resp.status_code == 404


def test_calendar_sync_meeting_pending(client):
    pending = {**COMPLETED_MEETING, "status": "pending"}
    with patch("meeting_agent.db.repository.get_meeting", return_value=pending):
        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")
    assert resp.status_code == 404


def test_calendar_sync_empty_action_items(client):
    empty = {**COMPLETED_MEETING, "action_items": []}
    with patch("meeting_agent.db.repository.get_meeting", return_value=empty), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=FAKE_TOKEN), \
         patch("meeting_agent.db.engine.get_session", return_value=_mock_db_session()):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 200
    assert resp.json()["events_created"] == 0


def test_calendar_sync_applies_corrections(client):
    """Corrections should override task description/assignee before creating events."""
    from datetime import date

    from meeting_agent.db.models import FeedbackCorrection

    mock_correction = MagicMock(spec=FeedbackCorrection)
    mock_correction.task_id = f"{MEETING_ID}_t0"
    mock_correction.corrected_description = "Send Q1 board report"
    mock_correction.corrected_assignee = "Bob Kim"
    mock_correction.corrected_due_date = date(2026, 5, 15)
    mock_correction.is_false_positive = False
    mock_correction.is_missing = False

    captured_titles = []

    def capture_event(**kwargs):
        captured_titles.append(kwargs.get("title"))
        return FAKE_EVENT

    with patch("meeting_agent.db.repository.get_meeting", return_value=COMPLETED_MEETING), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=FAKE_TOKEN), \
         patch("meeting_agent.api.calendar_router._get_existing_calendar_event", return_value=None), \
         patch("meeting_agent.api.calendar_router._upsert_calendar_event", return_value={
             "event_id": FAKE_EVENT["id"],
             "html_link": FAKE_EVENT["htmlLink"],
         }), \
         patch("meeting_agent.api.calendar_router.create_event_from_task", side_effect=capture_event), \
         patch("meeting_agent.db.engine.get_session", return_value=_mock_db_session([mock_correction])):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 200
    assert "Send Q1 board report" in captured_titles


def test_calendar_sync_partial_failure(client):
    """If one event creation fails, others still succeed."""
    call_count = 0

    def flaky_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Google API timeout")
        return FAKE_EVENT

    with patch("meeting_agent.db.repository.get_meeting", return_value=COMPLETED_MEETING), \
         patch("meeting_agent.api.calendar_router.refresh_if_expired", return_value=FAKE_TOKEN), \
         patch("meeting_agent.api.calendar_router._get_existing_calendar_event", return_value=None), \
         patch("meeting_agent.api.calendar_router._upsert_calendar_event", return_value={
             "event_id": FAKE_EVENT["id"],
             "html_link": FAKE_EVENT["htmlLink"],
         }), \
         patch("meeting_agent.api.calendar_router._mark_calendar_event_failed"), \
         patch("meeting_agent.api.calendar_router.create_event_from_task", side_effect=flaky_create), \
         patch("meeting_agent.db.engine.get_session", return_value=_mock_db_session()):

        resp = client.post(f"/meetings/{MEETING_ID}/calendar-sync?user_id={USER_ID}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["events_created"] == 1
    assert len(body["errors"]) == 1
