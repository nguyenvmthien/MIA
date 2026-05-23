"""Run a baseline/candidate extraction benchmark.

This is intentionally separate from training. Use it before and after a Kaggle
fine-tune to decide whether a candidate is good enough to promote.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from meeting_agent.mlops.evaluate import run_evaluation


def _slug(value: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in value).strip("-")


def _promotion_decision(
    baseline: dict,
    candidate: dict | None,
    min_precision: float,
    max_f1_drop: float,
    max_hallucination_delta: float,
) -> dict:
    if candidate is None:
        return {
            "candidate_present": False,
            "promote": False,
            "reasons": ["No candidate model was provided."],
        }

    reasons: list[str] = []
    if candidate["avg_precision"] < min_precision:
        reasons.append(
            f"candidate precision {candidate['avg_precision']:.4f} < minimum {min_precision:.4f}"
        )

    f1_drop = baseline["avg_f1"] - candidate["avg_f1"]
    if f1_drop > max_f1_drop:
        reasons.append(
            f"candidate F1 dropped {f1_drop:.4f} vs baseline "
            f"({baseline['avg_f1']:.4f} -> {candidate['avg_f1']:.4f})"
        )

    hallucination_delta = candidate["hallucination_rate"] - baseline["hallucination_rate"]
    if hallucination_delta > max_hallucination_delta:
        reasons.append(
            f"candidate hallucination rate increased {hallucination_delta:.4f} vs baseline "
            f"({baseline['hallucination_rate']:.4f} -> {candidate['hallucination_rate']:.4f})"
        )

    if candidate["schema_failure_rate"] > baseline["schema_failure_rate"]:
        reasons.append(
            f"candidate schema failure rate regressed "
            f"({baseline['schema_failure_rate']:.4f} -> {candidate['schema_failure_rate']:.4f})"
        )

    return {
        "candidate_present": True,
        "promote": not reasons,
        "reasons": reasons or ["Candidate passed benchmark promotion gates."],
        "deltas": {
            "precision": round(candidate["avg_precision"] - baseline["avg_precision"], 4),
            "recall": round(candidate["avg_recall"] - baseline["avg_recall"], 4),
            "f1": round(candidate["avg_f1"] - baseline["avg_f1"], 4),
            "hallucination_rate": round(hallucination_delta, 4),
            "avg_latency_ms": candidate["avg_latency_ms"] - baseline["avg_latency_ms"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark current and candidate Ollama models")
    parser.add_argument("--gold", default="data/eval/gold_smoke.jsonl")
    parser.add_argument(
        "--baseline-model",
        default=os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b"),
    )
    parser.add_argument("--candidate-model", default=None)
    parser.add_argument("--out-dir", default="data/eval/results")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--min-precision", type=float, default=0.70)
    parser.add_argument("--max-f1-drop", type=float, default=0.05)
    parser.add_argument("--max-hallucination-delta", type=float, default=0.02)
    args = parser.parse_args()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_checkpoint = out_dir / f"checkpoint_{timestamp}_{_slug(args.baseline_model)}.json"
    baseline = run_evaluation(
        args.gold,
        args.baseline_model,
        mode="few_shot",
        limit=args.limit,
        checkpoint_path=str(baseline_checkpoint),
    )
    candidate = None
    if args.candidate_model:
        candidate_checkpoint = (
            out_dir / f"checkpoint_{timestamp}_{_slug(args.candidate_model)}.json"
        )
        candidate = run_evaluation(
            args.gold,
            args.candidate_model,
            mode="finetuned",
            limit=args.limit,
            checkpoint_path=str(candidate_checkpoint),
        )

    decision = _promotion_decision(
        baseline=baseline,
        candidate=candidate,
        min_precision=args.min_precision,
        max_f1_drop=args.max_f1_drop,
        max_hallucination_delta=args.max_hallucination_delta,
    )

    report = {
        "benchmarked_at": datetime.now(timezone.utc).isoformat(),
        "gold_file": args.gold,
        "baseline_model": args.baseline_model,
        "candidate_model": args.candidate_model,
        "baseline": baseline,
        "candidate": candidate,
        "promotion_gate": decision,
    }

    name = f"benchmark_{timestamp}_{_slug(args.baseline_model)}"
    if args.candidate_model:
        name += f"_vs_{_slug(args.candidate_model)}"
    out_path = out_dir / f"{name}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(f"Benchmark saved to {out_path}")
    print("Promotion gate:", "PASS" if decision["promote"] else "HOLD")
    for reason in decision["reasons"]:
        print(f"- {reason}")
    return 0 if decision["promote"] or not args.candidate_model else 1


if __name__ == "__main__":
    raise SystemExit(main())
