"""Backend authentication dependencies for FastAPI routes."""

from __future__ import annotations

import hmac
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

_TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: str = "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _split_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _auth_required() -> bool:
    return os.environ.get("BACKEND_AUTH_REQUIRED", "").strip().lower() in _TRUE_VALUES


def _configured_user_tokens() -> list[str]:
    return _split_tokens(
        os.environ.get("BACKEND_USER_TOKENS") or os.environ.get("BACKEND_USER_TOKEN")
    )


def _configured_admin_tokens() -> list[str]:
    return _split_tokens(
        os.environ.get("BACKEND_ADMIN_TOKENS") or os.environ.get("BACKEND_ADMIN_TOKEN")
    )


def auth_is_configured() -> bool:
    return _auth_required() or bool(_configured_user_tokens() or _configured_admin_tokens())


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    api_key = request.headers.get("x-api-key")
    return api_key.strip() if api_key else None


def _matches(token: str, candidates: list[str]) -> bool:
    return any(hmac.compare_digest(token, candidate) for candidate in candidates)


def _identity_from_request(request: Request, role: str) -> Principal:
    user_id = (
        request.headers.get("x-user-id")
        or request.headers.get("x-auth-user")
        or ("admin" if role == "admin" else "dev-user")
    )
    return Principal(user_id=user_id, role=role)


async def require_user(request: Request) -> Principal:
    """Require a configured user/admin token when backend auth is enabled."""
    user_tokens = _configured_user_tokens()
    admin_tokens = _configured_admin_tokens()
    if not auth_is_configured():
        return Principal(user_id="dev-user", role="admin")

    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token or X-API-Key",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if _matches(token, admin_tokens):
        return _identity_from_request(request, "admin")
    if _matches(token, user_tokens):
        return _identity_from_request(request, "user")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_admin(request: Request) -> Principal:
    """Require an admin token when backend auth is enabled."""
    principal = await require_user(request)
    if not principal.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return principal
