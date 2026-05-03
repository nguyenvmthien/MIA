"""
Google Calendar integration — OAuth 2.0 flow + event creation.

Environment variables (set in .env):
  GOOGLE_CLIENT_ID       — OAuth2 client ID from Google Cloud Console
  GOOGLE_CLIENT_SECRET   — OAuth2 client secret
  GOOGLE_REDIRECT_URI    — OAuth2 redirect URI (e.g. http://localhost:8000/auth/google/callback)

Scopes requested:
  https://www.googleapis.com/auth/calendar.events

The OAuth flow:
  1. GET  /auth/google/login   → redirect to Google consent screen
  2. GET  /auth/google/callback?code=...&state=...  → exchange code for tokens, store encrypted
  3. POST /meetings/{id}/calendar-sync  → create Calendar events from action items

Usage (internal):
  from meeting_agent.integrations.google_calendar import (
      get_auth_url, exchange_code, create_event_from_task, refresh_if_expired
  )
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL  = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def _cfg() -> tuple[str, str, str]:
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    redirect_uri  = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
    if not client_id or not client_secret:
        raise RuntimeError(
            "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env"
        )
    return client_id, client_secret, redirect_uri


def get_auth_url(state: str) -> str:
    """Return the Google OAuth consent screen URL."""
    client_id, _, redirect_uri = _cfg()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    client_id, client_secret, redirect_uri = _cfg()
    body = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:
        token_data = json.loads(resp.read())
    # Record expiry as absolute UTC timestamp
    expires_in = token_data.get("expires_in", 3600)
    token_data["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()
    return token_data


def refresh_token(token_dict: dict) -> dict:
    """Use the refresh_token to obtain a new access_token."""
    client_id, client_secret, _ = _cfg()
    body = urllib.parse.urlencode({
        "refresh_token": token_dict["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=10) as resp:
        new_data = json.loads(resp.read())
    token_dict["access_token"] = new_data["access_token"]
    expires_in = new_data.get("expires_in", 3600)
    token_dict["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    ).isoformat()
    return token_dict


def refresh_if_expired(user_id: str) -> dict | None:
    """
    Load token for user_id, refresh if expiring within 5 minutes, persist updated token.
    Returns the (possibly refreshed) token dict, or None if no token stored.
    """
    from meeting_agent.integrations.token_store import load_token, save_token
    token = load_token(user_id)
    if token is None:
        return None
    expires_at_str = token.get("expires_at")
    if expires_at_str:
        expires_at = datetime.fromisoformat(expires_at_str)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
            log.debug("Refreshing Google token for user %s", user_id)
            token = refresh_token(token)
            save_token(user_id, token)
    return token


def create_event_from_task(
    access_token: str,
    title: str,
    description: str,
    due_date: str | None,
    assignee_email: str | None = None,
) -> dict:
    """
    Create a Google Calendar event for a single action item.

    Args:
        access_token: valid OAuth2 access token
        title:        action item description (becomes event title)
        description:  full notes / context
        due_date:     ISO date string (YYYY-MM-DD) or None → tomorrow
        assignee_email: if provided, added as a guest attendee

    Returns:
        Google Calendar API response dict (contains 'id', 'htmlLink', etc.)
    """
    if due_date:
        try:
            event_date = date.fromisoformat(due_date)
        except ValueError:
            event_date = date.today() + timedelta(days=1)
    else:
        event_date = date.today() + timedelta(days=1)

    event = {
        "summary": title,
        "description": description,
        "start": {"date": event_date.isoformat()},
        "end":   {"date": (event_date + timedelta(days=1)).isoformat()},
    }
    if assignee_email:
        event["attendees"] = [{"email": assignee_email}]

    body = json.dumps(event).encode()
    req = urllib.request.Request(
        EVENTS_URL + "?sendUpdates=all",
        data=body,
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error("Google Calendar API error %s: %s", e.code, body)
        raise
