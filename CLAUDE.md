# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (dev)
pip install -e ".[dev]"

# Run tests
PYTHONPATH=src pytest tests/ -v

# Run a single test file
PYTHONPATH=src pytest tests/test_guardrails.py -v

# Run with coverage
PYTHONPATH=src pytest tests/ --cov=meeting_agent --cov-report=term-missing

# Lint (currently commented out in CI but configured)
ruff check src/ tests/ train/ data_pipeline/
mypy src/meeting_agent --ignore-missing-imports

# Start API server (local)
meeting-agent serve --reload

# Full stack (recommended)
docker compose up -d
# With NVIDIA GPU:
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

## Architecture

The pipeline processes audio in sequential stages:

```
Audio → ingest → preprocess (ffmpeg/noise reduce) → STT (WhisperX+Pyannote)
     → RAG (FAISS speaker index) → orchestrator (Ollama/Qwen2.5-3B)
     → guardrails (schema/PII/hallucination/jailbreak) → assignment → emit
```

**Source layout:** All application code is under `src/meeting_agent/`. Tests import with `PYTHONPATH=src`.

**Key modules:**
- `src/meeting_agent/pipeline/orchestrator.py` — LLM calls with LangSmith tracing, Redis prompt cache, chunked token budget
- `src/meeting_agent/pipeline/guardrails.py` — validation chain: Pydantic schema → hallucination → jailbreak → PII scrub
- `src/meeting_agent/pipeline/router.py` — multi-Ollama load balancer; activated when `OLLAMA_ENDPOINTS` is set in `.env`
- `src/meeting_agent/pipeline/run.py` — wires all stages into the end-to-end pipeline
- `src/meeting_agent/api/main.py` — FastAPI: `POST /meetings`, `GET /meetings/{id}`, `POST /meetings/{id}/feedback`, `DELETE /meetings/{id}`, `/metrics`
- `src/meeting_agent/prompts/templates.py` — versioned few-shot CoT prompt templates (ruff E501 intentionally ignored here)
- `src/meeting_agent/monitoring/anomaly.py` — rolling Z-score + hard threshold anomaly detector
- `src/meeting_agent/config.py` — all settings via `pydantic-settings`; reads `.env`

**Async execution:** Celery workers handle pipeline jobs asynchronously. Celery Beat triggers automated retraining every 24 hours when `RETRAIN_MIN_CORRECTIONS` threshold (default 50) is reached.

**Training stack** (`train/`, requires `pip install -e ".[train]"`):
- `finetune.py` — QLoRA via Unsloth + MLflow experiment tracking + Optuna hyperparameter search
- `distill.py` — knowledge distillation (3B→1.5B) and LoRA magnitude pruning
- `evaluate.py` — precision/recall/F1 harness; CI threshold is 0.70 precision

**Data pipeline** (`data_pipeline/`): `collect.py` builds JSONL training data from audio dirs; `synthetic.py` generates synthetic meetings via LLM; `validate.py` checks schema/bias/leakage.

**Feedback loop:** Corrections submitted via `POST /meetings/{id}/feedback` are stored in `data/transcripts/_feedback.jsonl` and consumed by the retraining pipeline.

## Environment

Copy `.env.example` to `.env`. Required keys:
- `HF_TOKEN` — HuggingFace token for Pyannote diarization model
- `OLLAMA_BASE_URL` — local Ollama endpoint (default `http://localhost:11434`)

LLM model: `qwen2.5:3b` (pull with `ollama pull qwen2.5:3b`). Fine-tuned variants are deployed to Ollama as custom models and set via `OLLAMA_LLM_MODEL`.

## Coverage exclusions

Modules that require external services (WhisperX, ffmpeg, Ollama, Pyannote) are excluded from unit test coverage — see `[tool.coverage.run] omit` in `pyproject.toml`. These are covered by integration/Docker tests.
