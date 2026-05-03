"""
Data drift detector using Population Stability Index (PSI).

Compares distributions of LLM output features between a reference window
(training-time) and a current production window to detect model drift.

Features monitored:
  - tasks_extracted  : number of action items per meeting
  - avg_token_count  : average tokens per LLM call
  - hallucination_rate: fraction of tasks flagged by guardrails
  - assignee_hit_rate : fraction of tasks with a matched worker

PSI interpretation:
  < 0.10  → no significant shift
  0.10–0.25 → moderate shift, monitor
  > 0.25  → significant drift, consider retraining

Reference distribution stored at: data/training/.drift_reference.json
Current window read from Redis key: drift:current_window (list of JSON records)
Fallback: data/training/.drift_current.jsonl (file-append by worker_task.py)

Usage:
    python train/drift_detector.py                   # compute PSI, print report
    python train/drift_detector.py --set-reference   # snapshot current as new reference
    python train/drift_detector.py --out data/training/.drift_report.json
"""

import argparse
import json
import logging
import math
import os
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

REFERENCE_PATH = Path("data/training/.drift_reference.json")
CURRENT_WINDOW_FILE = Path("data/training/.drift_current.jsonl")
REDIS_CURRENT_KEY = "drift:current_window"
REDIS_CURRENT_TTL = 60 * 60 * 24 * 7  # 7 days

# Bin edges for each feature (right-open intervals, last bin catches overflow)
_BINS: dict[str, list[float]] = {
    "tasks_extracted":   [0, 1, 2, 3, 4, 6, 8, 12, float("inf")],
    "avg_token_count":   [0, 200, 400, 600, 800, 1000, 1500, 2000, float("inf")],
    "hallucination_rate": [0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 1.01],
    "assignee_hit_rate":  [0, 0.20, 0.40, 0.60, 0.70, 0.80, 0.90, 1.01],
}

ALERT_THRESHOLD = 0.25
WARN_THRESHOLD  = 0.10


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _redis_client():
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        r.ping()
        return r
    except Exception:
        return None


def append_record(record: dict) -> None:
    """Append a production inference record to the current drift window."""
    r = _redis_client()
    if r:
        try:
            r.rpush(REDIS_CURRENT_KEY, json.dumps(record))
            r.expire(REDIS_CURRENT_KEY, REDIS_CURRENT_TTL)
            return
        except Exception as e:
            log.debug("Redis append failed: %s", e)
    CURRENT_WINDOW_FILE.parent.mkdir(parents=True, exist_ok=True)
    with CURRENT_WINDOW_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _load_current_records() -> list[dict]:
    records: list[dict] = []
    r = _redis_client()
    if r:
        try:
            raw = r.lrange(REDIS_CURRENT_KEY, 0, -1)
            records = [json.loads(x) for x in raw]
            if records:
                return records
        except Exception as e:
            log.debug("Redis load failed: %s", e)
    if CURRENT_WINDOW_FILE.exists():
        for line in CURRENT_WINDOW_FILE.read_text().splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


# ── PSI computation ───────────────────────────────────────────────────────────

def _bin_values(values: list[float], bins: list[float]) -> list[float]:
    """Return fraction of values in each bin (length = len(bins)-1)."""
    n = len(values)
    counts = [0] * (len(bins) - 1)
    for v in values:
        for i in range(len(bins) - 1):
            if bins[i] <= v < bins[i + 1]:
                counts[i] += 1
                break
    eps = 1e-6
    return [(c / n if n > 0 else eps) + eps for c in counts]


def compute_psi(reference: list[float], current: list[float], bins: list[float]) -> float:
    """Compute PSI between two lists of values using the given bin edges."""
    ref_fracs = _bin_values(reference, bins)
    cur_fracs = _bin_values(current, bins)
    psi = sum(
        (c - r) * math.log(c / r)
        for r, c in zip(ref_fracs, cur_fracs)
    )
    return round(psi, 4)


def _extract_feature_values(records: list[dict]) -> dict[str, list[float]]:
    features: dict[str, list[float]] = {k: [] for k in _BINS}
    for rec in records:
        features["tasks_extracted"].append(float(rec.get("tasks_extracted", 0)))
        features["avg_token_count"].append(float(rec.get("avg_token_count", 0)))
        features["hallucination_rate"].append(float(rec.get("hallucination_rate", 0)))
        features["assignee_hit_rate"].append(float(rec.get("assignee_hit_rate", 0)))
    return features


# ── Reference management ──────────────────────────────────────────────────────

def set_reference(records: list[dict] | None = None) -> dict:
    """Snapshot current window as the new reference distribution."""
    if records is None:
        records = _load_current_records()
    if not records:
        raise RuntimeError("No records available to set as reference")
    features = _extract_feature_values(records)
    ref = {
        "created_at": datetime.utcnow().isoformat(),
        "n_records": len(records),
        "features": {k: v for k, v in features.items()},
    }
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps(ref, indent=2))
    log.info("Reference set: n=%d, saved to %s", len(records), REFERENCE_PATH)
    return ref


