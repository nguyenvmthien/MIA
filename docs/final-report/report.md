# Meeting AI Agent
## Báo cáo cập nhật theo trạng thái source hiện tại

**Môn học:** Applied Large Language Models  
**Ngày cập nhật:** 13/05/2026
**Dự án:** Hệ thống xử lý audio cuộc họp, trích xuất action items và vận hành theo LLMOps

---

## Tóm tắt

Meeting AI Agent là hệ thống end-to-end xử lý audio cuộc họp thành transcript có speaker turns, trích xuất action items bằng LLM, cho phép người dùng review/human feedback và đưa dữ liệu correction vào luồng LLMOps. Kiến trúc hiện tại gồm Next.js frontend, FastAPI backend, Celery worker, Redis, PostgreSQL, Ollama/Qwen2.5-3B, Prometheus/Grafana và profile MLOps cho fine-tuning khi có GPU.

Điểm quan trọng của phiên bản hiện tại là dữ liệu vận hành không còn chỉ nằm trong file rời rạc: meeting, participant, transcript turns, tasks, artifacts, feedback corrections, calendar events và worker registry được lưu qua database. Dữ liệu JSONL dùng cho training là artifact được export từ database, không phải nguồn truth chính.

Kết quả baseline hiện tại trên `data/eval/gold_smoke.jsonl` gồm 5 samples và 13 action items: precision `0.767`, recall `0.700`, F1 `0.727`, schema failure rate `0.0%`. Đây là kết quả của model nền Qwen2.5-3B chưa fine-tune.

---

## 1. Giới thiệu

### 1.1 Bối cảnh

Cuộc họp tạo ra nhiều quyết định và công việc tiếp theo, nhưng các thông tin này thường bị thất lạc trong ghi chú thủ công. Hệ thống Meeting AI Agent giải quyết bài toán đó bằng cách tự động xử lý audio, nhận diện các lượt nói, trích xuất action items và cho người dùng chỉnh sửa kết quả trước khi dùng dữ liệu đó cho cải thiện model.

### 1.2 Bài toán NLP

Dự án kết hợp ba bài toán chính:

1. **ASR:** chuyển audio sang transcript bằng WhisperX.
2. **Speaker diarization:** xác định từng lượt nói trong audio nhiều speaker bằng WhisperX/Pyannote.
3. **Information extraction:** dùng Qwen2.5-3B qua Ollama để trích xuất action items, assignee, deadline, priority và evidence.

Speaker diarization chỉ tạo nhãn ẩn danh như `SPEAKER_00`, không tự biết tên thật. Vì vậy UI Human Feedback hiển thị transcript evidence để người dùng map speaker sang participant đúng.

### 1.3 Mục tiêu LLMOps

Hệ thống được thiết kế theo vòng đời LLMOps:

- Prompt và schema có kiểm soát.
- Guardrails cho input/output.
- Database-backed feedback và artifacts.
- Monitoring qua Prometheus/Grafana.
- Export dữ liệu correction sang JSONL.
- Retrain gate khi đủ `RETRAIN_MIN_CORRECTIONS`.
- Evaluation và promotion manifest trước deploy.
- Deploy model promoted sang Ollama bằng thao tác manual/auditable.

---

## 2. Tổng quan tài liệu

Whisper và WhisperX là nền tảng cho ASR có timestamp chính xác. Pyannote hỗ trợ speaker diarization trong môi trường nhiều người nói. Qwen2.5-3B được dùng vì đủ nhẹ để chạy local qua Ollama nhưng vẫn có khả năng instruction-following tốt. FAISS/RAG hỗ trợ truy hồi ngữ cảnh liên quan khi transcript dài. QLoRA/LoRA là hướng fine-tuning phù hợp khi cần tối ưu mô hình nhỏ với GPU vừa phải.

Trong LLMOps, các rủi ro chính gồm output không đúng schema, hallucination, data drift, thiếu monitoring và deployment không có rollback. Vì vậy dự án ưu tiên structured output, validation, audit trail, feedback loop và promotion có kiểm soát.

---

## 3. Phương pháp

