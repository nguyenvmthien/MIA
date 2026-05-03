# Meeting AI Agent — Hiểu toàn bộ project

> Tài liệu này giải thích từng thành phần, luồng xử lý, và lý do thiết kế của toàn bộ hệ thống. Đọc từ đầu đến cuối nếu bạn mới vào project.

---

## 1. Mục tiêu

Người dùng upload file ghi âm cuộc họp (mp3/wav/m4a/...) → hệ thống tự động:
1. Chuyển âm thanh thành văn bản, biết ai nói gì
2. Dùng LLM đọc transcript và trích xuất các action items (việc cần làm, ai làm, deadline)
3. Cho người dùng review và chỉnh sửa
4. Tự động tạo Google Calendar events
5. Lưu lại những chỉnh sửa để tự cải thiện mô hình về sau

---

## 2. Kiến trúc tổng quan

```
┌─────────────────────────────────────────────────────────────────┐
│                         USER BROWSER                            │
│                    (Next.js — web/)                             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP/REST
┌───────────────────────────▼─────────────────────────────────────┐
│                      FastAPI (port 8000)                        │
│              src/meeting_agent/api/main.py                      │
│  POST /meetings  │  GET /meetings/{id}  │  POST /feedback       │
└──────┬───────────────────────────────────────────────┬──────────┘
       │ Celery task dispatch                          │ DB reads/writes
       │ (Redis broker)                                │
┌──────▼──────────────────┐              ┌─────────────▼──────────┐
│    Celery Worker        │              │     PostgreSQL          │
│  pipeline/worker_task   │              │  meetings / tasks /    │
│                         │              │  feedback_corrections  │
│  run_pipeline()         │              └────────────────────────┘
│    │ ingest              │
│    │ preprocess (ffmpeg) │              ┌────────────────────────┐
│    │ STT (WhisperX)      │              │        Redis           │
│    │ diarize (Pyannote)  │◄─────────────│  Celery broker+backend │
│    │ LLM (Ollama/Qwen)   │              │  Prompt cache          │
│    │ guardrails          │              └────────────────────────┘
│    │ assignment          │
│    └─► upsert DB         │              ┌────────────────────────┐
└─────────────────────────┘              │   Ollama (port 11434)  │
                                         │   Qwen2.5-3B (local)   │
                                         └────────────────────────┘
```

---

## 3. Tại sao lại dùng Celery (xử lý bất đồng bộ)?

Xử lý một file audio mất **vài phút** (WhisperX transcribe + LLM inference). Nếu làm thẳng trong HTTP request, browser sẽ timeout sau 30-60 giây.

Giải pháp: API nhận upload → trả về `meeting_id` ngay lập tức → Celery worker xử lý ngầm → frontend poll `GET /meetings/{id}` mỗi 3 giây cho đến khi xong.

```
Browser                API                  Redis           Worker
  │── POST /meetings ──►│                     │               │
  │◄── {meeting_id} ────│── enqueue task ────►│               │
  │                     │                     │── pick up ───►│
  │── GET /meetings/id ─►│── check Redis ─────►│               │
  │◄── {status:pending}─│                     │    ...running │
  │── GET /meetings/id ─►│── check Redis ─────►│               │
  │◄── {status:processing}                    │    ...running │
  │── GET /meetings/id ─►│── read PostgreSQL ──────────────────│ (done)
  │◄── {action_items:[]}─│                                     │
```

---

## 4. Pipeline xử lý chi tiết (6 stages)

File: `src/meeting_agent/pipeline/run.py`

### Stage 1 — Ingest
- Validate file audio (format, size, duration tối đa 4h)
- Copy vào `data/audio/{meeting_id}/upload.wav`

### Stage 2 — Preprocess
- Dùng **ffmpeg** convert sang 16kHz mono WAV (định dạng WhisperX cần)
- Noise reduction bằng `noisereduce`

### Stage 3 — STT + Diarization
- **WhisperX** transcribe toàn bộ audio → văn bản có timestamp từng từ
- **Pyannote** diarization → biết "đoạn này là Speaker_0 nói, đoạn kia là Speaker_1 nói"
- Kết hợp 2 kết quả → list `TranscriptTurn` (ai nói gì, từ giây nào đến giây nào)

```python
# Ví dụ TranscriptTurn
{
  "turn_id": "t_001",
  "display_name": "Alice",   # từ RAG speaker matching
  "text": "We need to finish the report by Friday",
  "start": 12.3,
  "end": 15.8
}
```

