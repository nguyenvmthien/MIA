# Monitoring & Observability Guide

This project has three observability layers: **LangSmith** (LLM traces), **Prometheus + Grafana** (system metrics), and **anomaly detection** (statistical alerts). This guide explains how to set each one up and use it day-to-day.

---

## 1. LangSmith — LLM trace management

LangSmith captures every prompt sent to Ollama, the raw response, token counts, and latency. Use it to debug bad extractions, tune prompts, and spot regressions.

### Setup

1. Create a free account at [smith.langchain.com](https://smith.langchain.com).
2. Create a project (e.g. `meeting-agent`).
3. Copy your API key from **Settings → API Keys**.
4. Add to `.env`:

```env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls_xxxxxxxxxxxxxxxx
LANGCHAIN_PROJECT=meeting-agent
```

That's all — the orchestrator auto-enables tracing when these vars are set (`orchestrator.py:42–50`).

### What gets traced

Each meeting processing run produces two LangSmith traces:

| Trace name | What it captures |
|---|---|
| `_raw_llm_call` (summarize) | Full system + user prompt for the summary, raw LLM response |
| `_raw_llm_call` (extract_tasks) | Few-shot CoT prompt per chunk, raw JSON response |

Traces are tagged with the `LANGCHAIN_PROJECT` name so you can filter by project.

### Day-to-day workflow

**View a bad extraction:**
1. Open LangSmith → your project → **Runs**.
2. Filter by `run_type = llm`. Find the run by timestamp or meeting_id (passed as metadata).
3. Click a run → **Input/Output** to see the exact prompt and response.
4. Click **Feedback** to tag the run as correct/incorrect — this feeds LangSmith's built-in evals.

**Compare prompt versions:**
- Each time you edit `prompts/templates.py`, bump `PROMPT_VERSION` in the template.
- Filter runs by metadata `prompt_version` to A/B compare outputs side by side.

**Set up an alert:**
- LangSmith → **Rules** → create a rule on `latency_p95 > 10s` or `error_rate > 5%` → notify via email or Slack webhook.

---

## 2. Prometheus + Grafana — system metrics

### What's collected

Metrics are exposed at `GET /metrics` (Prometheus format). Key metrics:

| Metric | Type | Description |
|---|---|---|
| `meeting_stage_duration_seconds` | Histogram | Per-stage latency (label: `stage`) |
| `meeting_llm_tokens_total` | Counter | Cumulative token usage |
| `meeting_hallucination_flags_total` | Counter | Guardrail hallucination detections |
| `meeting_anomaly_events_total` | Counter | Statistical outlier events |
| `meeting_tasks_extracted_total` | Counter | Successfully extracted tasks |
| `meeting_jobs_total` | Counter | Jobs by status (`completed`, `failed`) |
| `meeting_llm_calls_total` | Counter | Total LLM calls (label: `model`) |

### With Docker Compose (auto-configured)

Everything is pre-wired. After `docker compose up`:

| Service | URL | Default credentials |
|---|---|---|
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |

Prometheus scrapes `/metrics` on the API every 15 seconds (configured in `docker/prometheus.yml`).

### Creating a Grafana dashboard

1. Open Grafana → **Dashboards → New → New Dashboard → Add visualization**.
2. Select datasource `Prometheus`.
3. Example queries:

```promql
# Average STT latency over last 5 min
histogram_quantile(0.95, rate(meeting_stage_duration_seconds_bucket{stage="stt"}[5m]))

# Hallucination rate per job
rate(meeting_hallucination_flags_total[5m]) / rate(meeting_jobs_total[5m])

# Tasks extracted per minute
rate(meeting_tasks_extracted_total[1m])
```

4. Save the dashboard and pin it to your home view.

**Quick smoke traffic** (to populate dashboards when no real traffic exists):
```bash
for i in {1..30}; do curl -s http://localhost:8000/health >/dev/null; done
```

### Without Docker (local dev)

Install and run Prometheus locally:
```bash
brew install prometheus   # macOS
# Edit docker/prometheus.yml — change target to localhost:8000
prometheus --config.file=docker/prometheus.yml
```

---

## 3. Anomaly detection — rolling Z-score alerts

The built-in detector (`monitoring/anomaly.py`) flags statistical outliers automatically, without external services.

### How it works

- Maintains a rolling window (default: last 100 samples) per metric.
- Fires an alert when a new value is more than `z_threshold` (default: 3.0) standard deviations from the rolling mean.
- Hard thresholds can be configured for absolute limits (e.g. "flag if latency > 30s regardless of history").

### Metrics monitored

| Metric key | What it watches |
|---|---|
| `llm_latency_ms` | LLM call duration |
| `tasks_extracted` | Number of action items per meeting |
| `hallucination_flags` | Guardrail flags per run |
| `total_tokens` | Token usage per run |

### Viewing anomaly events

Anomaly events increment the `meeting_anomaly_events_total` Prometheus counter (visible in Grafana).

They are also logged at `WARNING` level — check application logs:
```bash
docker compose logs api | grep ANOMALY
```

### Tuning the detector

In `config.py` (or `.env`), you can expose these settings if you need tighter/looser thresholds:

```env
# Example: tighten to 2.5σ
ANOMALY_Z_THRESHOLD=2.5
ANOMALY_WINDOW_SIZE=50
```

> The detector is initialised in `monitoring/anomaly.py` and called from `pipeline/run.py` after each completed run.

---

## 4. Feedback loop metrics

The feedback store (`data/transcripts/_feedback.jsonl`) also exposes aggregate stats:

```bash
curl http://localhost:8000/feedback/stats
```

Returns correction counts, most-corrected assignees, and false-positive rates. Use this to decide when to trigger retraining:

```bash
# Check if retraining threshold is met (default: 50 corrections)
python3 -m meeting_agent.mlops.retrain --check

# Force retrain now
python3 -m meeting_agent.mlops.retrain --force
```

View retraining history:
```bash
curl http://localhost:8000/admin/retrain/state
```
