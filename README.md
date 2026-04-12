# Meeting AI Agent

An LLMOps-driven pipeline that converts meeting audio into structured, worker-assigned action items — powered entirely by local open-source models (no paid API required).

```
Audio → WhisperX (ASR+Diarize) → Qwen2.5-3B (LLM) → Action Items JSON
```

---

## Table of Contents

1. [How it works](#how-it-works)
2. [Project structure](#project-structure)
3. [How to run](#how-to-run)
   - [Option A — Local dev (no Docker)](#option-a--local-dev-no-docker)
   - [Option B — Docker Compose (recommended)](#option-b--docker-compose-recommended)
   - [Using the CLI](#using-the-cli)
   - [Using the REST API](#using-the-rest-api)
   - [Fine-tuning](#fine-tuning)
   - [Data pipeline](#data-pipeline)
   - [Evaluation](#evaluation)
   - [Monitoring](#monitoring)
4. [Output format](#output-format)
5. [LLMOps coverage](#llmops-coverage)
6. [Documentation](#documentation)

---

## How it works

```
Audio file
   │
   ▼  [ingest]       validate format, store to data/audio/
   │
   ▼  [preprocess]   ffmpeg → 16 kHz mono WAV, noise reduction
   │
   ▼  [STT]          WhisperX ASR → word-level transcript
      [diarize]      Pyannote → speaker labels (SPEAKER_00, SPEAKER_01 ...)
   │
   ▼  [RAG]          FAISS speaker index built from transcript turns
   │
   ▼  [orchestrate]  Chunked prompts → Ollama / Qwen2.5-3B
   │    ├── Meeting summary (3–5 sentences)
   │    └── Action items (JSON array, few-shot CoT)
   │
   ▼  [guardrails]   JSON schema (Pydantic), jailbreak check, PII scrub,
   │                 hallucination detection, due-date sanity
   │
   ▼  [assign]       Exact name → fuzzy match → human_review escalation
   │                 Confidence scoring per task
   │
   ▼  [emit]         MeetingSummary JSON + Prometheus metrics + anomaly check
```

---

## Project structure

```
.
├── src/meeting_agent/
│   ├── config.py                  Settings (pydantic-settings, reads .env)
│   ├── schemas/                   Pydantic v2 data contracts
│   │   ├── transcript.py          TranscriptTurn
│   │   ├── worker.py              Worker, WorkerRoster
│   │   ├── task.py                ExtractedTask, TaskPriority, TaskStatus
│   │   └── meeting.py             MeetingSummary, RunMetrics, StageTiming
│   ├── pipeline/
│   │   ├── ingest.py              Stage 1 — validate & store audio
│   │   ├── preprocess.py          Stage 2 — ffmpeg + noise reduction
│   │   ├── stt.py                 Stage 3 — WhisperX + Pyannote
│   │   ├── rag.py                 FAISS speaker profile index
│   │   ├── orchestrator.py        Stage 4 — LLM calls (LangSmith + Redis cache + router)
│   │   ├── guardrails.py          Schema, hallucination, jailbreak, PII
│   │   ├── pii.py                 PII regex masker
│   │   ├── cache.py               Redis prompt cache
│   │   ├── router.py              Multi-Ollama load balancer (distributed inference)
│   │   ├── assignment.py          Stage 5 — worker resolution
│   │   ├── feedback.py            User correction storage (feedback loop)
│   │   ├── run.py                 End-to-end pipeline runner
│   │   └── worker_task.py         Celery async task + Beat retraining schedule
│   ├── prompts/templates.py       Versioned few-shot CoT prompt templates
│   ├── monitoring/
│   │   ├── metrics.py             Prometheus counters & histograms
│   │   └── anomaly.py             Rolling-window statistical anomaly detector
│   ├── api/main.py                FastAPI (submit / poll / feedback / metrics)
│   └── cli.py                     `meeting-agent` CLI
├── train/
│   ├── finetune.py                QLoRA fine-tuning (Unsloth + MLflow + Optuna)
│   ├── dataset.py                 Dataset loading & instruction formatting
│   ├── evaluate.py                Precision / Recall / F1 eval harness
│   ├── distill.py                 Knowledge distillation (3B→1.5B) + LoRA pruning
│   └── retrain.py                 Automated retraining scheduler (CLI + Celery Beat)
├── data_pipeline/
│   ├── collect.py                 Audio dir → JSONL training data
│   ├── validate.py                Bias, leakage, schema, duplicate checks
│   └── synthetic.py               LLM-generated synthetic meeting data
├── tests/                         Unit tests (43 passing)
├── docs/                          Architecture & design documents
├── docker/                        Prometheus config, Grafana provisioning
├── .github/workflows/ci.yml       CI: lint → unit → schema smoke → eval smoke → docker
├── docker-compose.yml
├── Dockerfile
└── .env.example
```

---

## How to run

### Option A — Local dev (no Docker)

#### 1. Prerequisites

```bash
# Python 3.10+
python3 --version

# ffmpeg (required for audio preprocessing)
brew install ffmpeg           # macOS
sudo apt install ffmpeg       # Ubuntu/Debian

# Ollama — local LLM runtime
# Download from https://ollama.com
ollama pull qwen2.5:3b
ollama pull nomic-embed-text
```

#### 2. Install

```bash
git clone <repo>
cd MEETING-AGENT

pip install -e ".[dev]"
```

#### 3. Configure

```bash
cp .env.example .env
```

Edit `.env` — minimum required:

```env
# Free token from https://huggingface.co/pyannote/speaker-diarization-3.1
HF_TOKEN=hf_your_token_here

# Point to your running Ollama
OLLAMA_BASE_URL=http://localhost:11434
```

For LangSmith tracing (optional — free tier at smith.langchain.com):
```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls_your_key_here
```

#### 4. Run

```bash
# CLI — process a single file
meeting-agent process meeting.mp3 --roster examples/roster.json --output result.json

# API server
meeting-agent serve --reload
# → http://localhost:8000/docs
```

---

### Option B — Docker Compose (recommended)

Starts everything: API, Celery worker, Ollama, Postgres, Redis, Prometheus, Grafana.

```bash
cp .env.example .env
# Edit .env — set HF_TOKEN at minimum

docker compose up
```

CPU-only (default):
```bash
docker compose up -d
```

With NVIDIA GPU (optional):
```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

`docker-compose.gpu.yml` only adds GPU device reservation for the `ollama` service.

Notes:
- No GPU machine: use `docker compose up -d` (default CPU mode).
- NVIDIA GPU machine: use `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d`.
- If you edited healthcheck/service definitions in compose, use recreate to apply changes:
  `docker compose up -d --force-recreate <service>`.

| Service    | URL                       | Credentials  |
|------------|---------------------------|--------------|
| API        | http://localhost:8000     | —            |
| API docs   | http://localhost:8000/docs| —            |
| Prometheus | http://localhost:9090     | —            |
| Grafana    | http://localhost:3000     | admin/admin  |

Wait ~60 seconds for Ollama to pull the models on first start.

Observability stack:
- Prometheus: collects metrics from API (`/metrics`) and stores time-series data.
- Grafana: visualizes metrics from Prometheus (dashboards, charts, alerts UI).
- LangSmith: traces LLM execution (prompt/response flow) for debugging quality and latency.

Why Grafana can look empty:
- No traffic yet -> no useful time-series to draw.
- Wrong time range in dashboard.
- No provisioned dashboard/data source.

Quick smoke traffic for dashboards:
```bash
for i in {1..30}; do curl -s http://localhost:8000/health >/dev/null; done
```

To stop:
```bash
docker compose down
```

To wipe all data (including models):
```bash
docker compose down -v
```

---

### Using the CLI

#### Process a meeting file

```bash
meeting-agent process path/to/meeting.mp3 \
  --roster path/to/roster.json \
  --output result.json
```

**roster.json** format:
```json
{
  "workers": [
    {
      "worker_id": "w1",
      "name": "Alice Chen",
      "aliases": ["Alice"],
      "role": "Product Manager",
      "email": "alice@example.com"
    },
    {
      "worker_id": "w2",
      "name": "Bob Kim",
      "aliases": ["Bob", "Bobby"],
      "role": "Developer",
      "email": "bob@example.com"
    }
  ]
}
```

#### Start the API server

```bash
meeting-agent serve                    # production
meeting-agent serve --reload           # dev mode with auto-reload
meeting-agent serve --host 0.0.0.0 --port 8080
```

---

### Using the REST API

#### Submit a meeting

```bash
curl -X POST http://localhost:8000/meetings \
  -F "audio=@meeting.mp3" \
  -F 'roster_json={"workers":[{"worker_id":"w1","name":"Alice Chen","aliases":["Alice"]}]}'
```

Response:
```json
{"meeting_id": "abc-123", "status": "accepted"}
```

#### Poll for results

```bash
curl http://localhost:8000/meetings/abc-123
```

Returns `{"status": "pending"}` → `{"status": "processing"}` → full `MeetingSummary` JSON.

#### Submit feedback / corrections

```bash
curl -X POST http://localhost:8000/meetings/abc-123/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "corrections": [{
      "meeting_id": "abc-123",
      "task_id": "abc-123_c0_1",
      "original_assignee": "Alice",
      "corrected_assignee": "Bob Kim",
      "original_description": "write the docs",
      "corrected_description": "Write API documentation"
    }],
    "reviewer": "Carol"
  }'
```

Corrections are stored in `data/transcripts/_feedback.jsonl` and consumed by the retraining pipeline.

#### Delete meeting data (GDPR)

```bash
curl -X DELETE http://localhost:8000/meetings/abc-123
```

---

### Fine-tuning

#### 1. Generate synthetic training data

```bash
# Generate 50 synthetic meeting samples using the local LLM
python data_pipeline/synthetic.py --count 50 --out data/training/synthetic.jsonl
```

#### 2. Validate the dataset

```bash
python data_pipeline/validate.py \
  --train data/training/synthetic.jsonl \
  --val   data/training/val.jsonl
```

Checks: schema conformance, speaker balance, train/val leakage, duplicates.

#### 3. Fine-tune (requires GPU with ≥8GB VRAM)

```bash
pip install -e ".[train]"

python train/finetune.py \
  --data data/training/synthetic.jsonl \
  --output models/qwen-meeting-v1 \
  --epochs 3

# With Optuna hyperparameter search:
python train/finetune.py --data data/training/synthetic.jsonl --search
```

MLflow UI to track experiments:
```bash
mlflow ui --port 5000
# → http://localhost:5000
```

#### 4. Deploy fine-tuned model via Ollama

```bash
# After training, the GGUF file is in models/qwen-meeting-v1/gguf/
# Create a Modelfile and push to Ollama:
cat > Modelfile <<EOF
FROM ./models/qwen-meeting-v1/gguf/model.gguf
EOF
ollama create meeting-agent-v1 -f Modelfile

# Update .env to use the fine-tuned model:
# OLLAMA_LLM_MODEL=meeting-agent-v1
```

---

### Data pipeline

#### Collect from audio directory

```bash
python data_pipeline/collect.py audio \
  --audio-dir data/raw/audio \
  --roster examples/roster.json \
  --out data/training/collected.jsonl
```

#### Use feedback corrections as training data

```bash
# Feedback corrections are stored at:
cat data/transcripts/_feedback.jsonl

# Include them alongside other training data:
python train/finetune.py \
  --data data/training/synthetic.jsonl data/training/collected.jsonl \
  --output models/qwen-meeting-v2
```

---

### Distillation & Pruning

#### Knowledge distillation (3B teacher → 1.5B student)

Useful when deploying on CPU-only or memory-constrained hardware. Cuts inference time ~2× with <5% quality loss.

```bash
pip install -e ".[train]"

python train/distill.py distill \
  --teacher models/qwen-meeting-v1/adapter \
  --student-base unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit \
  --data data/training/synthetic.jsonl \
  --output models/qwen-meeting-student \
  --epochs 3
```

#### LoRA magnitude pruning (reduce adapter size)

Zero out the lowest-magnitude 30% of LoRA weights — reduces adapter file size with minimal accuracy impact.

```bash
python train/distill.py prune \
  --adapter models/qwen-meeting-v1/adapter \
  --output  models/qwen-meeting-pruned \
  --sparsity 0.3
```

---

### Distributed Inference (multi-GPU / multi-node)

Set `OLLAMA_ENDPOINTS` to activate the load balancer — no code changes needed:

```env
# .env
OLLAMA_ENDPOINTS=http://gpu1:11434,http://gpu2:11434,http://gpu3:11434
OLLAMA_ROUTING_STRATEGY=least_loaded   # or: round_robin
```

The router automatically:
- Runs health checks every 30 seconds
- Fails over to healthy endpoints on errors
- Tracks in-flight requests per endpoint (for `least_loaded` mode)

Check live endpoint stats:
```bash
curl http://localhost:8000/admin/router-stats
```

When `OLLAMA_ENDPOINTS` is not set, falls back to the single `OLLAMA_BASE_URL` transparently.

---

### Automated Retraining

#### Check if retraining is needed

```bash
python train/retrain.py --check
# → "Should retrain: False — only 12 new corrections (need 50)"
```

#### Trigger manually

```bash
python train/retrain.py --force       # via CLI
curl -X POST "http://localhost:8000/admin/retrain?force=true"  # via API
```

#### Celery Beat (automatic, every 24 hours)

```bash
# Run alongside the Celery worker:
celery -A meeting_agent.pipeline.worker_task.celery_app beat --loglevel=info
```

Checks the feedback store every 24 hours. When corrections exceed `RETRAIN_MIN_CORRECTIONS` (default 50), automatically:
1. Exports corrections as training examples
2. Validates the dataset
3. Runs `train/finetune.py`
4. Logs the new model to MLflow

View retraining history:
```bash
curl http://localhost:8000/admin/retrain/state
```

Configure thresholds in `.env`:
```env
RETRAIN_MIN_CORRECTIONS=50
RETRAIN_DATA_PATHS=data/training/synthetic.jsonl,data/training/collected.jsonl
RETRAIN_OUTPUT_DIR=models/qwen-meeting-latest
```

---

### Evaluation

```bash
# Run precision/recall/F1 evaluation on a labeled gold set
python train/evaluate.py \
  --gold data/eval/gold.jsonl \
  --out  results/eval.json
```

Gold set format (each line):
```json
{
  "meeting_date": "2026-04-12",
  "participants": "Alice Chen, Bob Kim",
  "transcript_turns": [
    {"speaker_name": "Alice Chen", "speaker_id": "SPEAKER_00",
     "start_ms": 0, "end_ms": 5000,
     "text": "Bob, can you send the report by Friday?"}
  ],
  "roster": {"workers": [{"worker_id": "w1", "name": "Bob Kim", "aliases": ["Bob"]}]},
  "action_items": [
    {"description": "Send report", "assignee": "Bob Kim",
     "due_date": "2026-04-17", "priority": "high", "notes": null}
  ]
}
```

Quality targets: Precision ≥ 0.85 · Recall ≥ 0.90 · Hallucination ≤ 5%

---

### Monitoring

Prometheus metrics are at `GET /metrics`. Import Grafana dashboard:

1. Open http://localhost:3000 (admin/admin)
2. Datasource is auto-provisioned as `Prometheus → http://prometheus:9090`
3. Create dashboards using these key metrics:

| Metric | Description |
|--------|-------------|
| `meeting_stage_duration_seconds` | Per-stage latency histogram |
| `meeting_llm_tokens_total` | Cumulative token usage |
| `meeting_hallucination_flags_total` | Guardrail detections |
| `meeting_anomaly_events_total` | Statistical outlier events |
| `meeting_tasks_extracted_total` | Successfully extracted tasks |
| `meeting_jobs_total{status}` | Completed vs failed jobs |

---

## Output format

```json
{
  "meeting_id": "abc-123",
  "job_status": "completed",
  "participants": ["Alice Chen", "Bob Kim"],
  "summary_text": "The team reviewed Q2 priorities...",
  "action_items": [
    {
      "task_id": "abc-123_c0_0",
      "description": "Send quarterly report to client",
      "assignee": "Bob Kim",
      "assignee_id": "w2",
      "due_date": "2026-04-17",
      "priority": "high",
      "status": "open",
      "extraction_confidence": 0.9,
      "source_turn_ids": ["turn-uuid-1"]
    }
  ],
  "unresolved_items": [],
  "human_review_items": [],
  "run_metrics": {
    "total_tokens_used": 3840,
    "tasks_extracted": 5,
    "hallucination_flags": 0,
    "stage_timings": {
      "ingest_ms": 80, "preprocess_ms": 1200,
      "stt_ms": 42000, "llm_ms": 7400,
      "assignment_ms": 12, "total_ms": 50692
    }
  }
}
```

---

## LLMOps coverage

| Requirement | Status | Implementation |
|---|---|---|
| Model selection | ✅ | WhisperX large-v3 + Qwen2.5-3B Q4_K_M |
| Fine-tuning (QLoRA) | ✅ | `train/finetune.py` — Unsloth + PEFT |
| Model versioning | ✅ | MLflow `log_model` in `train/finetune.py` |
| Data collection | ✅ | `data_pipeline/collect.py` |
| Data validation | ✅ | `data_pipeline/validate.py` — bias/leakage/schema |
| Synthetic data | ✅ | `data_pipeline/synthetic.py` |
| Inference optimization | ✅ | GGUF Q4_K_M, token chunking, Redis cache |
| Model distillation | ✅ | `train/distill.py` — KL-divergence KD (3B→1.5B) |
| Model pruning | ✅ | `train/distill.py prune` — magnitude-based LoRA sparsity |
| Distributed inference | ✅ | `pipeline/router.py` — multi-Ollama load balancer |
| FAISS RAG | ✅ | `pipeline/rag.py` — speaker profile retrieval |
| Prometheus + Grafana | ✅ | `monitoring/metrics.py`, docker-compose |
| LangSmith tracing | ✅ | `@traceable` on `_raw_llm_call` in orchestrator |
| Feedback loop | ✅ | `pipeline/feedback.py` + `POST /meetings/{id}/feedback` |
| Anomaly detection | ✅ | `monitoring/anomaly.py` — rolling Z-score + hard thresholds |
| Few-shot + CoT prompts | ✅ | `prompts/templates.py` |
| Guardrails | ✅ | schema, hallucination, jailbreak, PII scrub |
| Jailbreak protection | ✅ | `guardrails.py` — regex pattern blocklist |
| PII masking | ✅ | `pipeline/pii.py` — email, phone, SSN, card, IP |
| Scalability (Celery) | ✅ | `pipeline/worker_task.py` |
| Token budget | ✅ | `CHUNK_TOKEN_BUDGET` in orchestrator |
| GDPR compliance | ✅ | `DELETE /meetings/{id}` |
| Source provenance | ✅ | `source_turn_ids` on every `ExtractedTask` |
| CI/CD | ✅ | `.github/workflows/ci.yml` |
| AutoML (Optuna) | ✅ | `train/finetune.py --search` |
| Hyperparameter search | ✅ | Optuna over rank, lr, batch_size |
| Automated retraining | ✅ | `train/retrain.py` — threshold check + Celery Beat (24h) |
| Evaluation harness | ✅ | `train/evaluate.py` — P/R/F1 |

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/architecture.md](docs/architecture.md) | Full system architecture (C4 levels 1–3) |
| [docs/gap-analysis.md](docs/gap-analysis.md) | Requirements coverage tracker |
| [docs/doc.md](docs/doc.md) | Project requirements & LLMOps scope |
| [docs/require.md](docs/require.md) | LLMOps requirement checklist |
| [docs/planing.md](docs/planing.md) | Implementation plan & phase gates |
| [docs/c4model.md](docs/c4model.md) | C4 modeling reference |
| [docs/mainflow.md](docs/mainflow.md) | High-level agent flow |
