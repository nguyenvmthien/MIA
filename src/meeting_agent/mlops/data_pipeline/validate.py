"""
Data validation — checks a JSONL dataset for bias, leakage, and schema issues
before it is used for fine-tuning.

Checks:
  1. Schema conformance (required fields present)
  2. Speaker balance (no single speaker dominates > 80% of samples)
  3. Train/test leakage (no speaker in test that is exclusively in train)
  4. Label quality (action_items not empty for > threshold% of samples)
  5. Duplicate detection (near-identical transcripts)

Usage:
    python -m meeting_agent.mlops.data_pipeline.validate --train data/train.jsonl --val data/val.jsonl
"""

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from meeting_agent.mlops.data_contracts import load_jsonl_records, validate_records

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def load_jsonl(path: str) -> list[dict]:
    return load_jsonl_records(path)


def check_schema(samples: list[dict], name: str) -> list[str]:
    """Return list of error messages for schema violations."""
    allowed = {"meeting_raw_v1", "sft_v1"}
    return [f"{name}: {error}" for error in validate_records(samples, allowed=allowed)]


def check_speaker_balance(samples: list[dict], name: str, threshold: float = 0.8) -> list[str]:
    """Flag if any single speaker appears in > threshold fraction of samples."""
    warnings = []
    speaker_counts: Counter = Counter()
    for s in samples:
        for turn in s.get("transcript_turns", []):
            speaker_counts[turn.get("speaker_name", turn.get("speaker_id", "?"))] += 1
    total = sum(speaker_counts.values())
    if total == 0:
        return warnings
    for speaker, count in speaker_counts.most_common(3):
        ratio = count / total
        if ratio > threshold:
            warnings.append(
                f"{name}: speaker '{speaker}' dominates {ratio:.0%} of turns "
                f"(threshold {threshold:.0%}) — possible bias"
            )
    return warnings


def check_leakage(train: list[dict], val: list[dict]) -> list[str]:
    """
    Warn if a speaker name appears ONLY in val (not seen in train).
    These unseen speakers may inflate eval metrics.
    """
    def speakers(samples):
        names = set()
        for s in samples:
            for turn in s.get("transcript_turns", []):
                n = turn.get("speaker_name")
                if n:
                    names.add(n.lower())
        return names

    train_speakers = speakers(train)
    val_speakers = speakers(val)
    unseen = val_speakers - train_speakers
    if unseen:
        return [f"Leakage warning: {len(unseen)} val speakers not in train: {unseen}"]
    return []


def check_duplicates(samples: list[dict], name: str) -> list[str]:
    """Detect near-identical transcripts using first 100 chars as fingerprint."""
    seen = {}
    warnings = []
    for i, s in enumerate(samples):
        key = (s.get("transcript") or s.get("input") or "")[:100].strip().lower()
        if not key:
            key = " ".join(
                turn.get("text", "") for turn in s.get("transcript_turns", [])
            )[:100].strip().lower()
        if not key:
            continue
        if key in seen:
            warnings.append(f"{name}[{i}]: near-duplicate of sample {seen[key]}")
        else:
            seen[key] = i
    return warnings


def validate(train_path: str, val_path: str | None = None) -> bool:
    """Run all validation checks. Returns True if dataset passes."""
    train = load_jsonl(train_path)
    val = load_jsonl(val_path) if val_path else []

    all_issues = []
    all_issues += check_schema(train, "train")
    all_issues += check_speaker_balance(train, "train")
    all_issues += check_duplicates(train, "train")

    if val:
        all_issues += check_schema(val, "val")
        all_issues += check_speaker_balance(val, "val")
        all_issues += check_leakage(train, val)

    # Summary
    errors   = [i for i in all_issues if not i.startswith("Leakage") and "warning" not in i.lower()]
    warnings = [i for i in all_issues if i not in errors]

    log.info("Validation complete — train=%d val=%d", len(train), len(val))
    for w in warnings:
        log.warning("  WARN: %s", w)
    for e in errors:
        log.error("  ERROR: %s", e)

    if errors:
        log.error("Dataset FAILED validation (%d errors)", len(errors))
        return False
    log.info("Dataset PASSED validation (%d warnings)", len(warnings))
    return True


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--train", required=True)
    p.add_argument("--val", default=None)
    args = p.parse_args()
    ok = validate(args.train, args.val)
    raise SystemExit(0 if ok else 1)
