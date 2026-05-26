# AI/ML CORE Architecture — Meeting AI Agent & Action Items Extraction

## Overview

This document defines the AI/ML CORE system architecture for the Meeting AI Agent project. The system converts meeting audio into structured, worker-assigned action items using a fully observable LLMOps pipeline.

---

## 1. System Context (C4 Level 1)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SYSTEM CONTEXT                               │
│                                                                     │
│  [Meeting Host]──uploads audio/video──►┌──────────────────────┐    │
│                                        │  Meeting AI Agent    │    │
│  [Team Member]──receives tasks────────►│  System              │    │
│                                        │                      │    │
│  [Admin/Ops]───monitors & retrain─────►│  (this system)       │    │
│                                        └──────┬───────────────┘    │
│                                               │                    │
│         ┌─────────────────┬──────────────────┤                     │
│         ▼                 ▼                  ▼                     │
│  [Calendar API]   [Email/Slack API]   [MLflow Registry]           │
│  (Google/Outlook) (notification sink) (model store)               │
└─────────────────────────────────────────────────────────────────────┘
```

**Actors:**
- **Meeting Host** — uploads audio/video file or streams live meeting
- **Team Member** — receives extracted action items via email/Slack
- **Admin/Ops Engineer** — monitors dashboards, triggers retraining, reviews quality

**External Systems:**
- Calendar API (Google Calendar, Outlook) — deadline cross-reference
- Notification sinks (Email SMTP, Slack webhook) — deliver action items
- MLflow Model Registry — version-controlled model artifacts
- Object Store (S3/GCS) — raw audio & transcript archival

---

## 2. Container Diagram (C4 Level 2)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                   MEETING AI AGENT SYSTEM                                │
│                                                                                          │
│  ┌─────────────┐   REST/S3    ┌──────────────────┐   gRPC/HTTP    ┌──────────────────┐  │
│  │  API Gateway│─────────────►│  Processing      │───────────────►│  LLM Inference   │  │
│  │  (FastAPI)  │◄─────────────│  Service         │◄───────────────│  Service         │  │
│  │             │  JSON result │  (Orchestrator)  │  prompt/output │  (llama.cpp /    │  │
│  └─────────────┘              └────────┬─────────┘                │   Ollama + Qwen) │  │
│         │                             │                           └──────────────────┘  │
│         │ webhook                     │ audio blob                                       │
│         ▼                             ▼                                                  │
│  ┌─────────────┐              ┌──────────────────┐   embeddings   ┌──────────────────┐  │
│  │  Notification│             │  ASR + Diarize   │───────────────►│  Vector Store    │  │
│  │  Service    │             │  Service          │                │  (FAISS / Chroma)│  │
│  │  (Email/    │             │  (WhisperX)       │                │  — speaker       │  │
│  │   Slack)    │             └──────────────────┘                │    profiles      │  │
│  └─────────────┘                                                  └──────────────────┘  │
│                                                                                          │
│  ┌─────────────┐              ┌──────────────────┐                ┌──────────────────┐  │
│  │  Data Store │             │  Observability   │                │  Training        │  │
│  │  (PostgreSQL│             │  Stack           │                │  Pipeline        │  │
│  │  + Redis    │             │  (Prometheus +   │                │  (LoRA / QLoRA   │  │
│  │  cache)     │             │   Grafana +      │                │   fine-tuning)   │  │
│  └─────────────┘             │   LangSmith)     │                └──────────────────┘  │
│                              └──────────────────┘                                       │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. AI/ML CORE — Component Diagram (C4 Level 3)

This is the **central focus**: the Processing Service + LLM Inference Service internals.

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│                         AI/ML CORE (Processing Service)                           │
│                                                                                   │
│  ┌──────────────┐    ┌───────────────┐    ┌──────────────────────────────────┐   │
│  │  Ingestion   │    │  Preprocessing│    │        STT + Diarization         │   │
│  │  Controller  │───►│  Module       │───►│  ┌──────────┐  ┌──────────────┐  │   │
│  │              │    │  - format     │    │  │ WhisperX │  │  Pyannote    │  │   │
│  │  (accepts    │    │    normalize  │    │  │ (ASR)    │  │  (Speaker    │  │   │
│  │  audio/video │    │  - noise      │    │  │          │  │   Diarize)   │  │   │
│  │  /transcript)│    │    reduction  │    │  └──────────┘  └──────────────┘  │   │
│  └──────────────┘    │  - chunking   │    │  output: TranscriptTurn[]        │   │
│                      └───────────────┘    └──────────────────────────────────┘   │
│                                                         │                         │
│                                                         ▼                         │
│  ┌──────────────────────────────────────────────────────────────────────────┐    │
│  │                     ORCHESTRATION ENGINE                                  │    │
│  │                                                                           │    │
│  │  ┌─────────────────┐   ┌──────────────────┐   ┌───────────────────────┐  │    │
│  │  │  Context        │   │  Prompt Builder  │   │  Model Router         │  │    │
│  │  │  Assembler      │──►│                  │──►│                       │  │    │
│  │  │                 │   │  - loads versioned│   │  - selects model      │  │    │
│  │  │  - injects      │   │    template      │   │    based on task      │  │    │
│  │  │    worker roster│   │  - few-shot      │   │    (summary vs task   │  │    │
│  │  │  - injects      │   │    examples      │   │    extraction)        │  │    │
│  │  │    meeting meta │   │  - CoT scaffold  │   │  - fallback logic     │  │    │
│  │  │  - RAG retrieval│   │  - token budget  │   │                       │  │    │
│  │  │    (speaker     │   │    enforcement   │   └──────────┬────────────┘  │    │
│  │  │    profiles)    │   └──────────────────┘              │               │    │
│  │  └─────────────────┘                                     │               │    │
│  │                                                          ▼               │    │
│  │                                            ┌─────────────────────────┐   │    │
│  │                                            │   LLM Inference Call    │   │    │
│  │                                            │   (Qwen 3.5B Q4_K_M     │   │    │
│  │                                            │    via Ollama)           │   │    │
│  │                                            └─────────────┬───────────┘   │    │
│  │                                                          │               │    │
│  │                                                          ▼               │    │
│  │  ┌─────────────────┐   ┌──────────────────┐   ┌────────────────────┐   │    │
│  │  │  Guardrail      │◄──│  Response        │◄──│  Raw LLM Output   │   │    │
│  │  │  Engine         │   │  Post-Processor  │   │                    │   │    │
│  │  │                 │   │                  │   └────────────────────┘   │    │
│  │  │  - JSON schema  │   │  - parse JSON    │                            │    │
│  │  │    validation   │   │  - fix mallformed│                            │    │
│  │  │  - hallucination│   │    output        │                            │    │
│  │  │    detector     │   │  - date          │                            │    │
│  │  │  - PII scrubber │   │    normalization │                            │    │
│  │  │  - retry logic  │   └──────────────────┘                            │    │
│  │  └────────┬────────┘                                                   │    │
│  │           │                                                             │    │
│  └───────────┼─────────────────────────────────────────────────────────────┘    │
│              │                                                                   │
│              ▼                                                                   │
│  ┌───────────────────────────────────────────────────────┐                      │
│  │              Task Assignment & Resolution              │                      │
│  │                                                        │                      │
│  │  ┌──────────────────┐   ┌──────────────────────────┐  │                      │
│  │  │  Worker Resolver  │   │  Confidence Scorer       │  │                      │
│  │  │                  │   │                          │  │                      │
│  │  │  1. exact name   │   │  - score each task       │  │                      │
│  │  │  2. alias match  │   │  - flag low-conf for     │  │                      │
│  │  │  3. role/skill   │   │    human review          │  │                      │
│  │  │     embedding    │   │  - unassigned queue      │  │                      │
│  │  │  4. unresolved   │   │    if score < 0.6        │  │                      │
│  │  └──────────────────┘   └──────────────────────────┘  │                      │
│  └───────────────────────────────────────────────────────┘                      │
│              │                                                                   │
│              ▼                                                                   │
│  ┌───────────────────┐                                                           │
│  │  Output Emitter   │ → ExtractedTask[] JSON persisted to PostgreSQL            │
│  │  + Metrics Logger │ → stage timings, token counts, confidence dist            │
│  └───────────────────┘   pushed to Prometheus                                   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Data Schemas (Canonical Contracts)

```python
# TranscriptTurn — output of STT+Diarization stage
{
  "turn_id": "uuid",
  "speaker_id": "SPEAKER_01",
  "speaker_name": "Alice Chen",       # resolved from roster
  "start_ms": 12300,
  "end_ms": 15800,
  "text": "We need to finish the API docs by Friday.",
  "confidence": 0.94
}

