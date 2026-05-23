"""
Evaluation harness — measures task extraction quality on a labeled gold set.

Metrics:
  - Precision, Recall, F1 (BM25-based description matching)
  - Assignee accuracy
  - Hallucination rate (predicted tasks with no evidence in transcript)
  - Schema failure rate
  - Per-meeting-type breakdown

Modes:
  zero_shot   — no few-shot examples in prompt
  few_shot    — 3 few-shot examples injected (default, current system)
  finetuned   — use OLLAMA_LLM_MODEL override (fine-tuned model)

Usage:
    # Single mode
    python -m meeting_agent.mlops.evaluate --gold data/eval/gold_v1.jsonl

    # Compare all modes
    python -m meeting_agent.mlops.evaluate --gold data/eval/gold_v1.jsonl --compare \
        --out data/eval/results/compare_20260429.json

    # Zero-shot only
    python -m meeting_agent.mlops.evaluate --gold data/eval/gold_smoke.jsonl \
        --mode zero_shot --out data/eval/results/zero_shot.json
"""

import argparse
import json
import logging
import math
import re
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ── BM25 text matching ────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class _BM25:
    """Minimal BM25 scorer for description matching. No external deps."""

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs = [_tokenize(d) for d in corpus]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        # IDF
        n = len(self.docs)
        df: dict[str, int] = defaultdict(int)
        for doc in self.docs:
            for term in set(doc):
                df[term] += 1
        self.idf = {term: math.log((n - freq + 0.5) / (freq + 0.5) + 1)
                    for term, freq in df.items()}

    def score(self, query: str, doc_idx: int) -> float:
        q_terms = _tokenize(query)
        doc = self.docs[doc_idx]
        dl = len(doc)
        tf_map: dict[str, int] = defaultdict(int)
        for t in doc:
            tf_map[t] += 1
        score = 0.0
        for term in q_terms:
            tf = tf_map.get(term, 0)
            idf = self.idf.get(term, 0)
            score += idf * (tf * (self.k1 + 1)) / (
                tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            )
        return score


def _task_match_bm25(
    pred_desc: str,
    gold_descs: list[str],
    threshold: float = 2.0,
) -> tuple[bool, int]:
    """
    Return (matched, best_gold_idx) using BM25.
    threshold=2.0 means BM25 score must be > 2.0 to count as a match.
    Falls back to simple Jaccard if BM25 scores all zero.
    """
    if not gold_descs:
        return False, -1

    bm25 = _BM25(gold_descs)
    scores = [bm25.score(pred_desc, i) for i in range(len(gold_descs))]
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_idx]

    if best_score > threshold:
        return True, best_idx

    # Fallback: Jaccard overlap
    pred_words = set(_tokenize(pred_desc))
    for i, gold_desc in enumerate(gold_descs):
        gold_words = set(_tokenize(gold_desc))
        if not pred_words or not gold_words:
            continue
        jaccard = len(pred_words & gold_words) / len(pred_words | gold_words)
        if jaccard >= 0.5:
            return True, i

    return False, -1


# ── Hallucination detection ───────────────────────────────────────────────────

def _is_hallucinated(task: dict, transcript_turns: list[dict]) -> bool:
    """
    A predicted task is hallucinated if its description has no evidence
    (overlapping content words) in any transcript turn.
    """
    desc_words = set(_tokenize(task.get("description", "")))
    stopwords = {"the", "a", "an", "to", "of", "and", "or", "in", "on",
                 "at", "for", "by", "with", "it", "is", "was", "be", "will"}
    content_words = desc_words - stopwords
    if not content_words:
        return False  # can't tell

    full_text = " ".join(t.get("text", "") for t in transcript_turns).lower()
    full_tokens = set(_tokenize(full_text))
    overlap = content_words & full_tokens
    return len(overlap) / len(content_words) < 0.3  # <30% overlap = hallucination


# ── Per-sample evaluation ─────────────────────────────────────────────────────

