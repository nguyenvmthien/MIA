"""Smoke test for training dataset compatibility across raw and SFT records."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

def main() -> int:
    from meeting_agent.mlops.data_contracts import load_jsonl_records, validate_records
    from meeting_agent.mlops.dataset import _format_example

    rows = [
        {
            "schema_version": "sft_v1",
            "instruction": "Extract action items.",
            "input": "Alice: Bob, send the report.",
            "output": "[]",
            "source_meeting_id": "sft-smoke",
        },
        {
            "schema_version": "meeting_raw_v1",
            "meeting_id": "raw-smoke",
            "meeting_date": "2026-05-13",
            "participants": ["Alice", "Bob"],
            "roster": {"workers": [{"worker_id": "w1", "name": "Bob"}]},
            "transcript_turns": [
                {
                    "turn_id": "t1",
                    "speaker_id": "SPEAKER_00",
                    "speaker_name": "Alice",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "Bob, please send the report by Friday.",
                }
            ],
            "action_items": [{"description": "Send the report", "assignee": "Bob"}],
        },
    ]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dataset.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        loaded = load_jsonl_records(path)

    errors = validate_records(loaded, allowed={"sft_v1", "meeting_raw_v1"})
    if errors:
        print("\n".join(errors))
        return 1
    formatted = [_format_example(row) for row in loaded]
    assert len(formatted) == 2
    assert formatted[0]["output"] == "[]"
    assert "Send the report" in formatted[1]["output"]
    print("Dataset compatibility smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