### 3.1 Pipeline

```text
Audio upload
  -> ingest + validation
  -> preprocess to 16 kHz mono WAV
  -> WhisperX ASR
  -> WhisperX/Pyannote diarization
  -> transcript_turns in PostgreSQL
  -> LLM extraction with guardrails
  -> roster-based assignment
  -> human review + feedback
  -> calendar sync and MLOps export
```

### 3.2 ASR và diarization

Module `src/meeting_agent/pipeline/stt.py` chạy WhisperX và diarization. Kết quả diarization được lưu dạng artifact để audit và được dùng để gán speaker cho transcript turns. Hệ thống truyền waveform trực tiếp cho diarization để giảm phụ thuộc vào decoding nội bộ khi runtime thiếu `torchcodec` đầy đủ.

### 3.3 Trích xuất action items

LLM nhận transcript, roster và prompt yêu cầu output JSON. Backend kiểm tra schema, lọc hallucination, chuẩn hóa assignee theo roster và lưu task vào database. Task có thể chứa `source_turn_ids` để UI hiển thị bằng chứng transcript.

### 3.4 Dữ liệu

Nguồn dữ liệu hiện tại:

- `data/eval/gold_smoke.jsonl`: 5 mẫu đánh giá, 13 action items.
- `data/training/synthetic.jsonl`: dữ liệu synthetic bootstrap.
- `data/training/collected.jsonl`: dữ liệu collected/export.
- `data/training/feedback_corrections.jsonl`: artifact export từ feedback trong database.

Database là source of truth. JSONL là artifact để training/evaluation.

### 3.5 Fine-tuning

Fine-tuning nằm trong `src/meeting_agent/mlops`, dùng QLoRA/LoRA qua dependency nhóm `train`. `Dockerfile.train` và Docker Compose profile `mlops` đã chuẩn bị môi trường trainer. Khi có GPU và đủ correction, Celery Beat có thể trigger retrain check; trainer chạy trên queue riêng `mlops`.

Hiện tại không claim đã có model fine-tuned tốt hơn baseline vì môi trường hiện tại chưa chạy một fine-tune GPU end-to-end.

### 3.6 Promotion và deploy

Sau khi model candidate được evaluate, hệ thống ghi promotion manifest. Serving switch sang Ollama tag mới vẫn là thao tác manual qua lệnh deploy có chủ đích. Đây là lựa chọn an toàn vì model mới không nên tự động thay model đang phục vụ nếu chưa được review.

---

## 4. Triển khai

### 4.1 Thành phần runtime

- `web/`: Next.js UI cho upload, status, transcript review, speaker mapping và task feedback.
- `src/meeting_agent/api/main.py`: FastAPI endpoints.
- `src/meeting_agent/pipeline/worker_task.py`: Celery tasks, queue routing và scheduled MLOps jobs.
- PostgreSQL: lưu meeting, participants, transcript turns, tasks, artifacts, feedback, calendar events, workers.
- Redis: broker/cache.
- Ollama: LLM serving.
- Prometheus/Grafana: observability.
- `Dockerfile.train`: image train tách khỏi API runtime.

### 4.2 Human Feedback UI

Bước Human Feedback hiện hiển thị:

- Transcript theo từng speaker turn.
- Speaker evidence cho từng `SPEAKER_xx`.
- Dropdown map speaker ẩn danh sang participant thật.
- Task evidence dựa trên `source_turn_ids`.
- Layout responsive hơn, không bị co thành cụm nhỏ ở giữa màn hình.

Thiết kế này xử lý đúng trường hợp một audio có nhiều speaker.

### 4.3 MLOps profile

Profile `mlops` bổ sung:

- `beat`: Celery Beat cho retrain check và drift check.
- `trainer`: worker riêng consume queue `mlops`.
- `mlflow`: tracking server.
- `Dockerfile.train`: dependency train/GPU.

Lệnh vận hành chính:

```bash
make mlops-up
make retrain-check
make retrain-force
make train-image
make deploy-promoted-model APPLY=1
```

---

## 5. Đánh giá

### 5.1 Kết quả baseline

