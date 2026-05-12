from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from meeting_agent.api.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("BACKEND_USER_TOKEN", "user-token")
    monkeypatch.setenv("BACKEND_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("BACKEND_AUTH_REQUIRED", "true")


def test_protected_meeting_requires_token(client):
    resp = client.get("/meetings/some-id")

    assert resp.status_code == 401


def test_user_token_can_access_meeting(client):
    with patch("meeting_agent.api.main.celery_app") as mock_celery, \
         patch("meeting_agent.api.main.db_get_meeting", return_value={"meeting_id": "some-id"}):
        mock_celery.AsyncResult.return_value = MagicMock(state="PENDING")
        resp = client.get(
            "/meetings/some-id",
            headers={"Authorization": "Bearer user-token", "X-User-Id": "user-1"},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"


def test_user_token_cannot_access_unowned_meeting(client):
    with patch("meeting_agent.api.main.celery_app") as mock_celery, \
         patch("meeting_agent.api.main.db_get_meeting", return_value=None):
        mock_celery.AsyncResult.return_value = MagicMock(state="PENDING")
        resp = client.get(
            "/meetings/some-id",
            headers={"Authorization": "Bearer user-token", "X-User-Id": "user-1"},
        )

    assert resp.status_code == 404


def test_admin_endpoint_rejects_user_token(client):
    resp = client.get(
        "/admin/router-stats",
        headers={"Authorization": "Bearer user-token", "X-User-Id": "user-1"},
    )

    assert resp.status_code == 403


def test_admin_endpoint_accepts_admin_token(client):
    resp = client.get(
        "/admin/router-stats",
        headers={"Authorization": "Bearer admin-token", "X-User-Id": "admin-1"},
    )

    assert resp.status_code == 200


def test_calendar_token_direct_uses_authenticated_user(client):
    with patch("meeting_agent.api.calendar_router.save_token") as mock_save:
        resp = client.post(
            "/auth/google/token-direct",
            headers={"Authorization": "Bearer user-token", "X-User-Id": "real-user"},
            json={"user_id": "attacker", "access_token": "ya29.test"},
        )

    assert resp.status_code == 200
    assert resp.json()["user_id"] == "real-user"
    mock_save.assert_called_once_with("real-user", {"access_token": "ya29.test"})