### Stage 4 — LLM (Orchestrator)
File: `src/meeting_agent/pipeline/orchestrator.py`

**Hai tác vụ song song:**

**4a. Summarize:** Gửi toàn bộ transcript → LLM tóm tắt cuộc họp 1 đoạn văn.

**4b. Extract action items:** Đây là phần phức tạp nhất.

Vấn đề: transcript dài hàng nghìn từ, không vừa context window của LLM. Giải pháp: **chunking** — chia transcript thành các chunk ~2000 token, gọi LLM từng chunk.

Với mỗi chunk:
1. **RAG** (FAISS speaker index): tìm các đoạn hội thoại liên quan trong quá khứ để bổ sung context
2. Gọi LLM với prompt few-shot Chain-of-Thought
3. **Redis cache**: nếu prompt giống hệt đã gọi trước → trả cache ngay, không gọi Ollama
4. LLM trả về JSON array các tasks
5. **Guardrails** validate output

Prompt được thiết kế trong `src/meeting_agent/prompts/templates.py` với few-shot examples thực tế.

### Stage 5 — Guardrails
File: `src/meeting_agent/pipeline/guardrails.py`

Mỗi task từ LLM đi qua chuỗi kiểm tra:

| Kiểm tra | Mô tả |
|---------|-------|
| **Jailbreak detection** | Regex patterns phát hiện prompt injection trong transcript (ví dụ: "ignore previous instructions") |
| **PII masking** | Che số điện thoại, email, CMND trong log |
| **Schema validation** | Pydantic validate JSON output có đúng format không |
| **Assignee whitelist** | Tên người được assign phải có trong roster |
| **Due date sanity** | Loại bỏ ngày > 1 năm trước hoặc > 5 năm tương lai (likely hallucinated) |
| **Hallucination detection** | Nếu LLM assign cho Alice nhưng transcript không có tên Alice → flag `human_review` |

Kết quả: mỗi task có status `open` / `unresolved` / `human_review`.

### Stage 6 — Assignment & Confidence Scoring
File: `src/meeting_agent/pipeline/assignment.py`

- Guardrails đã làm exact match; Assignment làm **fuzzy match** (SequenceMatcher ≥ 80%) cho các task còn `unresolved`
- Tính **confidence score** (0–1) dựa trên: có assignee không, có due date không, status là gì
- Task có confidence < `task_confidence_threshold` (default 0.6) → escalate lên `human_review`

---

## 5. Database layer

### Tại sao cần PostgreSQL? Redis không đủ sao?

Redis chỉ lưu Celery task result theo TTL ngắn. Nếu Redis restart hoặc TTL hết → kết quả mất. PostgreSQL là **storage vĩnh viễn**.

### Schema (3 bảng)

```sql
meetings              -- 1 row mỗi meeting
  id, status, audio_filename, created_at, processed_at,
  participants, summary_text, run_metrics, error

tasks                 -- N rows mỗi meeting (action items)
  meeting_id (FK), task_id, description, assignee, assignee_id,
  due_date, priority, status, extraction_confidence, bucket
  -- bucket: "action" | "unresolved" | "human_review"

feedback_corrections  -- corrections từ user
  meeting_id (FK), task_id, reviewer,
  original_description, corrected_description,
  original_assignee, corrected_assignee,
  original_due_date, corrected_due_date,
  is_false_positive, is_missing, submitted_at
```

### Lifecycle của một meeting trong DB

```
API nhận upload
  └─► INSERT meetings (status="pending")

Celery worker hoàn thành
  └─► UPSERT meetings (status="completed") + INSERT tasks

User review + confirm
  └─► INSERT feedback_corrections (implicit diff từ frontend)

GET /meetings/{id}
  └─► Nếu còn đang chạy → đọc Redis (live status)
  └─► Nếu đã xong → đọc PostgreSQL (canonical, permanent)
```

### Migrations với Alembic

Alembic quản lý schema versioning. Mỗi thay đổi schema → một file migration trong `alembic/versions/`.

```bash
alembic upgrade head    # apply tất cả migrations chưa chạy
alembic downgrade -1    # rollback migration gần nhất
alembic current         # xem DB đang ở version nào
```

Khi API boot lần đầu, `ensure_tables()` cũng tự tạo tables (idempotent fallback cho dev).

