# Data Pipeline

Hướng dẫn đầy đủ cách thu thập, sinh, validate, và chuẩn bị dữ liệu cho Meeting Agent.

---

## Tổng quan

```
[Nguồn dữ liệu]
       │
       ├── 1. Audio thật     → data_pipeline/collect.py   → data/training/collected.jsonl
       ├── 2. Synthetic LLM  → data_pipeline/synthetic.py → data/training/synthetic.jsonl
       └── 3. Feedback user  → data/transcripts/_feedback.jsonl (tự động)
                  │
                  ▼
       data_pipeline/validate.py  (schema, bias, leakage, duplicate check)
                  │
                  ▼
       train/finetune.py  (QLoRA fine-tuning)
```

---

## Cấu trúc thư mục data/

```
data/
├── audio/               ← File audio đầu vào (.mp3, .wav, .m4a, ...)
│   └── test_meeting.mp3
├── transcripts/         ← Transcript JSON đã xử lý + feedback
│   └── _feedback.jsonl
├── training/            ← Dataset cho fine-tuning
│   ├── synthetic.jsonl
│   ├── collected.jsonl
│   └── val.jsonl
├── eval/                ← Gold set cho đánh giá
│   └── gold.jsonl
└── models/              ← Model checkpoint sau khi train
```

---

## 1. Sinh Audio Test (macOS)

Dùng `say` (text-to-speech có sẵn trên macOS) để tạo file audio test nhanh mà không cần recording thật.

```bash
# Tạo script cuộc họp
say -v Alex -o data/audio/test_meeting.aiff \
"Alice, can you send the quarterly report to the client by this Friday?
Sure, I will prepare and send it before Friday afternoon.
Bob, please review the API documentation and submit feedback before end of day.
Got it, I will send my comments by five PM.
Carol, can you schedule a follow-up meeting with the design team for next Monday?
Yes, I will send the calendar invite this morning." \
&& ffmpeg -i data/audio/test_meeting.aiff data/audio/test_meeting.mp3 -y

# Xóa file trung gian
rm data/audio/test_meeting.aiff
```

**Lưu ý:**
- `-v Alex` — giọng đọc (có thể dùng `say -v ?` để xem danh sách giọng)
- `ffmpeg` convert từ `.aiff` sang `.mp3` (WhisperX đọc tốt hơn với `.mp3`/`.wav`)
- File lưu vào `data/audio/` — **không** lưu vào `/tmp/` vì sẽ bị xóa khi restart

---

## 2. Sinh Synthetic Data (LLM-generated)

`data_pipeline/synthetic.py` dùng Ollama (`qwen2.5:3b`) để sinh transcript cuộc họp giả cùng ground-truth action items.

### Cách chạy

```bash
# Sinh 50 mẫu (mặc định)
python3 data_pipeline/synthetic.py --count 50 --out data/training/synthetic.jsonl

# Sinh nhiều hơn cho fine-tuning
python data_pipeline/synthetic.py --count 200 --out data/training/synthetic.jsonl
```

### Cơ chế hoạt động

| Bước | Mô tả |
|---|---|
| Random topic | Chọn ngẫu nhiên từ 8 chủ đề (roadmap, sprint, bug triage, ...) |
| Random participants | Chọn 2–4 người từ 5 persona mẫu |
| LLM generate | Gọi `qwen2.5:3b` sinh transcript 4–8 turns + action items JSON |
| Parse & save | Strip markdown fences, parse JSON, append vào JSONL |
| Retry | Thử lại tối đa `count × 3` lần nếu LLM trả về JSON lỗi |

### Cấu trúc mỗi dòng JSONL

```json
{
  "meeting_date": "2026-04-10",
  "participants": "Alice Chen (Product Manager), Bob Kim (Backend Developer)",
  "transcript_turns": [
    {
      "speaker_name": "Alice Chen",
      "speaker_id": "SPEAKER_00",
      "start_ms": 0,
      "end_ms": 5000,
      "text": "Bob, can you finish the API spec by Thursday?"
    }
  ],
  "action_items": [
    {
      "description": "Finish API spec",
      "assignee": "Bob Kim",
      "due_date": "2026-04-15",
      "priority": "high",
      "notes": null
    }
  ],
  "roster": {
    "workers": [
      {"worker_id": "w0", "name": "Alice Chen", "aliases": ["Alice"], "role": "Product Manager"},
      {"worker_id": "w1", "name": "Bob Kim", "aliases": ["Bob"], "role": "Backend Developer"}
    ]
  },
  "transcript": "[Alice Chen]: Bob, can you finish the API spec by Thursday?\n[Bob Kim]: Sure."
}
```

### Yêu cầu