def evaluate_sample(
    predicted: list[dict],
    gold: list[dict],
    transcript_turns: list[dict],
) -> dict:
    matched_gold: set[int] = set()
    gold_descs = [g.get("description", "") for g in gold]
    tp = fp = 0
    assignee_correct = 0
    hallucinations = 0

    for pred in predicted:
        matched, gold_idx = _task_match_bm25(pred.get("description", ""), gold_descs)
        if matched and gold_idx not in matched_gold:
            tp += 1
            matched_gold.add(gold_idx)
            # Assignee accuracy
            pred_a = (pred.get("assignee") or "").lower()
            gold_a = (gold[gold_idx].get("assignee") or "").lower()
            if pred_a and gold_a and pred_a == gold_a:
                assignee_correct += 1
        else:
            fp += 1
            if _is_hallucinated(pred, transcript_turns):
                hallucinations += 1

    fn = len(gold) - len(matched_gold)
    precision = tp / len(predicted) if predicted else 1.0
    recall = tp / len(gold) if gold else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    assignee_acc = assignee_correct / tp if tp > 0 else None

    return {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "assignee_accuracy": round(assignee_acc, 4) if assignee_acc is not None else None,
        "hallucinations": hallucinations,
        "n_predicted": len(predicted),
        "n_gold": len(gold),
    }


# ── Core evaluation runner ────────────────────────────────────────────────────

def _aggregate_results(
    *,
    mode: str,
    model: str,
    gold_path: str,
    all_metrics: list[dict],
    schema_failures: int,
    total_hallucinations: int,
    latencies: list[int],
) -> dict:
    n = len(all_metrics)

    def avg(key: str) -> float:
        return sum(m[key] for m in all_metrics) / n if n else 0

    assignee_accs = [
        m["assignee_accuracy"] for m in all_metrics if m["assignee_accuracy"] is not None
    ]

    return {
        "mode": mode,
        "model": model,
        "gold_file": gold_path,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "samples": n,
        "avg_precision": round(avg("precision"), 4),
        "avg_recall": round(avg("recall"), 4),
        "avg_f1": round(avg("f1"), 4),
        "assignee_accuracy": (
            round(sum(assignee_accs) / len(assignee_accs), 4) if assignee_accs else None
        ),
        "hallucination_rate": round(
            total_hallucinations / max(sum(m["n_predicted"] for m in all_metrics), 1),
            4,
        ),
        "schema_failure_rate": round(schema_failures / n, 4) if n else 0,
        "avg_latency_ms": round(sum(latencies) / max(n, 1)),
        "p95_latency_ms": sorted(latencies)[int(n * 0.95)] if latencies else 0,
        "ci_pass": avg("precision") >= 0.70,
        "per_sample": all_metrics,
    }


def run_evaluation(
    gold_path: str,
    model: str,
    mode: str = "few_shot",
    limit: int | None = None,
    checkpoint_path: str | None = None,
) -> dict:
    from meeting_agent.pipeline.orchestrator import extract_action_items
    from meeting_agent.schemas.transcript import TranscriptTurn
    from meeting_agent.schemas.worker import WorkerRoster

    gold_samples = [json.loads(l) for l in Path(gold_path).read_text().splitlines() if l.strip()]
    if limit is not None:
        gold_samples = gold_samples[:limit]

    all_metrics = []
    schema_failures = 0
    total_hallucinations = 0
    latencies = []

    for i, sample in enumerate(gold_samples):
        turns = [
            TranscriptTurn(
                turn_id=str(uuid.uuid4()),
                speaker_id=seg.get("speaker_id", "SPEAKER_00"),
                speaker_name=seg.get("speaker_name"),
                start_ms=seg.get("start_ms", 0),
                end_ms=seg.get("end_ms", 1000),
                text=seg.get("text", ""),
            )
            for seg in sample.get("transcript_turns", [])
        ]
        roster = WorkerRoster.model_validate(sample.get("roster", {"workers": []}))
        gold_tasks = sample.get("action_items", [])

        t0 = time.monotonic()
        try:
            predicted_tasks, _ = extract_action_items(
                turns, roster,
                meeting_date=sample.get("meeting_date", "2026-01-01"),
                meeting_id=f"eval_{i}",
                model=model,
                prompt_mode=mode,
            )
            predicted = [t.model_dump(mode="json") for t in predicted_tasks]
        except Exception as exc:
            log.warning("Sample %d extraction failed: %s", i, exc)
            schema_failures += 1
            predicted = []

        latency_ms = int((time.monotonic() - t0) * 1000)
        latencies.append(latency_ms)

        m = evaluate_sample(predicted, gold_tasks, sample.get("transcript_turns", []))
        m["sample_idx"] = i
        m["meeting_date"] = sample.get("meeting_date", "")
        m["latency_ms"] = latency_ms
        all_metrics.append(m)
        total_hallucinations += m["hallucinations"]
        if checkpoint_path:
            partial = _aggregate_results(
                mode=mode,
                model=model,
                gold_path=gold_path,
                all_metrics=all_metrics,
                schema_failures=schema_failures,
                total_hallucinations=total_hallucinations,
                latencies=latencies,
            )
            partial["partial"] = True
            partial["remaining_samples"] = len(gold_samples) - len(all_metrics)
            checkpoint = Path(checkpoint_path)
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps(partial, indent=2, ensure_ascii=False))

        log.info(
            "Sample %02d [%dms]: P=%.2f R=%.2f F1=%.2f | pred=%d gold=%d hall=%d",
            i, latency_ms, m["precision"], m["recall"], m["f1"],
            len(predicted), len(gold_tasks), m["hallucinations"],
        )

    results = _aggregate_results(
        mode=mode,
        model=model,
        gold_path=gold_path,
        all_metrics=all_metrics,
        schema_failures=schema_failures,
        total_hallucinations=total_hallucinations,
        latencies=latencies,
    )

    _print_results(results)
    return results


