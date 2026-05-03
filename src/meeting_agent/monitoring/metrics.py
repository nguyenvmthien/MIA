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

LLM_CHUNKS = Counter(
    "meeting_llm_chunks_total",
    "Total number of transcript chunks processed through the LLM",
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

# ── Pipeline quality ──────────────────────────────────────────────────────────
GUARDRAILS_DURATION = Histogram(
    "meeting_guardrails_duration_seconds",
    "Duration of the guardrails validation step in seconds",
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 600],
)

CACHE_HITS = Counter(
    "meeting_cache_hits_total",
    "Number of LLM Redis prompt cache hits",
)

CACHE_MISSES = Counter(
    "meeting_cache_misses_total",
    "Number of LLM Redis prompt cache misses",
)

ASSIGNEE_RESOLVED = Counter(
    "meeting_assignee_resolved_total",
    "Assignee resolution outcomes",
    labelnames=["result"],  # matched | unresolved | fuzzy
)

PIPELINE_ERRORS = Counter(
    "meeting_error_total",
    "Pipeline errors by stage and error type",
    labelnames=["stage", "error_type"],
)

# ── Business metrics ──────────────────────────────────────────────────────────
AUDIO_DURATION = Histogram(
    "meeting_audio_duration_seconds",
    "Actual meeting audio duration in seconds",
    buckets=[60, 300, 600, 1200, 1800, 3600],
)

PARTICIPANTS_COUNT = Histogram(
    "meeting_participants_count",
    "Number of participants per meeting",
    buckets=[1, 2, 3, 4, 5, 8, 10, 15, 20],
)

TASKS_PER_MEETING = Histogram(
    "meeting_tasks_per_meeting",
    "Number of tasks extracted per meeting",
    buckets=[0, 1, 2, 3, 5, 8, 10, 15, 20],
)

FEEDBACK_SUBMITTED = Counter(
    "meeting_feedback_submitted_total",
    "User feedback submissions",
    labelnames=["type"],  # correction | false_positive | missing
)

CALENDAR_EVENTS_CREATED = Counter(
    "meeting_calendar_events_created_total",
    "Total Google Calendar events created from action items",
)

# ── RAG metrics ───────────────────────────────────────────────────────────────
RAG_QUERIES = Counter(
    "meeting_rag_queries_total",
    "RAG speaker index queries",
    labelnames=["result"],  # hit | miss
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
    for result in ("matched", "unresolved", "fuzzy"):
        ASSIGNEE_RESOLVED.labels(result=result)
    for stage in ("ingest", "preprocess", "stt", "llm", "guardrails", "assignment"):
        for error_type in ("exception", "timeout", "validation"):
            PIPELINE_ERRORS.labels(stage=stage, error_type=error_type)
    for result in ("hit", "miss"):
        RAG_QUERIES.labels(result=result)
    for feedback_type in ("correction", "false_positive", "missing"):
        FEEDBACK_SUBMITTED.labels(type=feedback_type)


_preinit()
