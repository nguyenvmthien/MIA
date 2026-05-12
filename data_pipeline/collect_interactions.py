"""
Collect user interaction data from the database and export as RLHF-ready JSONL.

Each record is either:
  - SFT (supervised fine-tuning): transcript → corrected tasks (after human review)
  - RLHF (preference): chosen (corrected) vs rejected (original model output) pairs

Usage:
    PYTHONPATH=src python data_pipeline/collect_interactions.py \
        --out data/training/interactions_$(date +%Y%m%d).jsonl \
        --format sft \
        --min-corrections 1

    # RLHF preference pairs
    PYTHONPATH=src python data_pipeline/collect_interactions.py \
        --out data/training/rlhf_$(date +%Y%m%d).jsonl \
        --format rlhf
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)


def _build_sft_record(meeting: dict, corrections: list[dict]) -> dict | None:
    """Build a supervised fine-tuning record from a meeting + its corrections."""
    turns = meeting.get("transcript_turns") or []
    if not turns:
        return None

    # Build ground-truth task list: start from action_items, apply corrections
    tasks = {t["task_id"]: dict(t) for t in meeting.get("action_items", [])}

    for c in corrections:
        tid = c.get("task_id")
        if not tid:
            continue
        if c.get("is_false_positive"):
            tasks.pop(tid, None)
            continue
        if tid not in tasks:
            if c.get("is_missing"):
                tasks[tid] = {
                    "task_id": tid,
                    "description": c.get("corrected_description", ""),
                    "assignee": c.get("corrected_assignee"),
                    "due_date": c.get("corrected_due_date"),
                }
            continue
        t = tasks[tid]
        if c.get("corrected_description"):
            t["description"] = c["corrected_description"]
        if c.get("corrected_assignee") is not None:
            t["assignee"] = c["corrected_assignee"] or None
        if c.get("corrected_due_date"):
            t["due_date"] = str(c["corrected_due_date"])

    transcript_text = "\n".join(
        f"[{turn.get('speaker_name', turn.get('speaker_id', 'SPEAKER'))}] {turn.get('text', '')}"
        for turn in turns
    )

    return {
        "format": "sft",
        "meeting_id": meeting["meeting_id"],
        "model_version": meeting.get("model_version"),
        "created_at": meeting.get("processed_at"),
        "instruction": (
            "Extract all action items from the meeting transcript. "
            "Return a JSON array of objects with fields: "
            "task_id, description, assignee (person name or null), due_date (ISO date or null)."
        ),
        "input": transcript_text,
        "output": json.dumps(list(tasks.values()), ensure_ascii=False),
        "n_corrections": len(corrections),
        "participants": meeting.get("participants", []),
    }


def _build_rlhf_records(meeting: dict, corrections: list[dict]) -> list[dict]:
    """Build RLHF chosen/rejected pairs for each corrected task."""
    records = []
    turns = meeting.get("transcript_turns") or []
    if not turns:
        return records

    transcript_text = "\n".join(
        f"[{turn.get('speaker_name', turn.get('speaker_id', 'SPEAKER'))}] {turn.get('text', '')}"
        for turn in turns
    )

    original_tasks = {t["task_id"]: t for t in meeting.get("action_items", [])}

    for c in corrections:
        tid = c.get("task_id")
        if not tid or c.get("is_missing"):
            continue

        orig = original_tasks.get(tid, {})

        if c.get("is_false_positive"):
            # Rejected: model hallucinated a task that doesn't exist
            records.append({
                "format": "rlhf",
                "type": "false_positive",
                "meeting_id": meeting["meeting_id"],
                "model_version": meeting.get("model_version"),
                "prompt": transcript_text,
                "chosen": "[]",
                "rejected": json.dumps([orig], ensure_ascii=False),
            })
            continue

        # Build corrected version
        corrected = dict(orig)
        if c.get("corrected_description"):
            corrected["description"] = c["corrected_description"]
        if c.get("corrected_assignee") is not None:
            corrected["assignee"] = c["corrected_assignee"] or None
        if c.get("corrected_due_date"):
            corrected["due_date"] = str(c["corrected_due_date"])

        if corrected != orig:
            records.append({
                "format": "rlhf",
                "type": "correction",
                "meeting_id": meeting["meeting_id"],
                "model_version": meeting.get("model_version"),
                "prompt": transcript_text,
                "chosen": json.dumps([corrected], ensure_ascii=False),
                "rejected": json.dumps([orig], ensure_ascii=False),
            })

    return records


def collect(
    out_path: str,
    fmt: str = "sft",
    min_corrections: int = 1,
    model_version: str | None = None,
    limit: int = 10000,
) -> int:
    """Query DB and write JSONL. Returns number of records written."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    from sqlalchemy import func

    from meeting_agent.db.engine import get_session
    from meeting_agent.db.models import FeedbackCorrection, Meeting, Task

    written = 0
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with get_session() as session:
        # Find meetings that have at least min_corrections human corrections
        eligible_ids = (
            session.query(FeedbackCorrection.meeting_id)
            .group_by(FeedbackCorrection.meeting_id)
            .having(func.count(FeedbackCorrection.id) >= min_corrections)
            .limit(limit)
            .all()
        )
        eligible_ids = [row[0] for row in eligible_ids]

        if not eligible_ids:
            log.warning("No meetings with >= %d corrections found", min_corrections)
            return 0

        log.info("Found %d eligible meetings", len(eligible_ids))

        with open(out, "w", encoding="utf-8") as f:
            for mid in eligible_ids:
                meeting = session.get(Meeting, mid)
                if meeting is None:
                    continue
                if model_version and meeting.model_version != model_version:
                    continue

                turns = meeting.transcript_turns or []
                if not turns:
                    log.debug("Meeting %s has no transcript_turns, skipping", mid)
                    continue

                # Load corrections
                corrections_raw = (
                    session.query(FeedbackCorrection)
                    .filter_by(meeting_id=mid)
                    .all()
                )
                corrections = [
                    {
                        "task_id": c.task_id,
                        "is_false_positive": c.is_false_positive,
                        "is_missing": c.is_missing,
                        "original_description": c.original_description,
                        "corrected_description": c.corrected_description,
                        "original_assignee": c.original_assignee,
                        "corrected_assignee": c.corrected_assignee,
                        "original_due_date": c.original_due_date.isoformat() if c.original_due_date else None,
                        "corrected_due_date": c.corrected_due_date.isoformat() if c.corrected_due_date else None,
                    }
                    for c in corrections_raw
                ]

                action_tasks = (
                    session.query(Task)
                    .filter_by(meeting_id=mid, bucket="action")
                    .all()
                )
                meeting_dict = {
                    "meeting_id": mid,
                    "model_version": meeting.model_version,
                    "processed_at": meeting.processed_at.isoformat() if meeting.processed_at else None,
                    "transcript_turns": turns,
                    "participants": meeting.participants or [],
                    "action_items": [
                        {
                            "task_id": t.task_id,
                            "description": t.description,
                            "assignee": t.assignee,
                            "due_date": t.due_date.isoformat() if t.due_date else None,
                        }
                        for t in action_tasks
                    ],
                }

                if fmt == "sft":
                    record = _build_sft_record(meeting_dict, corrections)
                    if record:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        written += 1
                else:
                    records = _build_rlhf_records(meeting_dict, corrections)
                    for record in records:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
                        written += len(records)
                        break  # already counted all at once

    log.info("Wrote %d records to %s", written, out)
    return written


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Export DB interaction data for AI training")
    parser.add_argument("--out", default=f"data/training/interactions_{datetime.now().strftime('%Y%m%d')}.jsonl")
    parser.add_argument("--format", choices=["sft", "rlhf"], default="sft", dest="fmt")
    parser.add_argument("--min-corrections", type=int, default=1)
    parser.add_argument("--model-version", default=None, help="Filter by model version (e.g. qwen2.5:3b)")
    parser.add_argument("--limit", type=int, default=10000)
    args = parser.parse_args()

    n = collect(
        out_path=args.out,
        fmt=args.fmt,
        min_corrections=args.min_corrections,
        model_version=args.model_version,
        limit=args.limit,
    )
    print(f"Exported {n} {args.fmt.upper()} records → {args.out}")


if __name__ == "__main__":
    main()
