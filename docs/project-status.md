# Project Status

Last updated: 2026-05-23

This file is the single short status document for planning and cleanup context. Detailed operational docs remain split by topic:

- `TODO.md`: active roadmap and open work.
- `docs/architecture.md`: current runtime and LLMOps architecture.
- `docs/data-pipeline.md`: data collection, synthetic data, validation, and training data prep.
- `docs/mlops-runbook.md`: retraining, MLflow, promotion, and deploy operations.
- `docs/monitoring-guide.md`: Prometheus, Grafana, LangSmith, and anomaly checks.
- `docs/eval-results.md`: baseline evaluation results.
- `docs/final-report/`: report source and generated PDF.

## Current State

The application has a working async meeting-processing pipeline:

```text
audio upload
-> preprocess
-> WhisperX ASR/diarization
-> transcript turns in PostgreSQL
-> LLM extraction via Ollama/Qwen2.5
-> guardrails and worker assignment
-> human feedback
-> calendar sync
-> training/eval export
```

Runtime stack:

- FastAPI backend
- Next.js frontend
- Celery workers and Redis
- PostgreSQL
- Ollama
- Prometheus and Grafana
- Optional MLflow/MLOps profile

## Active Constraints

- Local machine has no GPU.
- Fine-tuning should be treated as Kaggle-assisted manual training, not automatic production retraining.
- `/admin/retrain` and Celery Beat can prepare/check/export retraining data, but Kaggle cannot act as a persistent trainer worker.
- A fine-tuned candidate must be evaluated against the current model before deploy. Do not promote just because training completed.

## Fine-Tuning Policy

Use this lifecycle until a real GPU worker exists:

```text
feedback/data export
-> training bundle
-> Kaggle training
-> download candidate artifact
-> local eval gate against current model
-> promote only if metrics improve or regressions are acceptable
-> manual Ollama deploy
```

Minimum promotion checks:

- Precision remains at or above the accepted threshold.
- F1 does not drop materially compared with the current model.
- Hallucination rate does not increase.
- Due-date extraction and assignee resolution do not regress on review samples.
- Manual smoke review passes on a few real or representative meetings.

## Cleanup Notes

The old planning and requirement files were consolidated here and into `TODO.md`. Removed files included stale phase plans, generic LLMOps requirements, generic C4 reference notes, and an old audit/remediation scratchpad whose completed items now live in code, tests, CI, or `TODO.md`.
