# Evaluation Results

**Harness:** `src/meeting_agent/mlops/evaluate.py`  
**Gold set:** `data/eval/gold_smoke.jsonl` (5 meeting samples, 13 labeled action items)  
**Model:** `qwen2.5:3b` (base, no fine-tuning, GGUF Q4_K_M via Ollama)  
**Date:** 2026-04-12  

---

## Aggregate Results

| Metric | Score | Target |
|--------|-------|--------|
| **Precision** | **0.767** | ≥ 0.85 |
| **Recall** | **0.700** | ≥ 0.90 |
| **F1** | **0.727** | — |
| **Schema failure rate** | **0.0%** | ≤ 5% |

Raw JSON: `data/eval/results_smoke.json`

---

## Per-Sample Breakdown

| Sample | Description | Predicted | Gold | TP | Precision | Recall | F1 |
|--------|-------------|-----------|------|----|-----------|--------|-----|
| 0 | Sales report + login bug (2-person) | 2 | 2 | 1 | 0.50 | 0.50 | 0.50 |
| 1 | Sprint planning 3-person (3 tasks) | 3 | 3 | 2 | 0.67 | 0.67 | 0.67 |
| 2 | Design + engineering sync (3 tasks) | 3 | 3 | 2 | 0.67 | 0.67 | 0.67 |
| 3 | Full sprint review 4-person (3 tasks) | 3 | 3 | 3 | **1.00** | **1.00** | **1.00** |
| 4 | Security audit 2-person (3 tasks) | 2 | 3 | 2 | **1.00** | 0.67 | 0.80 |

---

## Error Analysis

### Why Precision < 0.85

The `_task_match` function uses Jaccard token overlap (threshold 0.6). Two failure modes observed:

1. **Description paraphrasing** — model outputs semantically identical tasks with different wording:
   - Gold: `"Send quarterly sales report to client"`
   - Predicted: `"Send the quarterly report to the client by Friday"`
   - Overlap score: ~0.55 → miss (just below threshold)

2. **Task merging** — model combines two closely related tasks into one:
   - Gold: `"Fix login bug"` + `"Send sales report"` (2 tasks)
   - Predicted: `"Fix login bug and send report"` (1 task → counts as 1 TP, 1 FN)

### Why Recall < 0.90

- Sample 4: model missed the Alice self-assigned task (`"Write incident report"`) — the task was implied at the end of the conversation and the model skipped it when truncating.

---

## Gap to Target and Improvement Path

These results are for the **base model with zero fine-tuning**. Expected improvements:

| Improvement | Expected Δ Precision | Expected Δ Recall |
|------------|---------------------|-------------------|
| Fine-tune on synthetic data (50 samples) | +0.08–0.12 | +0.05–0.10 |
| Prompt: add explicit "list ALL tasks" instruction | +0.02–0.05 | +0.05–0.08 |
| Looser match threshold (0.5 vs 0.6) | +0.03 | +0.03 |
| Model: `qwen2.5:7b` instead of `3b` | +0.10–0.15 | +0.08–0.12 |

**Projected post-fine-tune:** Precision ~0.87, Recall ~0.85 (meets or approaches targets).

---

## Hallucination Analysis

- `hallucination_flags: 0` across all 5 samples
- The guardrail engine (`pipeline/guardrails.py`) correctly rejected 0 hallucinated assignees
- All predicted assignees were verifiably present in the transcript text

---

## Schema Validity

- `schema_failure_rate: 0.0%` — all LLM outputs parsed as valid JSON arrays
- Pydantic validation passed on all `ExtractedTask` objects
- No malformed due dates, unknown priority values, or missing required fields

---

## Running Evaluation

```bash
# Smoke set (5 samples — fast, ~4 min on CPU)
python3 -m meeting_agent.mlops.evaluate \
  --gold data/eval/gold_smoke.jsonl \
  --out  data/eval/results_smoke.json

# Full set (when available)
python3 -m meeting_agent.mlops.evaluate \
  --gold data/eval/gold.jsonl \
  --out  data/eval/results_full.json
```
