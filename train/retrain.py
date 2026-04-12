"""
Automated Retraining Pipeline.

Checks the feedback store for accumulated corrections and triggers
a new fine-tuning run when enough new data has been collected.

Three ways to run:
  1. CLI (one-shot check)
       python train/retrain.py --check
       python train/retrain.py --force

  2. Celery Beat (periodic — runs inside the worker process)
       Configured in pipeline/worker_task.py beat_schedule

  3. REST API trigger
       POST /admin/retrain   (see api/main.py)

Thresholds (configurable via env):
  RETRAIN_MIN_CORRECTIONS=50   minimum new corrections before retraining
  RETRAIN_DATA_PATHS=data/training/synthetic.jsonl,data/training/collected.jsonl
  RETRAIN_OUTPUT_DIR=models/qwen-meeting-latest
  MLFLOW_TRACKING_URI=http://localhost:5000
"""

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Configuration ─────────────────────────────────────────────────────────────
RETRAIN_MIN_CORRECTIONS = int(os.environ.get("RETRAIN_MIN_CORRECTIONS", "50"))
RETRAIN_DATA_PATHS      = os.environ.get(
    "RETRAIN_DATA_PATHS",
    "data/training/synthetic.jsonl,data/training/collected.jsonl",
).split(",")
RETRAIN_OUTPUT_DIR      = os.environ.get("RETRAIN_OUTPUT_DIR", "models/qwen-meeting-latest")
MLFLOW_TRACKING_URI     = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

# State file tracks how many corrections were present at the last retrain
_STATE_FILE = Path("data/training/.retrain_state.json")


def _load_state() -> dict:
    if _STATE_FILE.exists():
        return json.loads(_STATE_FILE.read_text())
    return {"last_correction_count": 0, "last_retrain_at": None, "runs": []}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _export_feedback_as_training_data(out_path: str) -> int:
    """
    Convert accumulated feedback corrections into JSONL training examples
    and write to out_path for inclusion in the next training run.
    """
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from meeting_agent.pipeline.feedback import load_feedback

    corrections = load_feedback(limit=10_000)
    if not corrections:
        return 0

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(out_path, "w") as f:
        for c in corrections:
            if c.is_false_positive:
                continue  # skip — these tell us what NOT to extract (handled by negative examples)
            row = {
                "transcript": f"[Action item]: {c.original_description}",
                "meeting_date": (
                    c.submitted_at.date().isoformat() if c.submitted_at else "2026-01-01"
                ),
                "participants": c.corrected_assignee or c.original_assignee or "",
                "action_items": [{
                    "description": c.corrected_description or c.original_description,
                    "assignee": c.corrected_assignee or c.original_assignee,
                    "due_date": c.corrected_due_date or c.original_due_date,
                    "priority": "medium",
                    "notes": "human-corrected example",
                }],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1

    log.info("Exported %d feedback corrections → %s", count, out_path)
    return count


def should_retrain(force: bool = False) -> tuple[bool, str]:
    """
    Return (should_retrain, reason).
    True when new corrections since last run exceed RETRAIN_MIN_CORRECTIONS.
    """
    if force:
        return True, "forced"

    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from meeting_agent.pipeline.feedback import load_feedback

    current_count = len(load_feedback(limit=100_000))
    state = _load_state()
    new_corrections = current_count - state["last_correction_count"]

    if new_corrections >= RETRAIN_MIN_CORRECTIONS:
        return True, f"{new_corrections} new corrections (threshold {RETRAIN_MIN_CORRECTIONS})"
    return False, f"only {new_corrections} new corrections (need {RETRAIN_MIN_CORRECTIONS})"


def run_retrain(force: bool = False) -> dict:
    """
    Check threshold and trigger fine-tuning if met.
    Returns a status dict.
    """
    trigger, reason = should_retrain(force=force)
    log.info("Retrain check: trigger=%s reason=%s", trigger, reason)

    if not trigger:
        return {"status": "skipped", "reason": reason}

    # Export feedback corrections as additional training data
    feedback_path = "data/training/feedback_corrections.jsonl"
    exported = _export_feedback_as_training_data(feedback_path)

    # Assemble data files
    data_files = [p for p in RETRAIN_DATA_PATHS if Path(p).exists()]
    if exported > 0:
        data_files.append(feedback_path)

    if not data_files:
        return {"status": "failed", "reason": "No training data files found"}

    # Validate dataset before training
    validate_result = subprocess.run(
        [sys.executable, "data_pipeline/validate.py", "--train", data_files[0]],
        capture_output=True, text=True,
    )
    if validate_result.returncode != 0:
        log.warning("Data validation warnings:\n%s", validate_result.stdout)

    # Run fine-tuning as subprocess so it runs in its own process/GPU context
    log.info("Starting fine-tuning with data: %s", data_files)
    cmd = [
        sys.executable, "train/finetune.py",
        "--data", *data_files,
        "--output", RETRAIN_OUTPUT_DIR,
        "--mlflow-uri", MLFLOW_TRACKING_URI,
        "--epochs", "3",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    success = result.returncode == 0

    if success:
        log.info("Fine-tuning completed successfully")
    else:
        log.error("Fine-tuning failed:\n%s", result.stderr[-2000:])

    # Update state
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from meeting_agent.pipeline.feedback import load_feedback
    current_count = len(load_feedback(limit=100_000))

    state = _load_state()
    run_record = {
        "triggered_at": datetime.utcnow().isoformat(),
        "reason": reason,
        "data_files": data_files,
        "feedback_corrections_included": exported,
        "success": success,
        "output_dir": RETRAIN_OUTPUT_DIR,
    }
    state["last_correction_count"] = current_count
    state["last_retrain_at"] = run_record["triggered_at"]
    state["runs"].append(run_record)
    _save_state(state)

    return {
        "status": "completed" if success else "failed",
        "reason": reason,
        "data_files": data_files,
        "output_dir": RETRAIN_OUTPUT_DIR,
        "corrections_included": exported,
    }


# ── Celery Beat task ──────────────────────────────────────────────────────────

def register_beat_schedule(celery_app):
    """
    Register the periodic retrain check with Celery Beat.
    Call this from worker_task.py after creating the Celery app.
    """
    @celery_app.task(name="meeting_agent.check_retrain")
    def check_retrain_task():
        result = run_retrain()
        log.info("Celery Beat retrain check: %s", result)
        return result

    celery_app.conf.beat_schedule = {
        "check-retrain-daily": {
            "task": "meeting_agent.check_retrain",
            "schedule": 60 * 60 * 24,  # every 24 hours
        },
    }
    return check_retrain_task


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Automated retraining pipeline")
    p.add_argument("--check", action="store_true",
                   help="Check if retrain is needed (dry-run)")
    p.add_argument("--force", action="store_true",
                   help="Force retrain regardless of correction count")
    args = p.parse_args()

    if args.check:
        trigger, reason = should_retrain()
        print(f"Should retrain: {trigger} — {reason}")
    else:
        result = run_retrain(force=args.force)
        print(json.dumps(result, indent=2))
