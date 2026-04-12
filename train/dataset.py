"""
Dataset preparation for fine-tuning.

Loads JSONL files of (transcript, action_items) pairs and formats them
into the instruction-following format expected by Qwen2.5 / Unsloth.

Data format (each line of input JSONL):
{
  "transcript": "[Alice]: Bob, can you send the report by Friday?",
  "roster": "- Bob Kim [Dev]",
  "meeting_date": "2026-04-12",
  "participants": "Alice Chen, Bob Kim",
  "action_items": [
    {"description": "Send report", "assignee": "Bob Kim", "due_date": "2026-04-17",
     "priority": "high", "notes": null}
  ]
}
"""

from __future__ import annotations

import json
from pathlib import Path

from meeting_agent.prompts.templates import (
    EXTRACT_TASKS_SYSTEM,
    EXTRACT_TASKS_USER,
)


def _format_example(row: dict) -> dict:
    """Convert a raw data row into an (instruction, output) pair."""
    # Compute next Friday relative to meeting_date for the system prompt
    from datetime import date, timedelta
    try:
        d = date.fromisoformat(row["meeting_date"])
    except Exception:
        d = date.today()
    days_ahead = 4 - d.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    friday = (d + timedelta(days=days_ahead)).isoformat()

    system = EXTRACT_TASKS_SYSTEM.format(roster=row.get("roster", ""), friday=friday)
    user = EXTRACT_TASKS_USER.format(
        meeting_date=row["meeting_date"],
        participants=row.get("participants", ""),
        transcript=row["transcript"],
    )
    assistant = json.dumps(row["action_items"], ensure_ascii=False)

    return {
        "instruction": system,
        "input": user,
        "output": assistant,
    }


def load_jsonl(path: str | Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_dataset(data_paths: list[str | Path]):  # -> datasets.Dataset
    """
    Load one or more JSONL files and return a HuggingFace Dataset
    in instruction-tuning format.
    """
    from datasets import Dataset  # type: ignore

    all_rows = []
    for path in data_paths:
        all_rows.extend(load_jsonl(path))

    formatted = [_format_example(row) for row in all_rows]
    return Dataset.from_list(formatted)


def train_val_split(dataset, val_ratio: float = 0.15):
    split = dataset.train_test_split(test_size=val_ratio, seed=42)
    return split["train"], split["test"]
