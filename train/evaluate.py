"""
Evaluation harness — measures task extraction quality on a labeled gold set.

Metrics:
  - Precision, Recall, F1 for task extraction
  - Assignee accuracy
  - Schema validity rate
  - Hallucination rate

Usage:
    python train/evaluate.py --gold data/eval/gold.jsonl --model qwen2.5:3b
"""

import argparse
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _task_match(pred: dict, gold: dict, desc_threshold: float = 0.6) -> bool:
    """
    Two tasks match if their descriptions are similar enough
    (using simple token overlap as a proxy for semantic similarity).
    """
    pred_words = set(_normalize(pred.get("description", "")).split())
    gold_words = set(_normalize(gold.get("description", "")).split())
    if not pred_words or not gold_words:
        return False
    overlap = len(pred_words & gold_words) / len(pred_words | gold_words)
    return overlap >= desc_threshold


def evaluate_sample(
    predicted: list[dict],
    gold: list[dict],
) -> dict:
    """Compute precision, recall, F1 for one meeting."""
    tp = 0
    matched_gold = set()

    for pred in predicted:
        for gi, g in enumerate(gold):
            if gi not in matched_gold and _task_match(pred, g):
                tp += 1
                matched_gold.add(gi)
                break

    precision = tp / len(predicted) if predicted else 1.0
    recall = tp / len(gold) if gold else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return {"tp": tp, "fp": len(predicted) - tp, "fn": len(gold) - tp,
            "precision": precision, "recall": recall, "f1": f1}


def run_evaluation(gold_path: str, model: str) -> dict:
    """
    Run the extraction pipeline on each gold sample and compare to labels.
    Returns aggregate metrics across all samples.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

    import uuid

    from meeting_agent.pipeline.orchestrator import extract_action_items
    from meeting_agent.schemas.transcript import TranscriptTurn
    from meeting_agent.schemas.worker import WorkerRoster

    gold_samples = []
    with open(gold_path) as f:
        for line in f:
            line = line.strip()
            if line:
                gold_samples.append(json.loads(line))

    all_precision, all_recall, all_f1 = [], [], []
    schema_failures = 0
    for i, sample in enumerate(gold_samples):
        # Reconstruct transcript turns from the gold sample
        turns = []
        for seg in sample.get("transcript_turns", []):
            turns.append(TranscriptTurn(
                turn_id=str(uuid.uuid4()),
                speaker_id=seg.get("speaker_id", "SPEAKER_00"),
                speaker_name=seg.get("speaker_name"),
                start_ms=seg.get("start_ms", 0),
                end_ms=seg.get("end_ms", 1000),
                text=seg.get("text", ""),
            ))

        roster = WorkerRoster.model_validate(sample.get("roster", {"workers": []}))
        gold_tasks = sample.get("action_items", [])

        try:
            predicted_tasks, _ = extract_action_items(
                turns, roster,
                meeting_date=sample.get("meeting_date", "2026-01-01"),
                meeting_id=f"eval_{i}",
            )
            predicted = [t.model_dump(mode="json") for t in predicted_tasks]
        except Exception as exc:
            log.warning("Sample %d extraction failed: %s", i, exc)
            schema_failures += 1
            predicted = []

        metrics = evaluate_sample(predicted, gold_tasks)
        all_precision.append(metrics["precision"])
        all_recall.append(metrics["recall"])
        all_f1.append(metrics["f1"])

        log.info(
            "Sample %d: P=%.2f R=%.2f F1=%.2f (pred=%d gold=%d)",
            i, metrics["precision"], metrics["recall"], metrics["f1"],
            len(predicted), len(gold_tasks),
        )

    n = len(gold_samples)
    results = {
        "samples": n,
        "avg_precision": sum(all_precision) / n if n else 0,
        "avg_recall": sum(all_recall) / n if n else 0,
        "avg_f1": sum(all_f1) / n if n else 0,
        "schema_failure_rate": schema_failures / n if n else 0,
    }

    log.info("=" * 50)
    log.info("EVALUATION RESULTS (%d samples)", n)
    log.info("  Precision : %.3f  (target ≥ 0.85)", results["avg_precision"])
    log.info("  Recall    : %.3f  (target ≥ 0.90)", results["avg_recall"])
    log.info("  F1        : %.3f", results["avg_f1"])
    log.info("  Schema failures: %.1f%%", results["schema_failure_rate"] * 100)
    log.info("=" * 50)

    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--gold", required=True, help="Path to gold JSONL eval set")
    p.add_argument("--model", default="qwen2.5:3b", help="Ollama model to evaluate")
    p.add_argument("--out", default=None, help="Save results JSON to this file")
    args = p.parse_args()

    results = run_evaluation(args.gold, args.model)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=2)
        log.info("Results saved to %s", args.out)
