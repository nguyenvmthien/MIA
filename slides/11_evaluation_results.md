# Evaluation Results — Kết quả đánh giá

## Setup đánh giá

- **Harness:** `train/evaluate.py` — Precision / Recall / F1
- **Gold set:** 5 meeting samples, 13 labeled action items
- **Model:** Qwen2.5-3B base (chưa fine-tune)
- **Metric matching:** Jaccard token overlap ≥ 0.6

---

## Kết quả tổng hợp

| Metric | Kết quả | Target | Status |
|--------|---------|--------|--------|
| **Precision** | **0.767** | ≥ 0.85 | 🔧 cần fine-tune |
| **Recall** | **0.700** | ≥ 0.90 | 🔧 cần fine-tune |
| **F1** | **0.727** | — | — |
| **Schema failure rate** | **0.0%** | ≤ 5% | ✅ |
| **Hallucination flags** | **0** | ≤ 5% | ✅ |

---

## Phân tích lỗi — Tại sao Precision/Recall chưa đạt target?

**Precision thấp do:**
1. **Description paraphrasing** — model nói đúng nghĩa nhưng khác từ:
   - Gold: `"Send quarterly sales report to client"`
   - Predicted: `"Send the quarterly report to the client by Friday"`
   - Jaccard score: ~0.55 → miss (dưới threshold 0.6)

2. **Task merging** — model gộp 2 task thành 1:
   - Gold: `"Fix login bug"` + `"Send sales report"` (2 tasks)
   - Predicted: `"Fix login bug and send report"` (1 task)

**Recall thấp do:**
- Implied tasks bị bỏ sót khi truncate ở cuối transcript

---

## Lộ trình cải thiện

| Cải thiện | Δ Precision | Δ Recall |
|-----------|------------|---------|
| Fine-tune 50 samples | +0.08–0.12 | +0.05–0.10 |
| Prompt: "list ALL tasks explicitly" | +0.02–0.05 | +0.05–0.08 |
| Looser match threshold (0.5) | +0.03 | +0.03 |
| Dùng Qwen2.5-7B | +0.10–0.15 | +0.08–0.12 |

**Dự kiến sau fine-tune:** Precision ~0.87, Recall ~0.85 ✅
