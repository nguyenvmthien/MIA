"""
Export human-corrected meeting data from PostgreSQL → JSONL for fine-tuning.

Produces instruction/input/output format compatible with train/finetune.py.

Usage:
    PYTHONPATH=src python data_pipeline/export_for_finetuning.py \
        --out data/training/finetuning.jsonl \
        --min-corrections 1

The output format per line:
    {
        "instruction": "<system prompt>",
        "input": "<transcript text>",
        "output": "<json array of corrected tasks>"
    }
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SYSTEM_INSTRUCTION = (
    "You are an AI assistant that extracts action items from meeting transcripts. "
    "Given the meeting transcript below, extract all action items as a JSON array. "
    "Each item must have: description, assignee (null if unknown), "
    "due_date (YYYY-MM-DD or null), priority (high/medium/low)."
)


def export(out_path: str, min_corrections: int = 1) -> int:
    from meeting_agent.db.engine import get_session
    from meeting_agent.db.models import FeedbackCorrection, Meeting, Task

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    written = 0

    with get_session() as session:
        meeting_ids = [
            row[0]
            for row in session.query(FeedbackCorrection.meeting_id).distinct().all()
        ]

        with open(out_path, "w") as f:
            for mid in meeting_ids:
                meeting = session.get(Meeting, mid)
                if meeting is None or meeting.status not in ("completed", "done"):
                    continue

                corrections = (
                    session.query(FeedbackCorrection).filter_by(meeting_id=mid).all()
                )
                if len(corrections) < min_corrections:
                    continue

                tasks = (
                    session.query(Task)
                    .filter_by(meeting_id=mid)
                    .filter(Task.bucket == "action")
                    .filter(Task.status != "dismissed")
                    .all()
                )

                ground_truth = [
                    {
                        "description": t.description,
                        "assignee": t.assignee,
                        "due_date": t.due_date.isoformat() if t.due_date else None,
                        "priority": t.priority,
                    }
                    for t in tasks
                ]

                # Prefer raw transcript turns; fall back to summary text
                turns = meeting.transcript_turns or []
                if turns:
                    transcript_text = "\n".join(
                        f"[{t.get('speaker_name', t.get('speaker_id', 'Speaker'))}]: {t.get('text', '')}"
                        for t in turns
                    )
                else:
                    transcript_text = meeting.summary_text or ""

                if not transcript_text or not ground_truth:
                    log.warning("Skipping meeting %s — no transcript or tasks", mid)
                    continue

                row = {
                    "instruction": SYSTEM_INSTRUCTION,
                    "input": transcript_text,
                    "output": json.dumps(ground_truth, ensure_ascii=False),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                log.info("Exported meeting %s (%d tasks, %d corrections)", mid, len(tasks), len(corrections))

    log.info("Done — %d examples written to %s", written, out_path)
    return written


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="data/training/finetuning.jsonl")
    p.add_argument("--min-corrections", type=int, default=1,
                   help="Minimum number of human corrections for a meeting to be included")
    args = p.parse_args()
    export(args.out, args.min_corrections)
