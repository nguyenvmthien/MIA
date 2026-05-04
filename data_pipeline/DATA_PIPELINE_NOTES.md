# Data Pipeline — Cách làm Synthetic Data

## Tổng quan flow

```
Gemini API (LLM)
    → transcript JSON (turns + action items)
    → macOS `say` TTS
    → MP3 audio (multi-voice, multi-speaker)
    → upload qua pipeline như audio thật
```

---

## Bước 1: Gen transcript bằng Gemini

### Setup
```bash
pip install -e ".[data]"
# Thêm vào .env:
GEMINI_API_KEY=AIza...   # lấy tại aistudio.google.com/apikey
```

### Chạy short meetings (3-6 phút)
```bash
python data_pipeline/synthetic.py \
    --count 200 \
    --provider gemini \
    --out data/training/synthetic_v1_$(date +%Y%m%d).jsonl
```

### Chạy long meetings (30+ phút, multi-segment)
```bash
python data_pipeline/synthetic.py \
    --long \
    --count 10 \
    --duration 30 \
    --provider gemini \
    --out data/training/synthetic_long_$(date +%Y%m%d).jsonl
```

### Quota Gemini
- `gemini-2.5-flash` free tier: **20 req/day** — chỉ đủ ~12 short samples
- Để gen 200+ samples: **enable billing** trên Google Cloud (~$0.02-0.05 tổng)
- Link: console.cloud.google.com → Billing → Link account

### Output format (mỗi dòng JSONL)
```json
{
  "transcript_turns": [
    {"speaker_name": "Olivia Zhang", "speaker_id": "SPEAKER_00",
     "start_ms": 0, "end_ms": 5000, "text": "..."}
  ],
  "action_items": [
    {"description": "...", "assignee": "Peter Walsh",
     "due_date": "2026-05-10", "priority": "high", "notes": null}
  ],
  "domain": "finance",
  "num_turns": 12,
  "meeting_date": "2026-05-04",
  "participants": "Olivia Zhang (CFO), Peter Walsh (Financial Analyst), ..."
}
```

---

## Bước 2: Convert transcript → audio (macOS TTS)

```bash
python data_pipeline/tts_macos.py \
    --input data/training/synthetic_v1_20260504.jsonl \
    --out-dir data/audio/synthetic_tts \
    --limit 12   # bỏ --limit để convert tất cả
```

- Mỗi speaker được assign 1 giọng khác nhau từ `_VOICE_POOL`
- Giọng dùng: Daniel, Karen, Moira, Rishi, Fred, Kathy, ... (macOS built-in)
- Output: `meeting_00000_finance.mp3`, `meeting_00001_tech.mp3`, ...
- Tốc độ: ~30-60s/file tùy số turns
- Size: ~1MB/file cho meeting ~2 phút

### Thời lượng audio tương ứng
| Turns | Domain ví dụ | Audio ước tính |
|-------|-------------|----------------|
| 5-8   | stand-up, email review | ~1-2 phút |
| 8-12  | sprint planning, campaign | ~2-3 phút |
| 12-16 | budget review, post-mortem | ~3-5 phút |
| 16-20 | all-hands, M&A kickoff | ~5-7 phút |
| 100+  | long meeting (30min mode) | ~25-35 phút |

---

## Bước 3: Upload audio vào pipeline

Sau khi có MP3, upload bình thường qua UI hoặc API:
```bash
curl -X POST http://localhost:8000/meetings \
  -F "audio=@data/audio/synthetic_tts/meeting_00000_finance.mp3" \
  -F 'roster_json={"workers": [{"worker_id":"w0","name":"Olivia Zhang","role":"CFO","aliases":["Olivia"]},...]}'
```

Hoặc dùng script batch (chưa có, cần viết thêm nếu cần test nhiều file).

---

## Domain coverage

| Domain | Topics | Personas tiêu biểu |
|--------|--------|-------------------|
| tech | 10 | Alice Chen (PM), Bob Kim (BE Dev), Grace Park (EM) |
| marketing | 10 | Isabelle Durand (Mktg Mgr), Liam O'Brien (Growth) |
| finance | 10 | Olivia Zhang (CFO), Peter Walsh (Analyst) |
| sales | 7 | Tina Müller (Sales Dir), Vanessa Li (CS Mgr) |
| hr | 4 | Zoe Hernandez (HR Mgr), Bella Johnson (TA) |
| operations | 4 | Yuki Tanaka (Ops Mgr), Aaron Scott (Supply Chain) |
| executive | 6 | Fiona Campbell (CEO), George Baker (COO) |
| legal | 3 | Diana Moore (Legal), Edward Hill (Compliance) |

Participant selection: 70% từ domain pool + 30% cross-functional noise.

---

## Grounding filter

Action items bị reject nếu:
- Overlap < 2 tokens giữa description và transcript text
- Assignee không phải speaker name trong transcript

Logic này đảm bảo model không hallucinate tasks không được nhắc đến.

---

## Files liên quan

```
data_pipeline/
  synthetic.py       — gen transcript (Gemini / Ollama)
  tts_macos.py       — convert transcript → MP3
  validate.py        — check schema/bias/leakage
  collect.py         — collect từ audio dirs thật

data/training/
  synthetic_v1_YYYYMMDD.jsonl   — short meetings
  synthetic_long_YYYYMMDD.jsonl — long meetings (30min+)

data/audio/synthetic_tts/
  meeting_NNNNN_domain.mp3
```
