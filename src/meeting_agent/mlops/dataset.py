"""Dataset preparation for fine-tuning."""

from __future__ import annotations

from pathlib import Path

from meeting_agent.mlops.data_contracts import load_jsonl_records, normalize_training_record


def _format_example(row: dict) -> dict:
    """Convert canonical SFT or raw meeting rows into an SFT example."""
    record = normalize_training_record(row)
    return record.model_dump(
        mode="json",
        include={"instruction", "input", "output", "source_meeting_id", "model_version"},
        exclude_none=True,
    )


def load_jsonl(path: str | Path) -> list[dict]:
    return load_jsonl_records(path)


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
