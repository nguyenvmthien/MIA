"""
FastAPI router for Google Calendar OAuth + calendar-sync endpoints.

Mount in main.py:
    from meeting_agent.api.calendar_router import router as calendar_router
    app.include_router(calendar_router)

Endpoints:
    GET  /auth/google/login              → redirect to Google consent screen
    GET  /auth/google/callback           → exchange code, store token, redirect to UI
    GET  /auth/google/status/{user_id}   → check if user has valid token
    DELETE /auth/google/token/{user_id}  → revoke & delete stored token
    POST /meetings/{meeting_id}/calendar-sync  → create Calendar events from action items
"""

import logging
import os
import secrets

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from meeting_agent.integrations.google_calendar import (
    create_event_from_task,
    exchange_code,
    get_auth_url,
    refresh_if_expired,
)
from meeting_agent.integrations.token_store import delete_token, has_token, save_token
from meeting_agent.monitoring.metrics import CALENDAR_EVENTS_CREATED

log = logging.getLogger(__name__)

router = APIRouter(tags=["calendar"])

# In-memory CSRF state store (suitable for single-process; swap for Redis in production)
_pending_states: dict[str, str] = {}


# ── OAuth flow ────────────────────────────────────────────────────────────────

@router.get("/auth/google/login")
async def google_login(user_id: str = Query(..., description="Caller-supplied user identifier")):
    """
    Start the Google OAuth2 flow.

    Generates a CSRF state token, builds the consent URL, and redirects the
    browser. On completion Google calls /auth/google/callback.
    """
    try:
        state = secrets.token_urlsafe(24)
        _pending_states[state] = user_id
        url = get_auth_url(state=state)
        return RedirectResponse(url)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/auth/google/callback")
