"""Stage 1 — Ingest: validate and store the uploaded audio file."""

import shutil
import time
from pathlib import Path

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import STAGE_LATENCY

SUPPORTED_FORMATS = {".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".flac", ".webm"}
MAX_BYTES = settings.max_audio_duration_hours * 3600 * 320_000  # rough upper bound at 320kbps


class IngestError(Exception):
    pass


def ingest_audio(source_path: str | Path, meeting_id: str) -> Path:
    """
    Validate and copy the audio file into managed storage.

    Returns the path to the stored file.
    Raises IngestError on invalid input.
    """
    t0 = time.monotonic()
    source = Path(source_path)

    if not source.exists():
        raise IngestError(f"File not found: {source}")

    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_FORMATS:
        raise IngestError(
            f"Unsupported format '{suffix}'. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )

    file_size = source.stat().st_size
    if file_size > MAX_BYTES:
        raise IngestError(
            f"File too large ({file_size / 1e6:.1f} MB). "
            f"Max allowed for {settings.max_audio_duration_hours}h audio."
        )

    dest_dir = Path(settings.audio_storage_path) / meeting_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"audio{suffix}"
    shutil.copy2(source, dest)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    STAGE_LATENCY.labels(stage="ingest").observe(elapsed_ms / 1000)
    return dest