# ExtractedTask — output of LLM extraction stage
{
  "task_id": "uuid",
  "description": "Finish the API documentation",
  "assignee": "Alice Chen",
  "assignee_id": "worker_042",
  "due_date": "2026-04-18",           # ISO 8601
  "priority": "high",                 # low | medium | high | critical
  "source_turn_ids": ["uuid1"],       # provenance link
  "extraction_confidence": 0.87,
  "status": "open"                    # open | unresolved | human_review
}

# MeetingSummary — top-level output artifact
{
  "meeting_id": "uuid",
  "processed_at": "2026-04-12T10:00:00Z",
  "duration_ms": 3600000,
  "participants": ["Alice Chen", "Bob Kim"],
  "summary_text": "...",
  "action_items": [ExtractedTask, ...],
  "unresolved_items": [ExtractedTask, ...],
  "run_metrics": RunMetrics
}

# RunMetrics — observability payload
{
  "wer_estimate": 0.04,
  "diarization_error": 0.06,
  "total_tokens_used": 4200,
  "stage_latencies_ms": {
    "ingest": 120, "stt": 45000, "llm": 8200,
    "assignment": 340, "persist": 90
  },
  "hallucination_flags": 0,
  "tasks_extracted": 7,
  "tasks_unresolved": 1
}
```

---

## 5. Model Selection & Fine-Tuning Strategy

### 5.1 Model Stack

| Role | Model | Format | Runtime | Why |
|---|---|---|---|---|
| Speech-to-Text | **WhisperX large-v3** | FP16 | CUDA / CPU | State-of-art WER, word-level timestamps |
| Speaker Diarize | **Pyannote 3.1** | FP32 | CUDA / CPU | Best open-source DER, integrates with WhisperX |
| Action Extraction | **Qwen2.5-3B-Instruct** | GGUF Q4_K_M | Ollama / llama.cpp | Privacy-safe local inference, strong instruction following |
| Embeddings (RAG) | **nomic-embed-text** | GGUF | Ollama | Fast local embeddings for speaker profile retrieval |

### 5.2 Fine-Tuning Pipeline (LoRA / QLoRA)

```
┌─────────────────────────────────────────────────────────────────────┐
│                     FINE-TUNING PIPELINE                            │
│                                                                     │
│  Raw Meetings  ──►  Annotation Tool  ──►  Gold Dataset              │
│  (audio/text)       (label action          (JSONL format)           │
│                      items + owners)        ↓                       │
│                                       Data Validator                │
│                                       - bias check                  │
│                                       - leakage check               │
│                                       - schema conformance          │
│                                             ↓                       │
│                                       Train/Val/Test Split          │
│                                       (70 / 15 / 15)               │
│                                             ↓                       │
│                                       QLoRA Fine-Tune               │
│                                       (Unsloth + HF Trainer)        │
│                                       - rank=16, alpha=32           │
│                                       - target: q_proj, v_proj      │
│                                       - 4-bit NF4 base              │
│                                             ↓                       │
│                                       Eval Gate                     │
│                                       - precision ≥ 0.70 hard gate │
│                                       - F1 drop ≤ 0.05 vs baseline │
│                                       - hallucination delta ≤ 2pp   │
│                                             ↓                       │
│                                       Convert → GGUF Q4_K_M         │
│                                             ↓                       │
│                                       MLflow Registry               │
│                                       (model + adapter versioned)   │
└─────────────────────────────────────────────────────────────────────┘
```

**Training data sources:**
- Synthetic meetings from the packaged data-generation pipeline
- Public or permissioned meeting transcripts where licensing allows reuse
- Human-reviewed correction exports from the application feedback loop

**Techniques:**
- **QLoRA** (4-bit NF4 base + LoRA adapters) — resource-efficient fine-tuning
- **PEFT** via HuggingFace for adapter management
- Automatic model versioning in MLflow with eval metrics attached

---

## 6. Inference Optimization

```
┌────────────────────────────────────────────────────────────────┐
│                  INFERENCE OPTIMIZATION LAYERS                 │
│                                                                │
│  Layer 1 — Quantization                                        │
│    Qwen2.5-3B Q4_K_M GGUF  (4-bit, ~2GB VRAM)                │
│    WhisperX FP16            (half precision for GPU)           │
│                                                                │
│  Layer 2 — Caching                                             │
│    Redis  — prompt cache keyed on (meeting_id + chunk_hash)   │
│    FAISS  — speaker embedding index for roster RAG             │
│    Disk   — WhisperX model weights cached between runs         │
│                                                                │
│  Layer 3 — Batching                                            │
│    Transcript chunked into ≤ 3000-token segments               │
│    Parallel LLM calls per chunk (asyncio + thread pool)        │
│    WhisperX batch decode (beam=5, batch_size=16)               │
│                                                                │
│  Layer 4 — Token Budget Enforcement                            │
│    Prompt Builder enforces max_prompt_tokens = 2048            │
│    Summary truncation before action-item prompt                │
│    System prompt compressed via prompt compression technique   │
└────────────────────────────────────────────────────────────────┘
```

---

## 7. Prompt Engineering & Guardrails

### 7.1 Prompt Template (Action Item Extraction)

```
SYSTEM:
You are a meeting analyst. Extract ALL action items from the transcript segment.
Output ONLY valid JSON matching the schema. Do not invent tasks not stated in the text.

