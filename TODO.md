# Meeting Agent - TODO & MLOps Roadmap

> Cap nhat: 2026-05-23. Full pipeline chay duoc (upload audio -> STT/diarization -> LLM extract -> DB -> feedback -> calendar sync).
> Da xoa: Streamlit UI, CLI mode, streaming STT (WebSocket), nginx reverse proxy.
> Stack hien tai: FastAPI (port 8000) + Next.js + Celery + Redis + PostgreSQL + Ollama + Prometheus/Grafana + MLflow profile.

---

## 1. Dataset

### 1.1 Du lieu that
- [ ] Thu thap it nhat 50 meetings that co transcript va permission su dung
- [ ] Dam bao da dang: nganh nghe, so nguoi tham gia, ngon ngu EN/VI
- [ ] Luu raw audio + transcript vao `data/raw/` hoac storage rieng, khong commit PII len repo

### 1.2 Synthetic data
- [x] Setup Gemini backend cho `synthetic.py` (`--provider gemini`)
- [x] 54 topics x 8 domains, 34 personas, dynamic turns per topic
- [x] Long meeting support (`--long --duration 30`) - multi-segment concat
- [x] macOS TTS: `tts_macos.py` - transcript -> MP3 dung `say`
- [x] Dataset hien co: 200 short + 5 long + 10 smoke + 13 feedback samples
- [x] Validate output bang `src/meeting_agent/mlops/data_pipeline/validate.py`

### 1.3 Human annotation
- [x] Corrections tu UI luu vao DB va export duoc JSONL
- [x] Export training data: `GET /feedback/export?format=jsonl`
- [ ] Target: it nhat 50 meetings co >=1 human correction (hien repo co `feedback_corrections.jsonl`: 13 samples)
- [ ] Tang coverage cho false positive / missing tasks bang review that

### 1.4 Data quality
- [x] Dedupe `feedback_corrections.jsonl` (18 -> 13 samples sau khi loai near-duplicate)
- [x] Dataset compatibility smoke test trong CI (`scripts/dataset_compat_smoke.py`)
- [x] Data contracts cho raw/training/eval records (`src/meeting_agent/mlops/data_contracts.py`)
- [x] Normalized transcript rows + backfill script (`transcript_turns`, `scripts/backfill_transcript_turns.py`)
- [ ] Kiem tra class balance: action / false_positive / missing tasks tren tap feedback moi
- [ ] Verify PII redaction end-to-end truoc khi dung du lieu that cho training
- [ ] Tao train/val/test split versioned: 80/10/10

---

## 2. Fine-tuning Pipeline

### 2.1 Chuan bi
- [x] `transcript_turns` duoc luu vao DB cho meetings moi va co normalized table
- [x] Export format JSONL: `{"instruction": "...", "input": "<transcript>", "output": "<json tasks>"}`
- [x] Dataset version/hash helper de log vao MLflow (`dataset_version.py`)
- [x] `smoke_10.jsonl` san sang test

### 2.2 Chay fine-tuning
- [x] `finetune.py` ho tro QLoRA/Unsloth va log experiment vao MLflow
- [x] Retrain pipeline chay qua Celery queue `mlops`, co threshold check va state file
- [ ] Chay smoke fine-tuning tren may co CUDA/Colab:
  `python3 -m meeting_agent.mlops.finetune --data data/training/smoke_10.jsonl --output models/qwen-meeting-v1 --epochs 1`
- [ ] Chay full training:
  `python3 -m meeting_agent.mlops.finetune --data data/training/synthetic.jsonl --data data/training/synthetic_long.jsonl --epochs 3`
- [ ] Luu run ID, dataset hash, metrics va artifact path vao release note/model card

### 2.3 Deploy model
- [x] Eval gate so sanh candidate voi champion truoc khi promote
- [x] MLflow promotion manifest + deploy helper (`scripts/deploy_promoted_model.py`)
- [ ] Convert LoRA/GGUF -> Ollama custom model (`ollama create meeting-agent-v1 -f Modelfile`)
- [ ] Chay deploy co chu dich: `make deploy-promoted-model APPLY=1`
- [ ] Set `OLLAMA_LLM_MODEL=meeting-agent-v1` trong `.env` va restart worker/API

---

## 3. Metrics

### 3.1 Academic metrics
- [x] Evaluation script tinh Precision / Recall / F1, hallucination, due-date exact match
- [x] CI eval smoke threshold precision >= 0.70 neu co `data/eval/gold_smoke.jsonl`
- [ ] Chay benchmark tren validation set lon hon, target F1 >= 0.80
- [ ] Assignee resolution accuracy tren real meetings
- [ ] Bao cao hallucination rate theo model version

