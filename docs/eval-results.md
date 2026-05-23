# Evaluation Results

**Harness:** `src/meeting_agent/mlops/evaluate.py`  
**Benchmark runner:** `scripts/run_benchmark.py`  
**Gold set:** `data/eval/gold_synthetic_205.jsonl`  
**Model:** `qwen2.5:3b` via Ollama  
**Run:** 100 samples, `prompt_mode=few_shot`  
**Date:** 2026-05-23  

---

## Aggregate Results

| Metric | Score | Gate |
|--------|-------|------|
| **Precision** | **0.8604** | hard: >= 0.70 |
| **Recall** | **0.6665** | watch: >= 0.60 |
| **F1** | **0.6886** | watch: >= 0.65 |
| **Assignee accuracy** | **0.5232** | watch: >= 0.50 |
| **Hallucination rate** | **0.0%** | hard: <= baseline + 2pp |
| **Schema failure rate** | **0.0%** | hard: no regression |
| **Avg latency** | **26.97s** | watch |
| **P95 latency** | **120.2s** | watch |

Raw JSON: `data/eval/results/benchmark_20260523_114748_qwen2-5-3b.json`

---

## How Matching Works

For each labeled meeting sample:

1. The benchmark runs the real extraction pipeline with transcript turns, roster, and meeting date.
2. Predicted action items are compared with gold `action_items`.
3. `description` matching uses BM25 with a threshold of `> 2.0`.
4. If BM25 does not match, the matcher falls back to Jaccard token overlap with threshold `>= 0.5`.
5. One gold item can only be matched once.

Precision, recall, and F1 are computed from description-level matches:

```text
precision = true_positive_predictions / predicted_items
recall    = true_positive_predictions / gold_items
F1        = 2 * precision * recall / (precision + recall)
```

Assignee accuracy is tracked separately after a description match. A task with a matched description but wrong assignee still counts as a description-level true positive, but it lowers assignee accuracy.

---

## Gate Policy

The benchmark now separates hard gates from watch metrics:

| Type | Metric | Reason |
|------|--------|--------|
| Hard gate | Precision >= 0.70 | Avoid flooding users with false tasks |
| Hard gate | No schema regression | Keep API/task persistence stable |
| Hard gate | Hallucination delta <= 2pp | Avoid unsafe fabricated tasks |
| Relative gate | F1 drop <= 0.05 vs baseline | Candidate cannot be materially worse overall |
| Watch metric | Recall | Important, but can improve gradually |
| Watch metric | F1 | Tracked against baseline, not an absolute high bar yet |
| Watch metric | Assignee accuracy | Needs real-meeting validation |
| Watch metric | Latency | CPU/Ollama latency is expected to be high locally |

This keeps the benchmark useful for model promotion without requiring every metric to exceed an aggressive fixed target.

---

## Current Interpretation

The baseline model has strong precision and no observed hallucination/schema failures on this 100-sample synthetic benchmark. The main weaknesses are recall, assignee accuracy, and CPU latency.

The next benchmark should compare a candidate model against this baseline rather than requiring all absolute metrics to clear high targets.

```bash
make benchmark CANDIDATE=meeting-agent-v1
```
