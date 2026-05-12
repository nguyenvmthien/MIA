# Meeting Agent — TODO & MLOps Roadmap

> Cập nhật: 2026-05-11. Full pipeline chạy được (upload audio → STT/diarization → LLM extract → DB → feedback → calendar sync).
> Đã xóa: Streamlit UI, CLI mode, streaming STT (WebSocket), nginx reverse proxy.
> Stack hiện tại: FastAPI (port 8000) + Next.js (port 3001) + Celery + Redis + PostgreSQL + Ollama.

---

## 1. Dataset

### 1.1 Thu thập dữ liệu thật
- [ ] Ghi lại / thu thập ít nhất 50 meetings thật có transcript
- [ ] Đảm bảo đa dạng: ngành nghề, số người tham gia, ngôn ngữ (EN/VI)
- [ ] Lưu raw audio + transcript vào `data/raw/`

### 1.2 Synthetic data
- [x] Setup Gemini backend cho `synthetic.py` (`--provider gemini`)
- [x] 54 topics × 8 domains, 34 personas, dynamic turns per topic
- [x] Long meeting support (`--long --duration 30`) — multi-segment concat
- [x] macOS TTS: `tts_macos.py` — transcript → MP3 dùng `say`, 12 file sẵn sàng
- [x] 200 short + 5 long meetings đã gen xong (`synthetic.jsonl`, `synthetic_long.jsonl`)
- [x] Validate output — tất cả pass (`src/meeting_agent/mlops/data_pipeline/validate.py`)

### 1.3 Human annotation
- [x] Corrections từ UI lưu vào DB → export được 13 mẫu sau dedupe (`feedback_corrections.jsonl`)
- [ ] Target: ít nhất 50 meetings có ít nhất 1 human correction (hiện có 19 corrections)
- [x] Export training data: `GET /feedback/export?format=jsonl`

### 1.4 Data quality
- [x] Dedupe `feedback_corrections.jsonl` (18 → 13 samples sau khi loại near-duplicate)
- [ ] Kiểm tra class balance: action / false_positive / missing tasks
- [ ] Loại bỏ PII trước khi dùng cho training (guardrail đã có, cần verify end-to-end)
- [ ] Train/val/test split: 80/10/10

---

## 2. Fine-tuning Pipeline

### 2.1 Chuẩn bị
- [ ] Đảm bảo `transcript_turns` được lưu vào DB cho tất cả meetings mới
- [ ] Format JSONL: `{"instruction": "...", "input": "<transcript>", "output": "<json tasks>"}`

### 2.2 Chạy fine-tuning
- [x] Chuẩn bị `smoke_10.jsonl` (10 examples) sẵn sàng test
- [ ] Chạy fine-tuning trên Colab (Mac không support Unsloth — cần CUDA): `python3 -m meeting_agent.mlops.finetune --data data/training/smoke_10.jsonl --output models/qwen-meeting-v1 --epochs 1`
- [ ] Chạy full training: `python3 -m meeting_agent.mlops.finetune --data data/training/synthetic.jsonl --epochs 3`
- [ ] Log experiment vào MLflow

### 2.3 Deploy model
- [ ] Convert LoRA adapter → Ollama custom model (`ollama create meeting-agent-v1 -f Modelfile`)
- [ ] Set `OLLAMA_LLM_MODEL=meeting-agent-v1` trong `.env` và restart worker

---

## 3. Metrics

### 3.1 Academic metrics
- [ ] Precision / Recall / F1 trên task extraction (CI threshold: 0.70, target: ≥ 0.80)
- [ ] Assignee resolution accuracy
- [ ] Hallucination rate
- [ ] Exact match trên due_date extraction

### 3.2 Business metrics
- [x] Correction rate
- [x] False positive rate
- [x] Grafana dashboard (41 panels, alert rules)
- [ ] Time-to-action: thời gian từ upload → calendar event được tạo
- [ ] Calendar adoption rate: % meetings có ≥1 event được sync
- [ ] User retention: % user quay lại upload meeting lần 2+

### 3.3 Monitoring
- [x] Prometheus + Grafana
- [x] Alert khi correction rate tăng đột biến (Z-score anomaly detector)
- [x] Weekly drift check (`check_weekly_drift()`)

---

## 4. MLOps Lifecycle

### 4.1 Feedback loop
- [x] User corrections → `feedback_corrections` table
- [x] Corrections apply vào `tasks` table (ground truth)
- [x] Export JSONL cho fine-tuning (`/feedback/export`)
- [x] Verify trigger tự động retrain: threshold check + feedback export hoạt động đúng. Fine-tuning cần GPU thật.

### 4.2 Model versioning
- [ ] So sánh model cũ vs mới trên validation set trước khi deploy
- [ ] A/B test: endpoint `/admin/ab-test/start` đã có, cần test end-to-end

### 4.3 Data versioning
- [ ] Tag JSONL file theo date: `data/training/finetuning_YYYYMMDD.jsonl`
- [ ] Ghi lại data version nào dùng để train model version nào (trong MLflow)

---

## 5. Code / Architecture

### 5.1 Refactor
- [x] Move `train/` vào `src/meeting_agent/mlops/` — xóa `sys.path` hacks trong `worker_task.py`
- [x] Move `data_pipeline/` vào `src/meeting_agent/mlops/data_pipeline/`

### 5.2 Features còn thiếu
- [x] Meeting history page (`/history`)
- [x] Participants management — gán `SPEAKER_UNKNOWN` → worker
- [x] Test kỹ `PUT /workers/{id}` từ frontend
- [x] Test end-to-end `GET /feedback/export?format=jsonl`

### 5.3 Tests còn thiếu
- [x] `test_feedback_loop.py`
- [x] `test_calendar_router.py`
- [x] `test_export.py`
- [ ] Test `POST /admin/retrain` với mock retrain module
- [ ] Integration test: upload audio → poll until completed → verify tasks in DB

### 5.4 Production
- [x] Docker Compose production config (`docker-compose.prod.yml`)
- [x] Health check cho API + worker
- [x] Bỏ nginx (không cần thiết ở quy mô hiện tại)
- [ ] Rate limiting trên API (đặc biệt `POST /meetings`)
- [ ] `.github/workflows/docker-build.yml` — build & push Docker image on merge to main

---

## 6. GitHub DevOps / CI-CD

### 6.1 CI
- [x] `.github/workflows/ci.yml` — pytest + ruff + coverage (threshold 60%) + Docker build check

### 6.2 CD
- [ ] `docker-build.yml` — build & push `ghcr.io/<repo>/meeting-agent:<sha>` on merge to main

### 6.3 Branch strategy
- [ ] Protect `main` branch: require PR + CI pass
- [ ] Convention: `feat/`, `fix/`, `data/`, `train/` prefixes
