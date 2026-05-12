"""
A/B testing logic for comparing two Ollama model versions in production.

Model A = current champion (OLLAMA_LLM_MODEL)
Model B = challenger (AB_TEST_MODEL_B)

Traffic split: AB_TEST_TRAFFIC_B % of meetings go to model B.
Routing is deterministic per meeting_id (same meeting always uses same model).

Results stored in Redis: ab_test:{experiment_id}:{model}:{metric}

Usage:
    python -m meeting_agent.mlops.ab_test start --model-b qwen2.5:3b-v2 --traffic 0.1
    python -m meeting_agent.mlops.ab_test status
    python -m meeting_agent.mlops.ab_test stop
    python -m meeting_agent.mlops.ab_test results
"""

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_STATE_FILE = Path("data/training/.ab_test_state.json")
_ENABLED_VALUES = {"1", "true", "yes", "on"}


# ── State management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text())
    return {"active": False, "experiment_id": None, "model_a": None,
            "model_b": None, "traffic_b": 0.0, "started_at": None}


def save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def runtime_enabled() -> bool:
    """A/B routing is inert unless explicitly enabled in the runtime environment."""
    return os.environ.get("AB_TEST_ENABLED", "").strip().lower() in _ENABLED_VALUES


# ── Routing logic ─────────────────────────────────────────────────────────────

def route(meeting_id: str, model_a: str, model_b: str, traffic_b: float) -> str:
    """
    Deterministic routing: hash meeting_id to [0,1), use model B if < traffic_b.
    Same meeting_id always routes to the same model.
    """
    if traffic_b <= 0:
        return model_a
    if traffic_b >= 1:
        return model_b
    h = int(hashlib.md5(meeting_id.encode()).hexdigest(), 16)
    bucket = (h % 10000) / 10000.0
    return model_b if bucket < traffic_b else model_a


def get_assignment_for_meeting(meeting_id: str, default_model: str | None = None) -> dict:
    """Return assignment metadata for routing and audit logs."""
    fallback_model = default_model or os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")
    state = load_state()
    if not runtime_enabled() or not state.get("active"):
        return {
            "enabled": False,
            "experiment_id": None,
            "model": fallback_model,
            "variant": "control",
        }

    model = route(meeting_id, state["model_a"], state["model_b"], state["traffic_b"])
    return {
        "enabled": True,
        "experiment_id": state["experiment_id"],
        "model": model,
        "variant": "B" if model == state["model_b"] else "A",
    }


def get_model_for_meeting(meeting_id: str) -> str:
    """Return the model name to use for this meeting_id, respecting A/B state."""
    return get_assignment_for_meeting(meeting_id)["model"]


# ── Result logging ────────────────────────────────────────────────────────────

def log_result(
    experiment_id: str,
    model: str,
    meeting_id: str,
    metrics: dict,
) -> None:
    """Append a result record to Redis (or local file fallback)."""
    record = {
        "meeting_id": meeting_id,
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **metrics,
    }
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        key = f"ab_test:{experiment_id}:{model}:results"
        r.rpush(key, json.dumps(record))
        r.expire(key, 60 * 60 * 24 * 30)  # 30 days TTL
    except Exception as e:
        log.debug("Redis unavailable, falling back to file log: %s", e)
        log_path = Path(f"data/training/.ab_results_{experiment_id}.jsonl")
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")


# ── Results aggregation ───────────────────────────────────────────────────────

