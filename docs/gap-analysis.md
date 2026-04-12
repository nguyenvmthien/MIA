# Requirements Gap Analysis

Last updated: 2026-04-12

---

## Status Legend
- ✅ Fully implemented
- 🔧 Wired in config/deps but code hollow → being fixed
- 🆕 Not yet implemented → being implemented
- 📄 Design-level only (documented, not coded — acceptable for this project scale)

---

## 1. Model Selection & Fine-Tuning

| Sub-requirement | Status | Location |
|---|---|---|
| Choose right LLM architecture | ✅ | `config.py` — WhisperX + Qwen2.5-3B |
| Fine-tuning strategies (LoRA, QLoRA) | 🆕→✅ | `train/finetune.py` |
| Efficient training (PEFT, QLoRA) | 🆕→✅ | `train/finetune.py` + Unsloth |
| Model versioning system | 🆕→✅ | `train/finetune.py` — MLflow `log_model` |

## 2. Data Management & Preprocessing

| Sub-requirement | Status | Location |
|---|---|---|
| Structured data collection pipeline | 🆕→✅ | `data_pipeline/collect.py` |
| Data validation (bias/leakage) | 🆕→✅ | `data_pipeline/validate.py` |
| Regular dataset updates | 🆕→✅ | feedback loop → `pipeline/feedback.py` |
| Synthetic data generation | 🆕→✅ | `data_pipeline/synthetic.py` |

## 3. Model Deployment & Inference Optimization

| Sub-requirement | Status | Location |
|---|---|---|
| Right inference framework | ✅ | Ollama (`orchestrator.py`) |
| Quantization (GGUF Q4_K_M) | ✅ | `config.py`, Ollama |
| Distillation / pruning | 🆕→✅ | `train/distill.py` — KD teacher→student (3B→1.5B) + magnitude LoRA pruning |
| Docker / containerized deploy | ✅ | `Dockerfile`, `docker-compose.yml` |
| Caching (Redis prompt cache) | 🔧→✅ | `pipeline/cache.py` + wired into `orchestrator.py` |
| Caching (FAISS speaker RAG) | 🔧→✅ | `pipeline/rag.py` + wired into `orchestrator.py` |

## 4. Monitoring & Observability

| Sub-requirement | Status | Location |
|---|---|---|
| Log predictions & track metrics | ✅ | `monitoring/metrics.py`, Prometheus |
| Real-time monitoring (Prometheus + Grafana) | ✅ | `docker-compose.yml` |
| LangSmith tracing | 🔧→✅ | `orchestrator.py` — `@traceable` |
| Feedback loops | 🆕→✅ | `pipeline/feedback.py`, `POST /meetings/{id}/feedback` |
| Anomaly detection | 🆕→✅ | `monitoring/anomaly.py` |

## 5. Prompt Engineering & Guardrails

| Sub-requirement | Status | Location |
|---|---|---|
| Few-shot + CoT prompts | ✅ | `prompts/templates.py` |
| RAG / embeddings | 🔧→✅ | `pipeline/rag.py` |
| Guardrails (schema, hallucination) | ✅ | `guardrails.py` |
| PII masking | 🔧→✅ | `pipeline/pii.py` + wired into `guardrails.py` |
| Jailbreak / injection protection | 🆕→✅ | `guardrails.py` — input sanitizer |

## 6. Scalability & Cost Optimization

| Sub-requirement | Status | Location |
|---|---|---|
| Hardware choice | ✅ | Documented; local GPU or CPU |
| Batch processing | ✅ | `orchestrator.py` chunking, Celery |
| Request throttling | ✅ | Celery concurrency limit |
| Token reduction | ✅ | `CHUNK_TOKEN_BUDGET` in `orchestrator.py` |
| Model sharding / distributed inference | 🆕→✅ | `pipeline/router.py` — multi-Ollama load balancer with health checks |

## 7. Ethics & Compliance

| Sub-requirement | Status | Location |
|---|---|---|
| GDPR compliance | ✅ | `DELETE /meetings/{id}` in `api/main.py` |
| PII masking | 🔧→✅ | `pipeline/pii.py` |
| Fairness / bias detection | 🆕→✅ | `data_pipeline/validate.py` — speaker equity check |
| Audit trail | 🆕→✅ | LangSmith traces + `monitoring/anomaly.py` |
| Explainability (provenance) | ✅ | `source_turn_ids` on every `ExtractedTask` |

## 8. Continuous Improvement & Automation

| Sub-requirement | Status | Location |
|---|---|---|
| CI/CD pipeline | 🆕→✅ | `.github/workflows/ci.yml` |
| Feedback loop → retrain | 🆕→✅ | `pipeline/feedback.py` |
| Regular retraining schedule | 🆕→✅ | `train/retrain.py` — feedback threshold check + Celery Beat + `POST /admin/retrain` |
| AutoML / hyperparameter search | ✅ | `train/finetune.py --search` — Optuna over rank/lr/batch |
| Architecture experiments | ✅ | MLflow experiment tracking in `train/finetune.py` |

---

## All Implementation Files

```
src/meeting_agent/
  pipeline/
    ingest.py        Stage 1 — validate & store audio
    preprocess.py    Stage 2 — ffmpeg + noise reduction
    stt.py           Stage 3 — WhisperX + Pyannote diarization
    rag.py           FAISS speaker profile RAG (NEW)
    orchestrator.py  Stage 4 — LLM calls, LangSmith tracing, Redis cache (UPDATED)
    guardrails.py    Schema, hallucination, jailbreak, PII (UPDATED)
    pii.py           PII regex masker (NEW)
    cache.py         Redis prompt cache wrapper (NEW)
    router.py        Multi-Ollama load balancer / distributed inference (NEW)
    assignment.py    Stage 5 — worker resolution + confidence scoring
    feedback.py      User correction storage + feedback loop (NEW)
    run.py           End-to-end pipeline runner (UPDATED — anomaly check)
    worker_task.py   Celery async task + Beat schedule (UPDATED)
  monitoring/
    metrics.py       Prometheus counters & histograms
    anomaly.py       Rolling Z-score anomaly detector (NEW)
  api/main.py        FastAPI (UPDATED — feedback, retrain, router-stats endpoints)
train/
  finetune.py        QLoRA fine-tuning (Unsloth + MLflow + Optuna)
  dataset.py         Dataset loading and instruction formatting
  evaluate.py        Precision / Recall / F1 evaluation harness
  distill.py         Knowledge distillation (3B→1.5B) + LoRA pruning (NEW)
  retrain.py         Automated retraining scheduler (NEW)
data_pipeline/
  collect.py         Audio dir → JSONL training data
  validate.py        Bias, leakage, schema, duplicate checks
  synthetic.py       LLM-generated synthetic meeting data
.github/
  workflows/
    ci.yml           Lint → unit → schema smoke → eval smoke → docker build
```
