# Meeting Agent — TODO & MLOps Roadmap

> Cập nhật: 2026-05-04. Full pipeline đã chạy được (upload audio → STT/diarization → LLM extract → DB → feedback → calendar sync).
> History page + Participants management UI done. Synthetic data: 12 samples (Gemini, dừng do quota). TTS: 12 MP3 từ macOS `say`.
> Business metrics dashboard done (41 Grafana panels, alert rules). Tests: feedback_loop + export + calendar_router. Docker prod config + Makefile done.

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
- [ ] **Enable Gemini billing** → chạy full 200 short + 10 long meetings
  ```bash
  python data_pipeline/synthetic.py --count 200 --provider gemini --out data/training/synthetic_v1_$(date +%Y%m%d).jsonl
  python data_pipeline/synthetic.py --long --count 10 --duration 30 --provider gemini --out data/training/synthetic_long_$(date +%Y%m%d).jsonl
  ```
- [ ] Validate output với `data_pipeline/validate.py`
- [ ] Convert transcript → audio: `python data_pipeline/tts_macos.py --input <file> --out-dir data/audio/synthetic_tts`

### 1.3 Human annotation
- [ ] Sau mỗi meeting thật → user review trên UI → corrections lưu vào DB
- [ ] Target: ít nhất 50 meetings có ít nhất 1 human correction
- [ ] Export training data:
  ```bash
  PYTHONPATH=src python data_pipeline/export_for_finetuning.py \
      --out data/training/finetuning.jsonl --min-corrections 1
  ```

### 1.4 Data quality
- [ ] Kiểm tra class balance: action / false_positive / missing tasks
- [ ] Kiểm tra assignee distribution (không bị bias về 1 người)
- [ ] Loại bỏ PII trước khi dùng cho training (đã có guardrail nhưng cần verify)
- [ ] Train/val/test split: 80/10/10

---

## 2. Fine-tuning Pipeline

### 2.1 Chuẩn bị
- [ ] Đảm bảo `transcript_turns` được lưu vào DB cho tất cả meetings mới
  - Meetings cũ chỉ có `summary_text` → dùng làm fallback input
- [ ] Format JSONL: `{"instruction": "...", "input": "<transcript>", "output": "<json tasks>"}`

### 2.2 Chạy fine-tuning
- [ ] Test chạy với data nhỏ (10 examples) trước để verify pipeline không lỗi:
  ```bash
  PYTHONPATH=src python train/finetune.py \
      --data data/training/finetuning.jsonl \
      --output models/qwen-meeting-v1 \
      --epochs 1
  ```
- [ ] Chạy full training với GPU (≥8GB VRAM) hoặc Colab
- [ ] Log experiment vào MLflow: `mlflow ui` để xem kết quả

### 2.3 Deploy model
- [ ] Convert LoRA adapter → Ollama custom model:
  ```bash
  ollama create meeting-agent-v1 -f Modelfile
  ```
- [ ] Set `OLLAMA_LLM_MODEL=meeting-agent-v1` trong `.env`
- [ ] Restart worker + API

---

## 3. Metrics

### 3.1 Academic metrics (đã có skeleton trong `train/evaluate.py`)
- [ ] **Precision / Recall / F1** trên task extraction
  - CI threshold hiện tại: 0.70 precision
  - Target: ≥ 0.80 precision sau fine-tune
- [ ] **Assignee resolution accuracy**: % tasks được assign đúng người
- [ ] **Hallucination rate**: % tasks không có trong transcript
- [ ] **Exact match** trên due_date extraction

### 3.2 Business metrics (chưa có)
- [ ] **Time-to-action**: thời gian từ upload → calendar event được tạo
- [ ] **Correction rate**: số corrections / meeting → càng giảm càng tốt
- [ ] **False positive rate**: % tasks bị user deselect
- [ ] **Calendar adoption rate**: % meetings có ≥1 event được sync
- [ ] **User retention**: % user quay lại upload meeting lần 2+

### 3.3 Monitoring (Prometheus + Grafana — đã có cơ bản)
- [x] Thêm dashboard panel cho:
  - Correction rate theo thời gian
  - Assignee resolution success rate
  - Fine-tuning data volume growth
  - Model version performance comparison
- [x] Alert khi correction rate tăng đột biến (model drift)

---

## 4. MLOps Lifecycle

