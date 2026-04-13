# Vision — Chúng ta xây dựng cái gì?

## Meeting AI Agent

> **Upload audio cuộc họp → Nhận danh sách task có người phụ trách, deadline, độ ưu tiên — trong vài phút.**

---

## Demo flow (người dùng thấy gì)

```
1. Upload file meeting.mp3
         ↓
2. Hệ thống xử lý (1–2 phút với 30 phút audio)
         ↓
3. Nhận kết quả:
   - Tóm tắt cuộc họp (3–5 câu)
   - Danh sách action items:
     ✅ "Bob Kim — Gửi báo cáo Q2 cho client — Due: Thứ 6"  [confidence: 90%]
     ✅ "Alice Chen — Review API docs — Due: Tuần sau"       [confidence: 85%]
     ⚠️  "Cần xem xét: investigate caching" → human review

4. Sửa sai → Feedback → Hệ thống học lại
```

---

## Điểm khác biệt so với các giải pháp hiện tại

| | ChatGPT / GPT-4 API | Otter.ai | Meeting AI Agent |
|--|--|--|--|
| Dữ liệu ra ngoài | ✅ có | ✅ có | ❌ **100% local** |
| Assign task tự động | ❌ | ❌ | ✅ |
| Fine-tune theo doanh nghiệp | ❌ | ❌ | ✅ |
| Feedback & tự học | ❌ | ❌ | ✅ |
| Open source, tự deploy | ❌ | ❌ | ✅ |

---

## Nguyên tắc thiết kế

- **Privacy-first** — tất cả model chạy local, không API cloud
- **Traceable** — mỗi task biết xuất phát từ câu nói nào trong cuộc họp
- **Correctable** — user sửa sai → hệ thống học lại tự động