WORKER ROSTER (use exact names only):
{{ roster_json }}

SCHEMA:
{{ json_schema }}

FEW-SHOT EXAMPLES:
[Transcript]: "Bob, can you send the report to the client by Thursday?"
[Output]: {"description": "Send report to client", "assignee": "Bob Kim", "due_date": "2026-04-17", "priority": "medium"}

[Transcript]: "We should look into caching later sometime."
[Output]: {"description": "Investigate caching strategy", "assignee": null, "due_date": null, "priority": "low"}

MEETING METADATA:
Date: {{ meeting_date }}
Participants: {{ participant_list }}

TRANSCRIPT SEGMENT:
{{ transcript_chunk }}

OUTPUT JSON ARRAY:
```

### 7.2 Guardrail Engine

```
┌────────────────────────────────────────────────┐
│              GUARDRAIL ENGINE                  │
│                                                │
│  Input Guardrails (pre-LLM)                    │
│  ├── PII detector (names/emails masked in logs)│
│  ├── Audio length check (max 4 hours)          │
│  └── Roster validation (non-empty check)       │
│                                                │
│  Output Guardrails (post-LLM)                  │
│  ├── JSON schema validation (Pydantic v2)      │
│  ├── Assignee whitelist check (roster only)    │
│  ├── Date sanity check (not in past > 1 year)  │
│  ├── Hallucination detector                    │
│  │    — cross-reference claim vs transcript    │
│  │    — flag if assignee not in transcript     │
│  ├── Retry with stricter prompt on failure     │
│  │    (max 3 retries)                          │
│  └── Fallback to "unresolved" status on        │
│       persistent failure                       │
└────────────────────────────────────────────────┘
```

---

## 8. Monitoring & Observability Stack

```
┌───────────────────────────────────────────────────────────────────┐
│                   OBSERVABILITY STACK                             │
│                                                                   │
│  ┌─────────────────┐   ┌──────────────────┐   ┌───────────────┐  │
│  │   LangSmith     │   │   Prometheus     │   │   Grafana     │  │
│  │                 │   │                  │   │               │  │
│  │  - full prompt/ │   │  - stage latency │   │  - throughput │  │
│  │    response log │   │  - token count   │   │    dashboard  │  │
│  │  - trace per    │   │  - error rate    │   │  - quality    │  │
│  │    meeting run  │   │  - hallucination │   │    drift view │  │
│  │  - eval scores  │   │    rate          │   │  - cost view  │  │
│  │    per run      │   │  - WER / DER     │   │  - alert      │  │
│  │  - feedback     │   │  - confidence    │   │    panels     │  │
│  │    annotations  │   │    distribution  │   │               │  │
│  └─────────────────┘   └──────────────────┘   └───────────────┘  │
│                                                                   │
│  Alert Rules (Prometheus → PagerDuty / Slack):                    │
│  - hallucination_rate > baseline + 0.02 → P2 alert                │
│  - task_precision < 0.70 → P2 alert                              │
│  - task_f1 drops > 0.05 vs baseline → P2 alert                   │
│  - p95_e2e_latency > 120s (per hour of audio) → P3 warning       │
│  - error_rate > 0.01 → P2 alert                                   │
│                                                                   │
│  Feedback Loop:                                                   │
│  User corrections → annotated dataset → nightly retrain trigger  │
└───────────────────────────────────────────────────────────────────┘
```

### Key Metrics Tracked

| Metric | Target | Tool |
|---|---|---|
| Word Error Rate (WER) | ≤ 5% | internal eval |
| Diarization Error Rate (DER) | ≤ 8% | pyannote eval |
| Task Extraction Precision | ≥ 0.70 hard gate | benchmark runner |
| Task Extraction Recall | watch metric, current baseline 0.6665 | benchmark runner |
| Task Extraction F1 | no >0.05 drop vs baseline; current baseline 0.6886 | benchmark runner |
| Hallucination Rate | no >2pp regression vs baseline | LangSmith + guardrail |
| Schema Validity Rate | 100% | Pydantic validation |
| E2E Latency P95 (1h meeting) | ≤ 120s | Prometheus |
| Token Cost per Meeting | minimize | Prometheus |

---

## 9. Data Management Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│                   DATA MANAGEMENT PIPELINE                       │
│                                                                  │
│  Collection                                                      │
│  ├── Real meetings (user uploads, anonymized)                    │
│  ├── AMI Corpus (public labeled meeting dataset)                 │
│  └── Synthetic generation (scripts → transcripts → audio TTS)    │
│                                                                  │
│  Preprocessing                                                   │
│  ├── Audio normalization (ffmpeg, 16kHz mono WAV)                │
│  ├── Noise reduction (noisereduce library)                       │
│  ├── PII redaction before annotation storage                     │
│  └── Format standardization → TranscriptTurn JSONL              │
│                                                                  │
│  Validation                                                      │
│  ├── Schema conformance check (100% pass required)               │
│  ├── Bias audit (speaker balance, topic diversity)               │
│  ├── Leakage check (test speakers not in train)                  │
│  └── Annotation agreement (Cohen's κ ≥ 0.75 for dual-annotated) │
│                                                                  │
│  Storage                                                         │
│  ├── Raw audio → S3/GCS (encrypted at rest)                      │
│  ├── Transcripts → PostgreSQL (structured, queryable)            │
│  ├── Embeddings → FAISS index (speaker profiles)                 │
│  └── Training data → versioned DVC dataset                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 10. CI/CD & Continuous Improvement Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                    CI/CD PIPELINE (GitHub Actions)                   │
│                                                                      │
│  PR Trigger                                                          │
│  └── lint (ruff) → unit tests → schema smoke → eval smoke            │
│      → Docker build check                                            │
│                                                                      │
│  Nightly Trigger                                                     │
│  └── full eval harness on gold set → quality report posted to Slack  │
│      → if regression detected → create issue + block next deploy     │
│                                                                      │
│  Model Retrain Trigger (weekly or on feedback threshold)             │
│  └── fetch new annotated corrections → merge with training set       │
│      → QLoRA fine-tune → eval gate → if pass: push to MLflow        │
│      → canary deploy (10% traffic) → monitor 24h → full rollout     │
│      → if fail: auto-rollback to previous version                    │
│                                                                      │
│  Release Pipeline                                                    │
│  └── Docker build → push to registry → helm chart update            │
│      → staging deploy → integration tests → prod deploy (blue-green) │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 11. Scalability & Cost Optimization

| Concern | Strategy |
|---|---|
| **Hardware** | Single GPU node (RTX 3090 / A10) for local; AWS g4dn.xlarge for cloud |
| **Batch processing** | Async job queue (Celery + Redis) — meetings processed concurrently |
| **Model sharding** | Not needed at 3B scale; revisit if upgrading to 7B+ |
| **Token reduction** | Chunk transcripts, summarize non-task segments first, then extract |
| **Caching** | Redis prompt cache prevents re-processing repeated roster + same chunk |
| **Request throttling** | Rate limit API at 10 concurrent jobs; queue overflow to waiting state |
| **Cost tracking** | Token counter per meeting exposed in RunMetrics, alert if > threshold |

---

## 12. Ethics & Compliance

| Requirement | Implementation |
|---|---|
| **GDPR / CCPA** | PII masked in all logs; audio deleted after processing if configured; opt-in data retention |
| **Data minimization** | Only transcript text stored, not raw audio by default |
| **Bias detection** | Eval harness checks task assignment equity across speaker gender/role |
| **Explainability** | Source turn IDs attached to every extracted task (provenance) |
| **Human-in-the-loop** | Low-confidence tasks routed to human review queue before delivery |
| **Audit trail** | All LLM calls logged to LangSmith with full prompt+response for 90 days |
| **Jailbreak robustness** | System prompt pinned; user-supplied names sanitized before injection |

---

## 13. Dynamic Diagram — Primary Flow (Batch Meeting Processing)

```
Meeting Host          API Gateway      Processing Service     LLM Inference     Notification
     │                    │                   │                    │                  │
     │──POST /meetings────►│                   │                    │                  │
     │  (audio file)       │                   │                    │                  │
     │                     │──validate & store►│                    │                  │
     │                     │◄──job_id──────────│                    │                  │
     │◄──202 Accepted──────│                   │                    │                  │
     │                     │              [async pipeline starts]   │                  │
     │                     │                   │──WhisperX─────────►│(ASR+Diarize)     │
     │                     │                   │◄──TranscriptTurns──│                  │
     │                     │                   │──chunk + build prompt                 │
     │                     │                   │──────────────────────►Qwen inference  │
     │                     │                   │◄──────────────────────raw JSON output │
     │                     │                   │──guardrail + validate                 │
     │                     │                   │──assign workers                       │
     │                     │                   │──persist to PostgreSQL                │
     │                     │                   │──emit metrics → Prometheus            │
     │                     │                   │──────────────────────────────────────►│
     │                     │                   │              send email/Slack tasks   │
     │──GET /meetings/{id}─►│                   │                    │                  │
     │◄──MeetingSummary JSON│                   │                    │                  │