- Ollama đang chạy với model `qwen2.5:3b` đã pull
- Hoặc chạy trong Docker: `docker compose exec api python data_pipeline/synthetic.py --count 50 --out data/training/synthetic.jsonl`

---

## 2.5. Chuyển Synthetic JSONL thành Audio test

Khi bạn đã có `data/training/synthetic.jsonl`, có thể sinh audio tương ứng để test end-to-end từ input âm thanh.

Script: `data_pipeline/synthetic_to_audio.py`

### Chạy thử nhanh (3 mẫu)

```bash
python3 data_pipeline/synthetic_to_audio.py \
  --input data/training/synthetic.jsonl \
  --out-dir data/audio/synthetic \
  --limit 3 \
  --overwrite
```

### Chuyển toàn bộ dataset

```bash
python3 data_pipeline/synthetic_to_audio.py \
  --input data/training/synthetic.jsonl \
  --out-dir data/audio/synthetic \
  --overwrite
```

### Output tạo ra

- Mỗi sample tạo ra 1 file `.mp3` theo dạng `meeting_00000.mp3`
- Mỗi sample có 1 file `.json` đi kèm để đối chiếu nội dung transcript
- Tất cả lưu trong thư mục `data/audio/synthetic/`

### Yêu cầu môi trường

- macOS có sẵn lệnh `say`
- Cài `ffmpeg` để ghép/convert audio (`brew install ffmpeg`)

### Ghi chú

- Audio này dùng cho test pipeline (ingest -> STT -> LLM), không thay thế dữ liệu họp thật.
- Giọng nói được gán theo speaker bằng tập voice mặc định trong script.

---

## 3. Thu thập từ Audio thật

`data_pipeline/collect.py` chạy toàn bộ pipeline trên thư mục audio và lưu output làm training data.

```bash
# Thu thập từ thư mục audio
python data_pipeline/collect.py audio \
  --audio-dir data/audio \
  --roster examples/roster.json \
  --out data/training/collected.jsonl
```

**Định dạng audio hỗ trợ:** `.mp3`, `.wav`, `.mp4`, `.m4a`, `.flac`, `.ogg`

Mỗi file audio được chạy qua pipeline đầy đủ (preprocess → STT → LLM → guardrails → assign) và kết quả `MeetingSummary` được lưu thành 1 dòng JSONL.

---

## 4. Feedback từ User (tự động)

Mỗi lần user submit correction qua API, hệ thống tự động lưu vào:

```
data/transcripts/_feedback.jsonl
```

```bash
# Xem feedback đã thu thập
cat data/transcripts/_feedback.jsonl

# Dùng feedback làm training data bổ sung
python train/finetune.py \
  --data data/training/synthetic.jsonl data/transcripts/_feedback.jsonl \
  --output models/qwen-meeting-v2
```

---

## 5. Validate Dataset

Trước khi fine-tune, luôn validate để tránh bias và data leakage.

```bash
python data_pipeline/validate.py \
  --train data/training/synthetic.jsonl \
  --val   data/training/val.jsonl
```

### Các check được thực hiện

| Check | Mô tả | Kết quả |
|---|---|---|
| Schema | Kiểm tra `transcript`, `meeting_date`, `action_items` có mặt | ERROR nếu thiếu |
| Speaker balance | Không speaker nào chiếm > 80% số turns | WARN nếu vượt |
| Train/val leakage | Speaker trong val phải có trong train | WARN nếu unseen |
| Duplicate | Phát hiện transcript gần giống nhau (100 ký tự đầu) | WARN nếu trùng |
| Label quality | `action_items` phải là list | ERROR nếu sai kiểu |

**Exit code:** `0` = pass, `1` = có ERROR (không nên dùng để train)

---

## 6. Quy trình đầy đủ từ đầu

```bash
# Bước 1: Sinh synthetic data
python data_pipeline/synthetic.py --count 100 --out data/training/synthetic.jsonl

# Bước 2: Sinh validation set riêng
python data_pipeline/synthetic.py --count 20 --out data/training/val.jsonl

# Bước 3: Validate
python data_pipeline/validate.py \
  --train data/training/synthetic.jsonl \
  --val   data/training/val.jsonl

# Bước 4: Fine-tune (cần GPU ≥ 8GB VRAM)
pip install -e ".[train]"
python train/finetune.py \
  --data data/training/synthetic.jsonl \
  --output models/qwen-meeting-v1 \
  --epochs 3
```

---

## Ghi chú

- Tất cả data trong `data/` **không commit lên git** (đã có trong `.gitignore`)
- File audio test sinh bằng `say` chỉ dùng cho development — không dùng để train
- Để có data chất lượng cao, ưu tiên dùng audio cuộc họp thật + feedback corrections