def get_results(experiment_id: str | None = None) -> dict:
    """Return aggregated results per model."""
    if experiment_id is None:
        state = load_state()
        experiment_id = state.get("experiment_id")
    if not experiment_id:
        return {}

    records: dict[str, list] = {}

    # Try Redis first
    try:
        import redis
        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        for model_key in r.scan_iter(f"ab_test:{experiment_id}:*:results"):
            model = model_key.decode().split(":")[2]
            raw = r.lrange(model_key, 0, -1)
            records[model] = [json.loads(x) for x in raw]
    except Exception:
        pass

    # Fallback: local file
    log_file = Path(f"data/training/.ab_results_{experiment_id}.jsonl")
    if log_file.exists() and not records:
        by_model: dict[str, list] = {}
        for line in log_file.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            by_model.setdefault(r["model"], []).append(r)
        records = by_model

    summary = {}
    min_sample_size = int(os.environ.get("AB_TEST_MIN_SAMPLE_SIZE", "30"))
    for model, recs in records.items():
        if not recs:
            continue
        n = len(recs)
        summary[model] = {
            "n_meetings": n,
            "ready": n >= min_sample_size,
            "min_sample_size": min_sample_size,
            "avg_tasks_extracted": sum(r.get("tasks_extracted", 0) for r in recs) / n,
            "avg_tokens": sum(r.get("total_tokens", 0) for r in recs) / n,
            "avg_latency_ms": sum(r.get("llm_latency_ms", 0) for r in recs) / n,
            "hallucination_rate": sum(r.get("hallucination_flags", 0) for r in recs) / max(
                sum(r.get("tasks_extracted", 1) for r in recs), 1),
        }

    return {
        "experiment_id": experiment_id,
        "min_sample_size": min_sample_size,
        "ready": bool(summary) and all(m["ready"] for m in summary.values()),
        "models": summary,
    }


# ── CLI commands ──────────────────────────────────────────────────────────────

def cmd_start(model_b: str, traffic: float) -> None:
    if traffic <= 0 or traffic >= 1:
        raise ValueError("traffic must be between 0 and 1 exclusive")
    model_a = os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b")
    now = datetime.now(timezone.utc)
    experiment_id = f"ab_{now.strftime('%Y%m%d_%H%M%S')}"
    state = {
        "active": True,
        "experiment_id": experiment_id,
        "model_a": model_a,
        "model_b": model_b,
        "traffic_b": traffic,
        "started_at": now.isoformat(),
        "requires_env": "AB_TEST_ENABLED=true",
    }
    save_state(state)
    log.info("A/B test started: experiment=%s  A=%s  B=%s  traffic_b=%.0f%%",
             experiment_id, model_a, model_b, traffic * 100)
    print(f"\nAdd to .env to activate:\n  AB_TEST_ENABLED=true\n  AB_TEST_MODEL_B={model_b}\n  AB_TEST_TRAFFIC_B={traffic}\n  AB_TEST_EXPERIMENT_ID={experiment_id}")


def cmd_status() -> None:
    state = load_state()
    if not state.get("active"):
        print("No active A/B test.")
        return
    print(f"Runtime on : {runtime_enabled()}")
    print(f"Experiment : {state['experiment_id']}")
    print(f"Model A    : {state['model_a']} (champion, {(1-state['traffic_b'])*100:.0f}% traffic)")
    print(f"Model B    : {state['model_b']} (challenger, {state['traffic_b']*100:.0f}% traffic)")
    print(f"Started    : {state['started_at']}")


def cmd_results() -> None:
    results = get_results()
    if not results.get("models"):
        print("No results yet.")
        return
    print(f"\nExperiment: {results['experiment_id']}\n")
    for model, m in results["models"].items():
        print(f"  Model: {model}")
        print(f"    Meetings      : {m['n_meetings']}")
        print(f"    Avg tasks     : {m['avg_tasks_extracted']:.2f}")
        print(f"    Avg tokens    : {m['avg_tokens']:.0f}")
        print(f"    Avg latency   : {m['avg_latency_ms']:.0f} ms")
        print(f"    Halluc. rate  : {m['hallucination_rate']:.3f}")
        print()


def cmd_stop() -> None:
    state = load_state()
    if not state.get("active"):
        print("No active A/B test.")
        return
    state["active"] = False
    state["stopped_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print(f"A/B test stopped: {state['experiment_id']}")
    cmd_results()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A/B test manager")
    sub = parser.add_subparsers(dest="cmd")

    start_p = sub.add_parser("start", help="Start A/B test")
    start_p.add_argument("--model-b", required=True, help="Challenger model name in Ollama")
    start_p.add_argument("--traffic", type=float, default=0.1,
                         help="Fraction of traffic to send to model B (default: 0.1)")

    sub.add_parser("status", help="Show current A/B test status")
    sub.add_parser("results", help="Show aggregated results")
    sub.add_parser("stop", help="Stop current A/B test")

    args = parser.parse_args()
    if args.cmd == "start":
        cmd_start(args.model_b, args.traffic)
    elif args.cmd == "status":
        cmd_status()
    elif args.cmd == "results":
        cmd_results()
    elif args.cmd == "stop":
        cmd_stop()
    else:
        parser.print_help()
