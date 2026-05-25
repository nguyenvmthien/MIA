"""
Automated Retraining Pipeline.

Checks the feedback store for accumulated corrections and triggers
a new fine-tuning run when enough new data has been collected.

Three ways to run:
  1. CLI (one-shot check)
       python -m meeting_agent.mlops.retrain --check
       python -m meeting_agent.mlops.retrain --force

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
import hashlib
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from meeting_agent.config import settings

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Configuration ─────────────────────────────────────────────────────────────
RETRAIN_MIN_CORRECTIONS = int(
    os.environ.get("RETRAIN_MIN_CORRECTIONS", settings.retrain_min_corrections)
)
RETRAIN_DATA_PATHS      = os.environ.get(
    "RETRAIN_DATA_PATHS",
    "data/training/synthetic.jsonl,data/training/collected.jsonl",
).split(",")
RETRAIN_OUTPUT_DIR      = os.environ.get("RETRAIN_OUTPUT_DIR", settings.retrain_output_dir)
MLFLOW_TRACKING_URI     = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5000")

# State file tracks how many corrections were present at the last retrain
_STATE_FILE = Path("data/training/.retrain_state.json")
_MODEL_REGISTRY_DIR = Path(os.environ.get("MODEL_REGISTRY_DIR", "models/registry"))
_PROMOTION_MANIFEST_PATH = _MODEL_REGISTRY_DIR / "promotion_manifest.json"


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
    try:
        from meeting_agent.mlops.data_pipeline.collect_interactions import collect

        exported = collect(out_path=out_path, fmt="sft", min_corrections=1, limit=10_000)
    except Exception as exc:
        log.warning("DB-backed feedback export failed: %s", exc)
        exported = 0
    if exported == 0:
        log.warning(
            "No DB-backed feedback examples exported; refusing to fabricate transcript text"
        )
        return 0
    log.info("Exported %d DB-backed feedback examples → %s", exported, out_path)
    return exported


def _get_champion_f1() -> float:
    """Return F1 of current Production model from MLflow, or 0 if unavailable."""
    try:
        import mlflow
        client = mlflow.MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
        versions = client.get_latest_versions("meeting-agent-qwen", stages=["Production"])
        if versions:
            run = client.get_run(versions[0].run_id)
            return float(run.data.metrics.get("eval_f1", 0))
    except Exception as e:
        log.debug("MLflow champion lookup failed: %s", e)
    # Fallback: read from local state
    state = _load_state()
    for run in reversed(state.get("runs", [])):
        f1 = run.get("eval_result", {}).get("avg_f1")
        if f1 is not None and run.get("promoted"):
            return f1
    return 0.0


def _sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
        return h.hexdigest()
    files = sorted(p for p in path.rglob("*") if p.is_file())
    if not files:
        return None
    for file_path in files:
        h.update(str(file_path.relative_to(path)).encode())
        with file_path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    return h.hexdigest()


def _build_promotion_manifest(
    eval_result: dict,
    output_dir: str,
    *,
    mlflow_model_version: str | None = None,
    mlflow_run_id: str | None = None,
) -> dict:
    output_path = Path(output_dir)
    gguf_path = output_path / "gguf"
    adapter_path = output_path / "adapter"
    ollama_tag = os.environ.get(
        "PROMOTED_OLLAMA_MODEL_TAG",
        f"meeting-agent:{output_path.name}",
    )
    artifact_path = gguf_path if gguf_path.exists() else output_path
    return {
        "schema_version": "model_promotion_v1",
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "ollama_model_tag": ollama_tag,
        "output_dir": str(output_path),
        "artifact_path": str(artifact_path),
        "artifact_sha256": _sha256_path(artifact_path),
        "adapter_path": str(adapter_path) if adapter_path.exists() else None,
        "mlflow_registered_model": "meeting-agent-qwen",
        "mlflow_model_version": mlflow_model_version,
        "mlflow_run_id": mlflow_run_id,
        "eval_result": eval_result,
        "serving_update": {
            "automatic": False,
            "env_var": "OLLAMA_LLM_MODEL",
            "target_value": ollama_tag,
            "rollback_value": os.environ.get("OLLAMA_LLM_MODEL", "qwen2.5:3b"),
        },
    }


def _write_promotion_manifest(manifest: dict) -> None:
    _PROMOTION_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROMOTION_MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))


def _promote_mlflow_model(eval_result: dict) -> dict:
    """Transition the latest Staging model to Production in MLflow and write deploy metadata."""
    try:
        import mlflow
        client = mlflow.MlflowClient(tracking_uri=MLFLOW_TRACKING_URI)
        versions = client.get_latest_versions("meeting-agent-qwen", stages=["Staging"])
        if not versions:
            log.warning("No Staging model found in MLflow to promote")
            return {"promoted": False, "reason": "No Staging model found in MLflow"}
        v = versions[0]
        client.transition_model_version_stage(
            name="meeting-agent-qwen",
            version=v.version,
            stage="Production",
            archive_existing_versions=True,
        )
        client.set_model_version_tag(v.name, v.version, "eval_f1", str(eval_result.get("avg_f1", "")))
        client.set_model_version_tag(
            v.name,
            v.version,
            "promoted_at",
            datetime.now(timezone.utc).isoformat(),
        )
        manifest = _build_promotion_manifest(
            eval_result,
            RETRAIN_OUTPUT_DIR,
            mlflow_model_version=str(v.version),
            mlflow_run_id=v.run_id,
        )
        _write_promotion_manifest(manifest)
        client.set_model_version_tag(v.name, v.version, "ollama_model_tag", manifest["ollama_model_tag"])
        client.set_model_version_tag(v.name, v.version, "artifact_sha256", manifest["artifact_sha256"] or "")
        log.info(
            "MLflow: model version %s promoted to Production; manifest=%s",
            v.version,
            _PROMOTION_MANIFEST_PATH,
        )
        return {"promoted": True, "manifest": manifest}
    except Exception as e:
        log.warning("MLflow promotion failed: %s", e)
        return {"promoted": False, "reason": str(e)}


def should_retrain(force: bool = False) -> tuple[bool, str]:
    """
    Return (should_retrain, reason).
    True when new corrections since last run exceed RETRAIN_MIN_CORRECTIONS.
    """
    if force:
        return True, "forced"

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
    validation_reports = []
    for data_file in data_files:
        validate_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "meeting_agent.mlops.data_pipeline.validate",
                "--train",
                data_file,
            ],
            capture_output=True,
            text=True,
        )
        validation_reports.append({
            "file": data_file,
            "returncode": validate_result.returncode,
            "stdout": validate_result.stdout,
            "stderr": validate_result.stderr,
        })
        if validate_result.returncode != 0:
            report_path = Path("data/training/.validation_report.json")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(validation_reports, indent=2))
            log.error("Data validation failed for %s; aborting retrain", data_file)
            return {
                "status": "failed",
                "reason": f"Data validation failed for {data_file}",
                "validation_report": str(report_path),
            }

    report_path = Path("data/training/.validation_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(validation_reports, indent=2))

    # Run fine-tuning as subprocess so it runs in its own process/GPU context
    log.info("Starting fine-tuning with data: %s", data_files)
    cmd = [
        sys.executable, "-m", "meeting_agent.mlops.finetune",
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

    # ── CI gate: evaluate new model vs champion ───────────────────────────────
    eval_result = {}
    promoted = False
    promotion_result: dict = {}
    if success:
        gold_path = os.environ.get("EVAL_GOLD_PATH", "data/eval/gold_synthetic_205.jsonl")
        eval_limit = os.environ.get("EVAL_LIMIT", "100")
        if Path(gold_path).exists():
            log.info("Running CI eval gate on %s ...", gold_path)
            eval_cmd = [
                sys.executable, "-m", "meeting_agent.mlops.evaluate",
                "--gold", gold_path,
                "--mode", "finetuned",
                "--model", RETRAIN_OUTPUT_DIR,
                "--out", "data/training/.ci_eval_result.json",
            ]
            if eval_limit:
                eval_cmd.extend(["--limit", eval_limit])
            eval_proc = subprocess.run(eval_cmd, capture_output=True, text=True)
            ci_passed = eval_proc.returncode == 0

            if Path("data/training/.ci_eval_result.json").exists():
                eval_result = json.loads(Path("data/training/.ci_eval_result.json").read_text())

            # Compare against champion in MLflow
            champion_f1 = _get_champion_f1()
            new_f1 = eval_result.get("avg_f1", 0)
            f1_drop = champion_f1 - new_f1

            if not ci_passed:
                log.warning("CI gate: precision < 0.70, NOT promoting model")
            elif f1_drop > 0.05:
                log.warning("CI gate: F1 dropped %.3f vs champion (%.3f→%.3f), NOT promoting",
                            f1_drop, champion_f1, new_f1)
            else:
                log.info("CI gate PASSED (F1=%.3f, champion=%.3f), promoting model", new_f1, champion_f1)
                promotion_result = _promote_mlflow_model(eval_result)
                promoted = bool(promotion_result.get("promoted"))
        else:
            log.warning("Gold eval set not found at %s — skipping CI gate", gold_path)

    # Update state
    from meeting_agent.pipeline.feedback import load_feedback
    current_count = len(load_feedback(limit=100_000))

    state = _load_state()
    run_record = {
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "data_files": data_files,
        "feedback_corrections_included": exported,
        "success": success,
        "output_dir": RETRAIN_OUTPUT_DIR,
        "eval_result": eval_result,
        "promoted": promoted,
        "promotion_result": promotion_result,
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
        "eval_f1": eval_result.get("avg_f1"),
        "promoted": promoted,
        "promotion_manifest": str(_PROMOTION_MANIFEST_PATH) if promoted else None,
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
