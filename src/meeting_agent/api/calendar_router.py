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

from meeting_agent.integrations.google_calendar import (
    create_event_from_task,
    exchange_code,
    get_auth_url,
    refresh_if_expired,
)
from meeting_agent.integrations.token_store import delete_token, has_token, load_token, save_token

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


# ── Calendar sync ─────────────────────────────────────────────────────────────

@router.post("/meetings/{meeting_id}/calendar-sync", tags=["calendar"])
async def sync_to_calendar(
    meeting_id: str,
    user_id: str = Query(..., description="User whose Google Calendar to write to"),
):
    """
    Create Google Calendar events for all action items in a completed meeting.

    Reads the meeting result from Celery result backend, then creates one
    all-day Calendar event per action item on its due_date.

    Returns a list of created event IDs and HTML links.
    """
    from meeting_agent.pipeline.worker_task import celery_app

    # Fetch meeting result
    result = celery_app.AsyncResult(meeting_id)
    if result.state not in ("SUCCESS",):
        raise HTTPException(
            status_code=404,
            detail=f"Meeting {meeting_id} not found or not yet completed (state={result.state})",
        )
    meeting_data: dict = result.result

    # Get and possibly refresh token
    token = refresh_if_expired(user_id)
    if token is None:
        raise HTTPException(
            status_code=401,
            detail=f"No Google Calendar token for user '{user_id}'. Visit /auth/google/login?user_id={user_id}",
        )

    access_token: str = token["access_token"]
    action_items: list[dict] = meeting_data.get("action_items", [])

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