def _print_results(r: dict) -> None:
    log.info("=" * 60)
    log.info("EVALUATION RESULTS  mode=%s  model=%s", r["mode"], r["model"])
    log.info("  Samples       : %d", r["samples"])
    log.info("  Precision     : %.4f  (CI threshold ≥ 0.70 → %s)",
             r["avg_precision"], "PASS ✓" if r["ci_pass"] else "FAIL ✗")
    log.info("  Recall        : %.4f", r["avg_recall"])
    log.info("  F1            : %.4f", r["avg_f1"])
    log.info("  Assignee Acc  : %s", f"{r['assignee_accuracy']:.4f}" if r["assignee_accuracy"] else "N/A")
    log.info("  Halluc. Rate  : %.4f", r["hallucination_rate"])
    log.info("  Schema Fail   : %.4f", r["schema_failure_rate"])
    log.info("  Avg Latency   : %d ms", r["avg_latency_ms"])
    log.info("  P95 Latency   : %d ms", r["p95_latency_ms"])
    log.info("=" * 60)


# ── Compare mode ──────────────────────────────────────────────────────────────

def run_compare(gold_path: str, model: str, out_path: str | None) -> dict:
    """Run all three modes and produce a comparison report."""
    results = {}
    for mode in ["zero_shot", "few_shot", "finetuned"]:
        log.info("\n%s Running mode: %s %s", "="*20, mode, "="*20)
        try:
            r = run_evaluation(gold_path, model, mode)
            results[mode] = r
        except Exception as e:
            log.error("Mode %s failed: %s", mode, e)
            results[mode] = {"error": str(e)}

    comparison = {
        "compared_at": datetime.now(timezone.utc).isoformat(),
        "gold_file": gold_path,
        "model": model,
        "modes": results,
        "winner": max(
            (m for m in results if "avg_f1" in results[m]),
            key=lambda m: results[m].get("avg_f1", 0),
            default="few_shot",
        ),
    }

    log.info("\n%s COMPARISON SUMMARY %s", "="*20, "="*20)
    for mode, r in results.items():
        if "avg_f1" in r:
            log.info("  %-12s  P=%.3f  R=%.3f  F1=%.3f  Hall=%.3f",
                     mode, r["avg_precision"], r["avg_recall"], r["avg_f1"], r["hallucination_rate"])
    log.info("  Winner: %s", comparison["winner"])

    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(comparison, indent=2, ensure_ascii=False))
        log.info("Comparison saved to %s", out_path)

    return comparison


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Evaluation harness for Meeting AI Agent")
    p.add_argument("--gold", required=True, help="Path to gold JSONL eval set")
    p.add_argument("--model", default="qwen2.5:3b", help="Ollama model name")
    p.add_argument("--mode", default="few_shot",
                   choices=["zero_shot", "few_shot", "finetuned"],
                   help="Prompt mode to evaluate")
    p.add_argument("--compare", action="store_true",
                   help="Compare zero_shot vs few_shot vs finetuned")
    p.add_argument("--out", default=None, help="Save results JSON to this path")
    p.add_argument("--limit", type=int, default=None, help="Evaluate only the first N samples")
    p.add_argument("--checkpoint", default=None, help="Write partial results after each sample")
    args = p.parse_args()

    if args.compare:
        run_compare(args.gold, args.model, args.out)
    else:
        results = run_evaluation(
            args.gold,
            args.model,
            args.mode,
            limit=args.limit,
            checkpoint_path=args.checkpoint,
        )
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
            log.info("Results saved to %s", args.out)
        if not results["ci_pass"]:
            sys.exit(1)
