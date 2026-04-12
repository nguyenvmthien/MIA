"""
Data collection helpers — ingest audio/transcript files into the training dataset.

Supports:
  - Directory scan for audio files → transcribe via pipeline and save as JSONL
  - Manual transcript import (pre-existing .txt/.json files)
  - AMI corpus format import

Usage:
    python data_pipeline/collect.py --audio-dir data/raw/audio --out data/training/collected.jsonl
    python data_pipeline/collect.py --ami-dir data/raw/ami --out data/training/ami.jsonl
"""

import argparse
import json
import logging
import uuid
from pathlib import Path

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
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


def collect_from_ami(ami_dir: str, out_path: str) -> int:
    """
    Import meetings from the AMI Meeting Corpus (http://groups.inf.ed.ac.uk/ami/).
    Expects the standard AMI XML annotation + word-level transcript structure.
    This is a simplified importer — adapt paths to your local AMI download.
    """
    # AMI corpus has a complex XML structure; this is a placeholder that
    # reads the pre-processed words/*.words.xml and segments/*.segments.xml
    # For a full implementation, see: https://github.com/mcfloundinho/ami-tools
    log.warning(
        "AMI importer is a skeleton — integrate with ami-tools for full support. "
        "See: https://github.com/mcfloundinho/ami-tools"
    )
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd")

    audio_cmd = sub.add_parser("audio", help="Collect from audio directory")
    audio_cmd.add_argument("--audio-dir", required=True)
    audio_cmd.add_argument("--roster", default=None)
    audio_cmd.add_argument("--out", default="data/training/collected.jsonl")

    ami_cmd = sub.add_parser("ami", help="Import from AMI corpus")
    ami_cmd.add_argument("--ami-dir", required=True)
    ami_cmd.add_argument("--out", default="data/training/ami.jsonl")

    args = p.parse_args()
    if args.cmd == "audio":
        collect_from_audio_dir(args.audio_dir, args.roster, args.out)
    elif args.cmd == "ami":
        collect_from_ami(args.ami_dir, args.out)
    else:
        p.print_help()
