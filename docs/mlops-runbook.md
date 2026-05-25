# MLOps Fine-Tuning Runbook

This runbook describes the GPU-ready retraining path.

## What Runs Automatically

When the `mlops` compose profile is enabled:

- `beat` runs Celery Beat and checks retraining every 24 hours.
- `trainer` consumes only the `mlops` queue and runs retraining/fine-tuning jobs.
- `mlflow` stores training runs, metrics, model registry metadata, and artifacts.

The normal audio worker consumes only the default `celery` queue, so training cannot block meeting processing.

## Trigger Condition

Auto-retraining starts when:

- new human corrections since the previous retrain are `>= RETRAIN_MIN_CORRECTIONS`
- default threshold: `50`
- training data files pass validation
- DB-backed feedback export produces real examples

If the threshold is not reached, the scheduled check exits without training.

## Start GPU-Ready MLOps Services

```bash
make mlops-up
```

Equivalent:

```bash
docker compose --profile mlops up -d --build beat trainer mlflow
```

Follow logs:

```bash
make mlops-logs
```

## Manual Checks

Check threshold without training:

```bash
make retrain-check
```

Force a retrain through the local Python environment:

```bash
make retrain-force
```

Force through the running API:

```bash
curl -X POST "http://localhost:8000/admin/retrain?force=true"
```

The API-triggered job is routed to the `mlops` queue and requires the `trainer` service to be running.

## Fine-Tune Runtime Requirements

The training image is `Dockerfile.train`.

It installs:

- PyTorch CUDA runtime
- QLoRA dependencies from `.[train]`
- Unsloth
- TRL
- PEFT
- bitsandbytes
- MLflow
- Optuna

Recommended runtime:

- NVIDIA GPU
- CUDA-compatible Docker host
- at least 8 GB VRAM for the configured Qwen2.5-3B QLoRA path

## Promotion And Serving

After training succeeds, the retrain pipeline:

1. Runs the configured evaluation gate when a gold set exists.
2. Uses `data/eval/gold_synthetic_205.jsonl` for the current larger baseline benchmark when available; `data/eval/gold_smoke.jsonl` remains a fast CI smoke fallback.
3. Promotes the MLflow model only if the gate passes.
4. Writes `models/registry/promotion_manifest.json`.
5. Does not silently switch production serving.

Current promotion policy:

- Candidate precision must stay at or above `0.70`.
- Candidate F1 must not drop by more than `0.05` vs the current baseline.
- Candidate hallucination rate must not increase by more than `0.02`.
- Candidate schema failure rate must not regress.
- Recall, assignee accuracy, and latency are watch metrics, not absolute hard gates.

Deploy the promoted model explicitly:

```bash
make deploy-promoted-model APPLY=1
```

This creates the Ollama tag from the promotion manifest and writes a reversible serving env update.