---

## 6. Feedback loop & continuous learning

Đây là điểm đặc biệt nhất của project — hệ thống **tự cải thiện**.

### Feedback được thu thập như thế nào?

**Implicit feedback** (tự động, không cần user làm gì thêm):
- User edit description của task → ghi nhận `original_description` vs `corrected_description`
- User bỏ chọn task (deselect) → ghi nhận `is_false_positive=True` (LLM extract nhầm)

**Explicit feedback** (qua API):
- `POST /meetings/{id}/feedback` với body `FeedbackSubmission`
- Hỗ trợ cả `is_missing=True` (LLM bỏ sót task)

### Feedback được lưu ở đâu?

Dual-write:
1. **PostgreSQL** `feedback_corrections` — primary, queryable, indexed
2. **JSONL file** `data/transcripts/_feedback.jsonl` — backup, đọc bởi training scripts

### Khi nào retrain?

Celery Beat chạy task `check_retrain_task` **mỗi 24 giờ**:

```
Đếm corrections mới từ lần retrain trước
  │
  ├─ < 50 corrections → skip
  │
  └─ ≥ 50 corrections → bắt đầu retrain:
       1. Export corrections → JSONL training examples
       2. Validate data (schema, bias check)
       3. Run finetune.py (QLoRA với Unsloth, log vào MLflow)
       4. Eval mô hình mới vs champion (precision ≥ 0.70, F1 không giảm > 5%)
       5. Nếu pass → promote lên Production trong MLflow
```

---

## 7. Monitoring & Observability

### Prometheus metrics (exposed tại `/metrics`)

| Metric | Ý nghĩa |
|--------|---------|
| `meeting_jobs_total{status}` | Tổng jobs hoàn thành / thất bại |
| `meeting_jobs_in_flight` | Số jobs đang chạy (Gauge) |
| `meeting_stage_duration_seconds{stage}` | Latency từng stage pipeline |
| `meeting_llm_tokens_total` | Tổng tokens LLM tiêu thụ |
| `meeting_hallucination_flags_total{reason}` | Số lần phát hiện hallucination |
| `meeting_schema_failures_total` | Số lần LLM output sai format |
| `meeting_feedback_submitted_total{type}` | Corrections từ user |
| `meeting_tasks_per_meeting` | Distribution số tasks mỗi meeting |
| `meeting_rag_queries_total{result}` | RAG hit/miss ratio |
| `meeting_anomaly_events_total{metric}` | Anomalies phát hiện |

### Anomaly Detection

File: `src/meeting_agent/monitoring/anomaly.py`

Sau mỗi meeting, hệ thống kiểm tra:
- **Hard threshold**: hallucination_rate > 10% → alert ngay
- **Statistical outlier**: Z-score > 3σ so với rolling window 20 jobs → alert

### LangSmith Tracing (optional)

Nếu set `LANGCHAIN_TRACING_V2=true` và `LANGCHAIN_API_KEY`, mọi LLM call được trace với full prompt/response trên LangSmith dashboard.

---

## 8. Các services trong Docker Compose

| Service | Port | Vai trò |
|---------|------|---------|
| `postgres` | 5432 | Database chính |
| `redis` | 6379 | Celery broker + result backend + prompt cache |
| `ollama` | 11434 | Chạy Qwen2.5-3B local, không cần API key |
| `api` | 8000 | FastAPI — nhận upload, serve kết quả |
| `worker` | — | Celery worker — chạy pipeline |
| `ui` | 8501 | Streamlit UI (legacy) |
| `pgadmin` | 5050 | GUI quản lý PostgreSQL |
| `prometheus` | 9090 | Thu thập metrics |
| `grafana` | 3000 | Dashboard metrics |

Web UI mới (Next.js) chạy riêng ở `web/` trên port 3000 (dev) hoặc deploy Vercel.

---

## 9. Cấu trúc thư mục

