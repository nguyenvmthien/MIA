"""
Data collection helpers — ingest audio/transcript files into the training dataset.

Supports:
  - Directory scan for audio files → transcribe via pipeline and save as JSONL
  - Manual transcript import (pre-existing .txt/.json files)

Usage:
    python -m meeting_agent.mlops.data_pipeline.collect --audio-dir data/raw/audio --out data/training/collected.jsonl
"""

import argparse
import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

AUDIO_EXTS = {".mp3", ".wav", ".mp4", ".m4a", ".flac", ".ogg"}


def collect_from_audio_dir(
    audio_dir: str,
    roster_path: str | None,
    out_path: str,
) -> int:
    """
    Transcribe all audio files in a directory using the pipeline
    and save resulting MeetingSummary objects as JSONL training data.
    """
    from meeting_agent.pipeline.run import run_pipeline
    from meeting_agent.schemas.worker import WorkerRoster

    roster = WorkerRoster()
    if roster_path and Path(roster_path).exists():
        with open(roster_path) as f:
            roster = WorkerRoster.model_validate(json.load(f))

    audio_dir_path = Path(audio_dir)
    audio_files = [f for f in audio_dir_path.iterdir() if f.suffix.lower() in AUDIO_EXTS]
    log.info("Found %d audio files in %s", len(audio_files), audio_dir)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    saved = 0

    with open(out_path, "a") as f:
        for audio_file in audio_files:
            meeting_id = str(uuid.uuid4())
            log.info("Processing %s ...", audio_file.name)
            try:
                summary = run_pipeline(audio_file, roster, meeting_id=meeting_id)
                if summary.job_status.value == "completed":
                    row = summary.model_dump(mode="json")
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    saved += 1
            except Exception as exc:
                log.warning("Failed to process %s: %s", audio_file.name, exc)

    log.info("Collected %d samples → %s", saved, out_path)
    return saved


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--audio-dir", required=True)
    p.add_argument("--roster", default=None)
    p.add_argument("--out", default="data/training/collected.jsonl")
    args = p.parse_args()
    collect_from_audio_dir(args.audio_dir, args.roster, args.out)
