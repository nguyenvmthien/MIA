"""
Encrypted OAuth token store using Fernet symmetric encryption.

Tokens are stored per user_id in data/tokens/<user_id>.enc
The encryption key is derived from TOKEN_ENCRYPTION_KEY env var (or auto-generated
and saved to data/tokens/.key on first run — not suitable for production clusters;
set TOKEN_ENCRYPTION_KEY explicitly in .env for multi-process/multi-node setups).

Usage:
    from meeting_agent.integrations.token_store import save_token, load_token, delete_token

    save_token("user123", {"access_token": "...", "refresh_token": "...", ...})
    creds = load_token("user123")   # returns dict or None
    delete_token("user123")
"""

import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_TOKEN_DIR = Path("data/tokens")
_KEY_FILE = _TOKEN_DIR / ".key"


def _token_path(user_id: str) -> Path:
    """Return a safe token path for a user identifier."""
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()
    return _TOKEN_DIR / f"{digest}.enc"


def _get_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise ImportError("pip install cryptography") from e

    key_str = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()
    if key_str:
        key = key_str.encode()
    else:
        _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
        if _KEY_FILE.exists():
            key = _KEY_FILE.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            _KEY_FILE.write_bytes(key)
            _KEY_FILE.chmod(0o600)
            log.warning(
                "Generated new token encryption key at %s. "
                "Set TOKEN_ENCRYPTION_KEY env var for production.", _KEY_FILE
            )
    return Fernet(key)


def save_token(user_id: str, token_dict: dict) -> None:
    """Encrypt and persist a token dict for user_id."""
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    f = _get_fernet()
    encrypted = f.encrypt(json.dumps(token_dict).encode())
    path = _token_path(user_id)
    path.write_bytes(encrypted)
    path.chmod(0o600)
    log.debug("Token saved for user %s", user_id)


def load_token(user_id: str) -> dict | None:
    """Decrypt and return the stored token dict for user_id, or None if not found."""
    path = _token_path(user_id)
    if not path.exists():
        return None
    try:
        f = _get_fernet()
        decrypted = f.decrypt(path.read_bytes())
        return json.loads(decrypted)
    except Exception as e:
        log.warning("Failed to decrypt token for user %s: %s", user_id, e)
        return None


def delete_token(user_id: str) -> bool:
    """Delete stored token for user_id. Returns True if deleted."""
    path = _token_path(user_id)
    if path.exists():
        path.unlink()
        log.debug("Token deleted for user %s", user_id)
        return True
    return False


def has_token(user_id: str) -> bool:
    return _token_path(user_id).exists()