### 4.1 Feedback loop (đã có cơ bản)
- [x] User corrections → `feedback_corrections` table
- [x] Corrections apply vào `tasks` table (ground truth)
- [x] Export JSONL cho fine-tuning
- [ ] **Trigger tự động**: khi đủ 50 corrections mới → trigger retrain
  - Endpoint đã có: `POST /admin/retrain`
  - Celery Beat schedule đã có (24h interval)
  - Cần set `RETRAIN_MIN_CORRECTIONS=50` trong `.env`

### 4.2 Model versioning
- [ ] MLflow tracking cho mỗi training run (đã có trong `finetune.py`)
- [ ] So sánh model cũ vs mới trên validation set trước khi deploy
- [ ] Lưu model artifact: `models/qwen-meeting-v{version}/`
- [ ] A/B test: `pipeline/ab_test.py` (cần integrate vào orchestrator)

### 4.3 Drift detection
- [x] `monitoring/anomaly.py` đã có Z-score detector
- [x] Cần thêm: so sánh distribution của extracted tasks giữa các tuần (`check_weekly_drift()`)
- [x] Alert khi correction rate tăng > 2 std dev

### 4.4 Data versioning
- [ ] Dùng DVC hoặc đơn giản là tag JSONL file theo date:
  `data/training/finetuning_2026-05-04.jsonl`
- [ ] Ghi lại data version nào dùng để train model version nào (trong MLflow)

---

## 5. Code / Architecture còn pending

### 5.1 Refactor
- [ ] Move `train/` vào `src/meeting_agent/train/` — xóa `sys.path` hacks
- [ ] Move `data_pipeline/` vào `src/meeting_agent/data_pipeline/`
- [ ] Sau khi move: update `pyproject.toml` entry points

### 5.2 Features còn thiếu
- [x] **Meeting history page** — xem lại tất cả meetings đã xử lý (`/history`)
- [x] **Participants management** — gán `SPEAKER_UNKNOWN` → worker trong roster (inline trong review step + history page)
- [ ] **PUT /workers/{id}** đã có nhưng frontend roster chưa test kỹ
- [ ] **`/feedback/export?format=jsonl`** — test end-to-end download

### 5.3 Tests còn thiếu
- [x] `tests/test_feedback_loop.py` — end-to-end: submit correction → tasks updated
- [x] `tests/test_calendar_router.py` — mock Google API, verify corrections applied
- [x] `tests/test_export.py` — verify JSONL format matches finetune.py expectations

### 5.4 Production
- [x] Update `.env.example` với tất cả keys mới:
  - `PGADMIN_EMAIL`, `PGADMIN_PASSWORD`
  - `CELERY_WORKER_CONCURRENCY`
  - `RETRAIN_MIN_CORRECTIONS`
- [ ] HTTPS / reverse proxy (nginx) nếu deploy ra ngoài
- [ ] Rate limiting trên API endpoints

---

---

## 6. GitHub DevOps / CI-CD

### 6.1 CI (GitHub Actions)
- [x] `.github/workflows/ci.yml` — chạy tests + lint trên mỗi PR
  - `pytest tests/ -v` với `PYTHONPATH=src`
  - `ruff check src/ tests/`
  - Coverage report (threshold 60%)
  - Docker build check
- [ ] `.github/workflows/docker-build.yml` — build & push Docker image on merge to main
  - Tag: `ghcr.io/<repo>/meeting-agent:<sha>`

### 6.2 CD / Deployment
- [x] Docker Compose production config (`docker-compose.prod.yml`)
  - Tách biệt secrets bằng env file, không hardcode
  - Health check cho API + worker
- [x] `.env.example` đủ tất cả keys (PGADMIN, CELERY, RETRAIN, GEMINI)
- [x] Deployment script hoặc Makefile targets: `make deploy`, `make migrate`

### 6.3 Branch strategy
- [ ] Protect `main` branch: require PR + CI pass
- [ ] Convention: `feat/`, `fix/`, `data/`, `train/` prefixes

---

## 7. Thứ tự ưu tiên gợi ý

```
1. Enable Gemini billing → gen 200 samples + 10 long meetings
2. ✅ Business metrics dashboard (Grafana panels — 41 panels, alert rules)
3. ✅ GitHub CI workflow
4. Chạy fine-tuning 1 lần end-to-end    ← cần data trước
5. ✅ Tests còn thiếu (feedback_loop, export, calendar_router)
6. Move train/ + data_pipeline/ vào src
7. ✅ Docker prod config + Makefile
```