| Metric | Kết quả | Mục tiêu |
|---|---:|---:|
| Precision | 0.767 | >= 0.85 |
| Recall | 0.700 | >= 0.90 |
| F1 | 0.727 | - |
| Schema failure rate | 0.0% | <= 5.0% |

Kết quả theo sample:

| Sample | Gold items | Precision | Recall | F1 |
|---:|---:|---:|---:|---:|
| 0 | 2 | 0.50 | 0.50 | 0.50 |
| 1 | 3 | 0.67 | 0.67 | 0.67 |
| 2 | 3 | 0.67 | 0.67 | 0.67 |
| 3 | 2 | 1.00 | 1.00 | 1.00 |
| 4 | 3 | 1.00 | 0.67 | 0.80 |

### 5.2 Nhận xét

Schema failure rate bằng 0 cho thấy structured output và validation đang ổn định. Recall còn thấp so với mục tiêu, nghĩa là model nền vẫn bỏ sót action items. Đây là lý do cần tiếp tục thu feedback thật và chạy fine-tuning khi có đủ dữ liệu/GPU.

### 5.3 Kiểm thử vận hành

Các kiểm tra đã dùng trong quá trình hoàn thiện:

- Ruff check cho Python.
- Pytest cho STT, retrain promotion, deploy promoted model và export.
- Next.js lint/build.
- Docker Compose config cho profile mặc định và `mlops`.
- Health check API/web sau rebuild.

---

## 6. Thách thức và hạn chế

- Diarization không tự biết tên thật của speaker; cần human mapping hoặc voice enrollment.
- CPU inference chậm với WhisperX/Pyannote/LLM.
- Fine-tuning cần GPU; hiện mới GPU-ready, chưa claim đã chạy xong fine-tune.
- Bộ đánh giá còn nhỏ.
- Raw artifact capture đã có, nhưng retention policy/cleanup cần hoàn thiện thêm nếu production.
- Serving switch sau promotion là manual/auditable, không tự đổi model âm thầm.
- Nếu triển khai production cần HTTPS, secret manager, backup, RBAC chi tiết và alerting nghiêm túc hơn.

---

## 7. Hướng phát triển

- Thu thập thêm feedback thật từ UI và mở rộng gold set.
- Chạy fine-tuning GPU khi đủ correction.
- Đánh giá riêng assignee, deadline, priority và hallucination rate.
- Thêm semantic matching trong evaluation.
- Bổ sung retention policy cho artifacts.
- Mở rộng Grafana với queue age, latency percentile, GPU utilization và alert rules.
- Cân nhắc canary deployment thay vì manual deploy hoàn toàn.

---

## 8. Kết luận

Meeting AI Agent hiện đã có nền tảng đúng cho một project Applied LLM/LLMOps: pipeline audio-to-action-items, UI human feedback, database-backed audit trail, monitoring, evaluation, retrain gate, GPU-ready fine-tune path và controlled deployment. Báo cáo chỉ claim theo đúng trạng thái source hiện tại, tránh mô tả các kiến trúc cũ hoặc các khả năng chưa được triển khai end-to-end.

Trạng thái hiện tại đủ để báo cáo một hệ thống LLMOps hoàn chỉnh ở mức project/demo. Phần cần làm tiếp chủ yếu là mở rộng dữ liệu, chạy fine-tuning thật khi có GPU và hardening nếu muốn triển khai production.

---

## Phụ lục: cấu trúc đúng của dự án

```text
web/                                  # Next.js frontend
src/meeting_agent/
  api/main.py                         # FastAPI
  pipeline/
    stt.py                            # WhisperX + diarization
    worker_task.py                    # Celery tasks and queue routing
  mlops/
    evaluate.py                       # Evaluation harness
    finetune.py                       # GPU fine-tune entrypoint
    data_pipeline/                    # Feedback/data export helpers
scripts/deploy_promoted_model.py      # Controlled deploy flow
docker-compose.yml
Dockerfile.train
Makefile
docs/mlops-runbook.md
docs/project-status.md
data/eval/gold_smoke.jsonl
data/training/
```
