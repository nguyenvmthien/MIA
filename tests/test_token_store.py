"""Tests for encrypted token storage path handling."""

from pathlib import Path

from meeting_agent.integrations import token_store


def test_token_path_hashes_user_id(monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(token_store, "_KEY_FILE", tmp_path / ".key")

    path = token_store._token_path("../alice@example.com")

    assert path.parent == tmp_path
    assert path.name.endswith(".enc")
    assert ".." not in path.name
    assert "/" not in path.name


def test_save_load_delete_token_uses_safe_path(monkeypatch, tmp_path):
    monkeypatch.setattr(token_store, "_TOKEN_DIR", tmp_path)
    monkeypatch.setattr(token_store, "_KEY_FILE", tmp_path / ".key")
    user_id = "../alice@example.com"

    token_store.save_token(user_id, {"access_token": "token"})

    assert token_store.has_token(user_id) is True
    assert token_store.load_token(user_id) == {"access_token": "token"}
    assert token_store.delete_token(user_id) is True
    assert token_store.has_token(user_id) is False
    assert not Path(tmp_path.parent / "alice@example.com.enc").exists()
