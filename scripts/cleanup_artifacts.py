"""Apply retention policy to meeting artifacts and their local files."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from meeting_agent.config import settings
from meeting_agent.db.engine import get_session
from meeting_agent.db.models import MeetingArtifact

RAW_AUDIO_TYPES = {"uploaded_audio", "raw_audio_wav", "clean_audio"}
PII_TYPES = {"asr_raw", "diarization_raw", "llm_summary_raw", "llm_tasks_raw"}


def _allowed_roots() -> tuple[Path, ...]:
    return (
        Path(settings.audio_storage_path).resolve(),
        Path(settings.transcript_storage_path).resolve(),
    )


def _retention_days(artifact_type: str) -> int:
    if artifact_type in RAW_AUDIO_TYPES:
        return settings.raw_audio_retention_days
    if artifact_type in PII_TYPES:
        return settings.pii_artifact_retention_days
    return settings.artifact_retention_days


def _remove_local_file(uri: str | None) -> bool:
    if not uri:
        return False
    path = Path(uri).resolve()
    if not any(path.is_relative_to(root) for root in _allowed_roots()):
        return False
    if not path.exists() or not path.is_file():
        return False
    path.unlink()
    return True


def cleanup_artifacts(*, apply: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    scanned = 0
    expired = 0
    files_deleted = 0

    with get_session() as session:
        artifacts = session.query(MeetingArtifact).all()
        for artifact in artifacts:
            scanned += 1
            created_at = artifact.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            cutoff = now - timedelta(days=_retention_days(artifact.artifact_type))
            if created_at > cutoff:
                continue
            expired += 1
            if not apply:
                continue
            if _remove_local_file(artifact.storage_uri):
                files_deleted += 1
            artifact.storage_uri = None
            artifact.payload = None
            artifact.artifact_metadata = {
                **(artifact.artifact_metadata or {}),
                "retention_applied_at": now.isoformat(),
                "retention_policy_days": _retention_days(artifact.artifact_type),
            }
        if not apply:
            session.rollback()

    return {
        "apply": apply,
        "artifacts_scanned": scanned,
        "artifacts_expired": expired,
        "files_deleted": files_deleted,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete local files and clear payloads",
    )
    args = parser.parse_args()
    print(cleanup_artifacts(apply=args.apply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
