"""
Prometheus metrics definitions.

All metrics are defined here and imported by pipeline stages.
The FastAPI app exposes /metrics for Prometheus scraping.
"""

from prometheus_client import Counter, Gauge, Histogram

# ── Stage latency (seconds) ───────────────────────────────────────────────────
STAGE_LATENCY = Histogram(
    "meeting_stage_duration_seconds",
    "Duration of each pipeline stage in seconds",
    labelnames=["stage"],
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 600],
)

# ── LLM usage ─────────────────────────────────────────────────────────────────
LLM_CALLS = Counter(
    "meeting_llm_calls_total",
    "Total number of LLM API calls made",
)

LLM_TOKENS = Counter(
    "meeting_llm_tokens_total",
    "Total tokens consumed (prompt + completion)",
)

# ── Quality metrics ───────────────────────────────────────────────────────────
HALLUCINATION_FLAGS = Counter(
    "meeting_hallucination_flags_total",
    "Number of suspected hallucinations detected by guardrail engine",
    labelnames=["reason"],  # no_evidence | invalid_assignee | date_hallucination
)

SCHEMA_FAILURES = Counter(
    "meeting_schema_failures_total",
    "Number of times LLM output failed schema validation",
)

TASKS_EXTRACTED = Counter(
    "meeting_tasks_extracted_total",
    "Total action items successfully extracted",
)

TASKS_UNRESOLVED = Counter(
    "meeting_tasks_unresolved_total",
    "Total action items that could not be fully resolved",
)

# ── Job status ────────────────────────────────────────────────────────────────
JOBS_TOTAL = Counter(
    "meeting_jobs_total",
    "Total meeting processing jobs submitted",
    labelnames=["status"],  # completed | failed
)

JOBS_IN_FLIGHT = Gauge(
    "meeting_jobs_in_flight",
    "Number of meeting jobs currently being processed",
)

# ── Pre-initialize labeled metrics so they show up as 0 in Prometheus ─────────
# Without this, labeled counters/histograms only appear after the first .inc()
# call, causing Grafana to show "No data" for panels that expect these series.
def _preinit() -> None:
    JOBS_TOTAL.labels(status="completed")
    JOBS_TOTAL.labels(status="failed")
    for stage in ("ingest", "preprocess", "stt", "diarize", "llm", "guardrails", "assignment"):
        STAGE_LATENCY.labels(stage=stage)
    for reason in ("no_evidence", "invalid_assignee", "date_hallucination"):
        HALLUCINATION_FLAGS.labels(reason=reason)


_preinit()