```
MEETING-AGENT/
├── src/meeting_agent/
│   ├── api/
│   │   ├── main.py              # FastAPI app, tất cả endpoints
│   │   ├── calendar_router.py   # Google Calendar sync endpoints
│   │   └── ws_router.py         # WebSocket (streaming STT)
│   ├── db/
│   │   ├── engine.py            # SQLAlchemy engine + session factory
│   │   ├── models.py            # ORM models (Meeting, Task, FeedbackCorrection)
│   │   └── repository.py        # Tất cả DB operations
│   ├── pipeline/
│   │   ├── run.py               # Wires 6 stages thành 1 job
│   │   ├── ingest.py            # Stage 1: validate & store
│   │   ├── preprocess.py        # Stage 2: ffmpeg + noise reduction
│   │   ├── stt.py               # Stage 3: WhisperX + Pyannote
│   │   ├── orchestrator.py      # Stage 4: LLM calls + RAG + cache
│   │   ├── guardrails.py        # Stage 4b: validate LLM output
│   │   ├── assignment.py        # Stage 5: fuzzy match + confidence
│   │   ├── feedback.py          # Lưu corrections (DB + JSONL)
│   │   ├── worker_task.py       # Celery task definitions + Beat schedule
│   │   ├── rag.py               # FAISS speaker index
│   │   ├── cache.py             # Redis prompt cache
│   │   ├── pii.py               # PII masking
│   │   └── router.py            # Multi-Ollama load balancer
│   ├── monitoring/
│   │   ├── metrics.py           # Tất cả Prometheus counters/histograms
│   │   └── anomaly.py           # Rolling Z-score anomaly detection
│   ├── schemas/
│   │   ├── meeting.py           # MeetingSummary, RunMetrics, JobStatus
│   │   ├── task.py              # ExtractedTask, TaskPriority, TaskStatus
│   │   ├── transcript.py        # TranscriptTurn
│   │   └── worker.py            # Worker, WorkerRoster
│   ├── prompts/
│   │   └── templates.py         # Few-shot CoT prompt templates
│   ├── integrations/
│   │   └── google_calendar.py   # Google Calendar API client
│   └── config.py                # Pydantic settings (đọc từ .env)
├── train/
│   ├── finetune.py              # QLoRA fine-tuning (Unsloth + MLflow)
│   ├── retrain.py               # Automated retrain pipeline
│   ├── evaluate.py              # Precision/recall/F1 eval harness
│   ├── distill.py               # Knowledge distillation 3B→1.5B
│   └── drift_detector.py        # PSI drift detection
├── data_pipeline/
│   ├── collect.py               # Build JSONL từ audio dirs
│   ├── synthetic.py             # Generate synthetic meeting data bằng LLM
│   └── validate.py              # Schema + bias + leakage check
├── alembic/                     # DB migrations
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
├── web/                         # Next.js frontend
├── docker-compose.yml
└── pyproject.toml
```

---

## 10. Cấu hình (.env)

| Biến | Default | Bắt buộc |
|------|---------|----------|
| `HF_TOKEN` | — | ✅ (Pyannote diarization) |
| `DATABASE_URL` | `postgresql://meeting:meeting@localhost:5432/meeting_agent` | ✅ |
| `REDIS_URL` | `redis://localhost:6379/0` | ✅ |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | ✅ |
| `OLLAMA_LLM_MODEL` | `qwen2.5:3b` | |
| `WHISPER_MODEL` | `base` | |
| `LANGCHAIN_API_KEY` | — | Nếu muốn LangSmith tracing |
| `RETRAIN_MIN_CORRECTIONS` | `50` | |

---

## 11. Các điểm dễ nhầm

**Q: Kết quả meeting lưu ở Redis hay PostgreSQL?**
A: Cả hai. Redis lưu tạm trong lúc job chạy. PostgreSQL lưu vĩnh viễn sau khi xong. `GET /meetings/{id}` đọc Redis nếu job còn chạy, đọc PostgreSQL nếu đã hoàn thành.

**Q: `ensure_tables()` vs `alembic upgrade head` khác nhau thế nào?**
A: `ensure_tables()` (SQLAlchemy `create_all`) chỉ tạo table nếu chưa có — không thể thêm cột vào table đang tồn tại. `alembic upgrade` xử lý được incremental changes. Dùng Alembic cho production, `ensure_tables()` là fallback cho dev.

**Q: Tại sao feedback lưu 2 chỗ (DB + JSONL)?**
A: JSONL là format training scripts (`retrain.py`) đang dùng. DB là primary storage để query/stats. Khi DB unavailable, fallback về JSONL. Về lâu dài sẽ migrate hoàn toàn sang DB.

**Q: Ollama và Celery worker có cần cùng máy không?**
A: Không nhất thiết. `OLLAMA_BASE_URL` là URL có thể trỏ sang máy khác. Worker và Ollama chỉ cần network connectivity.
