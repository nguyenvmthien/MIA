# Demo — Output thực tế của hệ thống

## Streamlit UI — 3 tabs

| Tab | Chức năng |
|-----|-----------|
| **Upload** | Drag-and-drop audio, paste roster JSON, real-time polling |
| **Results** | Xem action items, run metrics, stage timings |
| **Feedback** | Sửa bất kỳ field nào và submit correction |

---

## REST API — Đơn giản cho integration

```bash
# 1. Submit meeting
curl -X POST http://localhost:8000/meetings \
  -F "audio=@meeting.mp3" \
  -F 'roster_json={"workers":[{"name":"Alice Chen","aliases":["Alice"]}]}'

# Response:
{"meeting_id": "abc-123", "status": "accepted"}

# 2. Poll kết quả
curl http://localhost:8000/meetings/abc-123
# pending → processing → full MeetingSummary JSON

# 3. Submit correction
curl -X POST http://localhost:8000/meetings/abc-123/feedback \
  -d '{"corrections":[{"task_id":"...","corrected_assignee":"Bob Kim"}]}'

# 4. GDPR: xoá dữ liệu
curl -X DELETE http://localhost:8000/meetings/abc-123
```

---

## MeetingSummary — Output JSON đầy đủ

```json
{
  "meeting_id": "abc-123",
  "participants": ["Alice Chen", "Bob Kim"],
  "summary_text": "Team reviewed Q2 priorities. Bob will send report to client...",
  "action_items": [
    {
      "description": "Send quarterly report to client",
      "assignee": "Bob Kim",
      "due_date": "2026-04-17",
      "priority": "high",
      "status": "open",
      "extraction_confidence": 0.90,
      "source_turn_ids": ["turn-uuid-1"]  ← traceability
    }
  ],
  "human_review_items": [...],     ← low confidence items
  "run_metrics": {
    "total_tokens_used": 3840,
    "stage_timings": {
      "stt_ms": 42000, "llm_ms": 7400, "total_ms": 50692
    },
    "hallucination_flags": 0
  }
}
```
