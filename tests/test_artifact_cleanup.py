from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from scripts.cleanup_artifacts import cleanup_artifacts


def test_cleanup_artifacts_dry_run_does_not_mutate(tmp_path):
    artifact_file = tmp_path / "audio.wav"
    artifact_file.write_bytes(b"audio")

    artifact = MagicMock()
    artifact.artifact_type = "uploaded_audio"
    artifact.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    artifact.storage_uri = str(artifact_file)
    artifact.payload = {"raw": "data"}
    artifact.artifact_metadata = {}

    session = MagicMock()
    session.query.return_value.all.return_value = [artifact]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False

    with (
        patch("scripts.cleanup_artifacts.get_session", return_value=ctx),
        patch("scripts.cleanup_artifacts.settings.audio_storage_path", str(tmp_path)),
    ):
        result = cleanup_artifacts(apply=False, now=datetime.now(timezone.utc))

    assert result["artifacts_expired"] == 1
    assert artifact_file.exists()
    assert artifact.storage_uri == str(artifact_file)
    session.rollback.assert_called_once()


def test_cleanup_artifacts_apply_clears_payload_and_file(tmp_path):
    artifact_file = tmp_path / "audio.wav"
    artifact_file.write_bytes(b"audio")

    artifact = MagicMock()
    artifact.artifact_type = "uploaded_audio"
    artifact.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    artifact.storage_uri = str(artifact_file)
    artifact.payload = {"raw": "data"}
    artifact.artifact_metadata = {}

    session = MagicMock()
    session.query.return_value.all.return_value = [artifact]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False

    with (
        patch("scripts.cleanup_artifacts.get_session", return_value=ctx),
        patch("scripts.cleanup_artifacts.settings.audio_storage_path", str(tmp_path)),
    ):
        result = cleanup_artifacts(apply=True, now=datetime.now(timezone.utc))

    assert result["files_deleted"] == 1
    assert not artifact_file.exists()
    assert artifact.storage_uri is None
    assert artifact.payload is None
    assert "retention_applied_at" in artifact.artifact_metadata


def test_cleanup_artifacts_refuses_paths_outside_storage(tmp_path):
    artifact_file = tmp_path / "outside.wav"
    artifact_file.write_bytes(b"audio")

    artifact = MagicMock()
    artifact.artifact_type = "uploaded_audio"
    artifact.created_at = datetime.now(timezone.utc) - timedelta(days=90)
    artifact.storage_uri = str(artifact_file)
    artifact.payload = {"raw": "data"}
    artifact.artifact_metadata = {}

    session = MagicMock()
    session.query.return_value.all.return_value = [artifact]
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value = False

    with (
        patch("scripts.cleanup_artifacts.get_session", return_value=ctx),
        patch("scripts.cleanup_artifacts.settings.audio_storage_path", str(tmp_path / "storage")),
    ):
        result = cleanup_artifacts(apply=True, now=datetime.now(timezone.utc))

    assert result["files_deleted"] == 0
    assert artifact_file.exists()
    assert artifact.storage_uri is None
    assert artifact.payload is None