def load_reference() -> dict | None:
    if REFERENCE_PATH.exists():
        return json.loads(REFERENCE_PATH.read_text())
    return None


# ── Main drift check ──────────────────────────────────────────────────────────

def run_drift_check(min_records: int = 30) -> dict:
    """
    Compute PSI for each feature between reference and current window.
    Returns a report dict with per-feature PSI, overall alert level, and metadata.
    """
    ref = load_reference()
    if ref is None:
        return {"status": "no_reference", "message": "Run --set-reference first"}

    current_records = _load_current_records()
    if len(current_records) < min_records:
        return {
            "status": "insufficient_data",
            "n_current": len(current_records),
            "min_required": min_records,
            "message": f"Need at least {min_records} records, have {len(current_records)}",
        }

    current_features = _extract_feature_values(current_records)
    ref_features: dict[str, list[float]] = ref["features"]

    psi_results: dict[str, dict] = {}
    max_psi = 0.0

    for feature, bins in _BINS.items():
        ref_vals = ref_features.get(feature, [])
        cur_vals = current_features.get(feature, [])
        if not ref_vals or not cur_vals:
            continue
        psi = compute_psi(ref_vals, cur_vals, bins)
        if psi >= ALERT_THRESHOLD:
            level = "alert"
        elif psi >= WARN_THRESHOLD:
            level = "warn"
        else:
            level = "ok"
        psi_results[feature] = {"psi": psi, "level": level}
        max_psi = max(max_psi, psi)

    overall_level = "ok"
    if max_psi >= ALERT_THRESHOLD:
        overall_level = "alert"
    elif max_psi >= WARN_THRESHOLD:
        overall_level = "warn"

    report = {
        "status": "ok",
        "computed_at": datetime.utcnow().isoformat(),
        "reference_created_at": ref.get("created_at"),
        "n_reference": ref.get("n_records", 0),
        "n_current": len(current_records),
        "overall_level": overall_level,
        "max_psi": max_psi,
        "features": psi_results,
    }
    return report


def print_report(report: dict) -> None:
    if report.get("status") != "ok":
        print(f"Drift check: {report.get('status')} — {report.get('message', '')}")
        return

    print(f"\n{'='*56}")
    print(f"DRIFT REPORT — {report['computed_at'][:19]}")
    print(f"Reference: {report['reference_created_at'][:19]}  (n={report['n_reference']})")
    print(f"Current window: n={report['n_current']}")
    print(f"{'='*56}")
    print(f"{'Feature':<22} {'PSI':>8}  {'Level'}")
    print(f"{'-'*56}")
    for feat, data in report["features"].items():
        symbol = {"ok": "✓", "warn": "⚠", "alert": "✗"}.get(data["level"], "?")
        print(f"{feat:<22} {data['psi']:>8.4f}  {symbol} {data['level']}")
    print(f"{'-'*56}")
    print(f"{'Overall':<22} {report['max_psi']:>8.4f}  → {report['overall_level'].upper()}")
    print(f"{'='*56}\n")
    if report["overall_level"] == "alert":
        print("ACTION REQUIRED: PSI > 0.25 — significant distribution shift detected.")
        print("Consider running: python train/retrain.py --force\n")
    elif report["overall_level"] == "warn":
        print("WARNING: PSI 0.10–0.25 — moderate shift, monitor closely.\n")


# ── Celery Beat task registration ─────────────────────────────────────────────

def register_beat_schedule(celery_app) -> None:
    """Register weekly drift check with Celery Beat."""
    @celery_app.task(name="meeting_agent.drift_check")
    def drift_check_task():
        report = run_drift_check()
        log.info("Drift check: overall=%s max_psi=%.4f",
                 report.get("overall_level"), report.get("max_psi", 0))
        if report.get("overall_level") == "alert":
            log.warning("DRIFT ALERT — consider retraining. Report: %s", report)
        return report

    celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
    celery_app.conf.beat_schedule["drift-check-weekly"] = {
        "task": "meeting_agent.drift_check",
        "schedule": 60 * 60 * 24 * 7,  # every 7 days
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PSI drift detector")
    parser.add_argument("--set-reference", action="store_true",
                        help="Snapshot current window as new reference distribution")
    parser.add_argument("--min-records", type=int, default=30,
                        help="Minimum records required for drift check (default: 30)")
    parser.add_argument("--out", default=None,
                        help="Save report JSON to this path")
    args = parser.parse_args()

    if args.set_reference:
        ref = set_reference()
        print(f"Reference set: n={ref['n_records']} records, created_at={ref['created_at']}")
    else:
        report = run_drift_check(min_records=args.min_records)
        print_report(report)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2))
            log.info("Report saved to %s", args.out)