```

---

## 14. Deployment Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                      PRODUCTION ENVIRONMENT                          │
│                        (Docker Compose / K8s)                        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                        App Cluster                          │    │
│  │                                                             │    │
│  │  [api-gateway]     [worker-1]      [worker-2]              │    │
│  │  FastAPI:8000       Celery worker   Celery worker           │    │
│  │  2 CPU / 4GB RAM    1 GPU / 16GB    1 GPU / 16GB           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                      Data Cluster                           │    │
│  │  [postgres:5432]   [redis:6379]   [ollama:11434]            │    │
│  │  4 CPU / 16GB       2 CPU / 8GB    GPU node                 │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   Observability Cluster                     │    │
│  │  [prometheus:9090]  [grafana:3000]  [langsmith-proxy]       │    │
│  │  2 CPU / 4GB         1 CPU / 2GB     1 CPU / 2GB            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Secrets: env vars from .env / K8s Secret                           │
│  Storage: S3-compatible (MinIO local, GCS/S3 cloud)                 │
│  Model artifacts: mounted volume from MLflow artifact store          │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 15. Technology Summary

| Layer | Technology | Version / Notes |
|---|---|---|
| ASR | WhisperX | large-v3, word timestamps |
| Speaker Diarization | Pyannote | 3.1 |
| LLM | Qwen2.5-3B-Instruct | GGUF Q4_K_M |
| LLM Runtime | Ollama | local, no data leaves machine |
| Embeddings | nomic-embed-text | via Ollama |
| Vector Store | FAISS | in-process, speaker profiles |
| Fine-tuning | Unsloth + PEFT | QLoRA, rank=16 |
| API | FastAPI | async, Pydantic v2 schemas |
| Task Queue | Celery + Redis | async job processing |
| Cache | Redis | prompt & transcript chunk cache |
| Database | PostgreSQL | meetings, tasks, workers |
| Model Registry | MLflow | model + adapter versioning |
| Data Versioning | DVC | dataset lineage |
| Monitoring | Prometheus + Grafana | metrics & dashboards |
| LLM Tracing | LangSmith | prompt/response logs, eval |
| Guardrails | Pydantic v2 + custom | schema + hallucination check |
| CI/CD | GitHub Actions | lint, test, eval, deploy |
| Containers | Docker + Compose | dev; Helm for prod K8s |
| Compliance | PII masker + audit log | GDPR-aligned |