async def google_callback(
    code: str = Query(...),
    state: str = Query(...),
    error: str | None = Query(default=None),
):
    """
    Google OAuth2 callback — exchange code for tokens and persist encrypted.

    On success redirects to the Streamlit UI at /?calendar=connected.
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")

    user_id = _pending_states.pop(state, None)
    if user_id is None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    try:
        token = exchange_code(code)
    except Exception as e:
        log.error("Token exchange failed: %s", e)
        raise HTTPException(status_code=502, detail="Token exchange failed")

    save_token(user_id, token)
    log.info("Google Calendar connected for user %s", user_id)

    ui_url = os.environ.get("STREAMLIT_URL", "http://localhost:8501")
    return RedirectResponse(f"{ui_url}/?calendar=connected&user_id={user_id}")


@router.get("/auth/google/status/{user_id}", tags=["calendar"])
async def google_auth_status(user_id: str):
    """Return whether the user has a stored Google Calendar token."""
    return {"user_id": user_id, "connected": has_token(user_id)}


@router.delete("/auth/google/token/{user_id}", tags=["calendar"])
async def revoke_google_token(user_id: str):
    """Delete the stored Google Calendar token for user_id."""
    deleted = delete_token(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No token found for user '{user_id}'")
    return {"user_id": user_id, "disconnected": True}


class _DirectTokenBody(BaseModel):
    user_id: str
    access_token: str


@router.post("/auth/google/token-direct", tags=["calendar"])
async def store_token_direct(body: _DirectTokenBody):
    """
    Accept an access token obtained by the Next.js frontend (NextAuth)
    and persist it so the backend can call the Calendar API on behalf of the user.
    """
    save_token(body.user_id, {"access_token": body.access_token})
    return {"user_id": body.user_id, "stored": True}


# ── Calendar sync ─────────────────────────────────────────────────────────────

class _CalendarSyncBody(BaseModel):
    task_ids: list[str] | None = None  # if None → sync all action_items


@router.post("/meetings/{meeting_id}/calendar-sync", tags=["calendar"])
async def sync_to_calendar(
    meeting_id: str,
    user_id: str = Query(..., description="User whose Google Calendar to write to"),
    body: _CalendarSyncBody = _CalendarSyncBody(),
):
    """
    Create Google Calendar events for all action items in a completed meeting.

    Reads the meeting result from Celery result backend, then creates one
    all-day Calendar event per action item on its due_date.

    Returns a list of created event IDs and HTML links.
    """
    from meeting_agent.db.engine import get_session
    from meeting_agent.db.models import FeedbackCorrection
    from meeting_agent.db.repository import get_meeting

    # Fetch meeting from DB (includes any feedback-corrected state)
    meeting_data = get_meeting(meeting_id)
    if meeting_data is None or meeting_data.get("status") not in ("completed", "done"):
        raise HTTPException(
            status_code=404,
            detail=f"Meeting {meeting_id} not found or not yet completed",
        )

    # Get and possibly refresh token
    token = refresh_if_expired(user_id)
    if token is None:
        raise HTTPException(
            status_code=401,
            detail=f"No Google Calendar token for user '{user_id}'. Visit /auth/google/login?user_id={user_id}",
        )

    access_token: str = token["access_token"]
    action_items: list[dict] = list(meeting_data.get("action_items", []))
    # Filter to only selected tasks if caller specified task_ids
    if body.task_ids is not None:
        task_id_set = set(body.task_ids)
        action_items = [t for t in action_items if t.get("task_id") in task_id_set]

    # Apply latest feedback corrections — override assignee/description if corrected
    with get_session() as _sess:
        rows = (
            _sess.query(FeedbackCorrection)
            .filter(
                FeedbackCorrection.meeting_id == meeting_id,
                FeedbackCorrection.is_false_positive.is_(False),
                FeedbackCorrection.is_missing.is_(False),
            )
            .all()
        )
        # Eagerly read all attributes inside session to avoid DetachedInstanceError
        correction_map: dict[str, dict] = {
            c.task_id: {
                "corrected_assignee": c.corrected_assignee,
                "corrected_description": c.corrected_description,
                "corrected_due_date": c.corrected_due_date.isoformat() if c.corrected_due_date else None,
            }
            for c in rows if c.task_id
        }

    for item in action_items:
        c = correction_map.get(item.get("task_id", ""))
        if c:
            if c["corrected_assignee"]:
                item["assignee"] = c["corrected_assignee"]
            if c["corrected_description"]:
                item["description"] = c["corrected_description"]
            if c["corrected_due_date"]:
                item["due_date"] = c["corrected_due_date"]

    if not action_items:
        return {"meeting_id": meeting_id, "events_created": 0, "events": []}

    # Look up worker email from registry if available
    def _worker_email(assignee: str | None) -> str | None:
        if not assignee:
            return None
        try:
            from meeting_agent.pipeline.worker_registry import list_workers
            for w in list_workers():
                if w.name.lower() == (assignee or "").lower() or w.worker_id == assignee:
                    return w.email
        except Exception:
            pass
        return None

    created_events = []
    errors = []

    for item in action_items:
        title = item.get("description", "Action item")
        due = item.get("due_date")
        assignee = item.get("assignee")
        notes = item.get("notes", "")
        description = f"Meeting: {meeting_id}\nAssignee: {assignee or 'unassigned'}\n{notes}".strip()
        email = _worker_email(assignee)

        try:
            event = create_event_from_task(
                access_token=access_token,
                title=title,
                description=description,
                due_date=due,
                assignee_email=email,
            )
            created_events.append({
                "task_description": title,
                "event_id": event.get("id"),
                "html_link": event.get("htmlLink"),
                "due_date": due,
            })
            CALENDAR_EVENTS_CREATED.inc()
        except Exception as e:
            log.warning("Failed to create Calendar event for task '%s': %s", title, e)
            errors.append({"task": title, "error": str(e)})

    # Persist event IDs alongside meeting result (best-effort)
    try:
        _save_calendar_ids(meeting_id, created_events)
    except Exception:
        pass

    return {
        "meeting_id": meeting_id,
        "events_created": len(created_events),
        "events": created_events,
        "errors": errors,
    }


def _save_calendar_ids(meeting_id: str, events: list[dict]) -> None:
    import json
    from pathlib import Path
    out = Path("data/transcripts") / f"{meeting_id}_calendar.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meeting_id": meeting_id, "events": events}, indent=2))