### 3.2 Business metrics
- [x] Correction rate
- [x] False positive rate
- [x] Training-ready samples
- [x] Grafana dashboard + alert rules
- [x] Calendar event persistence trong DB
- [ ] Time-to-action: thoi gian tu upload -> calendar event duoc tao
- [ ] Calendar adoption rate: % meetings co >=1 event duoc sync
- [ ] User retention: % user quay lai upload meeting lan 2+

### 3.3 Monitoring
- [x] Prometheus + Grafana
- [x] Alert khi correction rate tang dot bien (Z-score anomaly detector)
- [x] Weekly drift check (`check_weekly_drift()`)
- [x] Business metrics endpoint (`/metrics/business`)

---

## 4. MLOps Lifecycle

### 4.1 Feedback loop
- [x] User corrections -> `feedback_corrections` table
- [x] Corrections apply vao `tasks` table (ground truth)
- [x] Export JSONL cho fine-tuning (`/feedback/export`)
- [x] Trigger retrain: Celery Beat + `/admin/retrain` + `force` mode
- [ ] Chay retrain that tren GPU va ghi lai artifact/version

### 4.2 Model versioning
- [x] MLflow `log_model` trong `finetune.py`
- [x] So sanh model moi voi champion truoc khi promote
- [x] A/B runtime routing co explicit enablement (`AB_TEST_ENABLED=true`)
- [x] Admin endpoints: `/admin/ab-test/start|status|results|stop`
- [x] Tests cho A/B logic va promotion manifest
- [ ] Test A/B end-to-end voi 2 Ollama model that va traffic that

### 4.3 Data versioning
- [x] Dataset version/hash helper de log vao MLflow
- [ ] Tag JSONL file theo date: `data/training/finetuning_YYYYMMDD.jsonl`
- [ ] Ghi mapping data version -> model version -> deploy version trong model card/release note

---

## 5. Code / Architecture

### 5.1 Refactor
- [x] Move `train/` vao `src/meeting_agent/mlops/`
- [x] Move `data_pipeline/` vao `src/meeting_agent/mlops/data_pipeline/`
- [x] DB-backed worker registry
- [x] DB-backed calendar events
- [x] Normalized transcript turns va auditable meeting artifacts

### 5.2 Features
- [x] Meeting history page (`/history`)
- [x] Participants management - gan `SPEAKER_UNKNOWN` -> worker
- [x] Test `PUT /workers/{id}` tu frontend/backend path
- [x] Calendar sync idempotency va partial failure handling
- [x] Auth/ownership foundation cho meeting, calendar token va delete/export paths
- [ ] Hoan thien team/worker ownership neu can multi-tenant that

### 5.3 Tests
- [x] `test_feedback_loop.py`
- [x] `test_calendar_router.py`
- [x] `test_export.py`
- [x] `test_ab_test.py`
- [x] `test_retrain_promotion.py`
- [x] `test_deploy_promoted_model.py`
- [x] Schema, migration, dataset compatibility, hygiene, web build trong CI
- [ ] Test `POST /admin/retrain` voi mocked Celery/retrain module
- [ ] Integration test: upload audio -> poll until completed -> verify tasks in DB

### 5.4 Production
- [x] Docker Compose production config (`docker-compose.prod.yml`)
- [x] GPU/MLOps compose profile (`docker-compose.gpu.yml`) cho trainer/beat/mlflow
- [x] Health check cho API + worker
- [x] Bo nginx khoi active path (khong can thiet o quy mo hien tai)
- [x] `.github/workflows/docker-build.yml` build & push API/worker images len GHCR khi merge/push main
- [ ] Rate limiting tren API, dac biet `POST /meetings`
- [ ] Decide release policy: explicit deploy command hay protected release workflow

---

## 6. GitHub DevOps / CI-CD

### 6.1 CI
- [x] `.github/workflows/ci.yml` - ruff + pytest + coverage threshold 60% + schema smoke + eval smoke + Docker build check
- [x] Web lint/build trong CI
- [x] Alembic migration smoke test trong CI
- [x] Dataset compatibility smoke test trong CI
- [x] Repository hygiene check trong CI

### 6.2 CD
- [x] `.github/workflows/docker-build.yml` - build & push `ghcr.io/<repo>-api:<sha>` va `ghcr.io/<repo>-worker:<sha>` tren main
- [ ] Them web image vao CD neu frontend se deploy bang container rieng
- [ ] Them deployment environment/protected approval neu dung GitHub Environments

### 6.3 Branch strategy
- [ ] Protect `main` branch: require PR + CI pass
- [ ] Convention: `feat/`, `fix/`, `data/`, `train/` prefixes
