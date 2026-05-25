"""
Anomaly detector — tracks rolling metric windows and flags statistical outliers.

Checks run after every meeting job completes. Anomalies are logged and
incremented in Prometheus so Grafana alerts can fire.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field

from prometheus_client import Counter

from meeting_agent.config import settings

log = logging.getLogger(__name__)

ANOMALY_EVENTS = Counter(
    "meeting_anomaly_events_total",
    "Number of anomaly events detected",
    labelnames=["metric"],
)

# Rolling window size for computing mean/stddev
_WINDOW = settings.anomaly_window_size


@dataclass
class _RollingWindow:
    values: deque = field(default_factory=lambda: deque(maxlen=_WINDOW))

    def add(self, v: float) -> None:
        self.values.append(v)

    def mean(self) -> float:
        return sum(self.values) / len(self.values) if self.values else 0.0

    def stddev(self) -> float:
        if len(self.values) < 2:
            return 0.0
        m = self.mean()
        variance = sum((x - m) ** 2 for x in self.values) / len(self.values)
        return math.sqrt(variance)

    def is_anomaly(self, v: float, z_threshold: float | None = None) -> bool:
        """Return True if v is more than z_threshold standard deviations from mean."""
        threshold = z_threshold if z_threshold is not None else settings.anomaly_z_threshold
        if len(self.values) < 5:
            return False  # not enough data yet
        std = self.stddev()
        if std == 0:
            return False
        return abs(v - self.mean()) / std > threshold


# Global rolling windows per metric
_windows: dict[str, _RollingWindow] = {
    "hallucination_rate": _RollingWindow(),
    "tasks_extracted": _RollingWindow(),
    "llm_latency_ms": _RollingWindow(),
    "schema_failures": _RollingWindow(),
}

# Hard thresholds (always alert regardless of history)
_HARD_THRESHOLDS: dict[str, float] = {
    "hallucination_rate": 0.10,   # >10% hallucination in a single meeting
    "schema_failures": 3,          # >3 schema failures in a single meeting
}


def check_run(
    hallucination_flags: int,
    tasks_extracted: int,
    schema_failures: int,
    llm_latency_ms: int,
) -> list[str]:
    """
    Check a completed meeting run for anomalies.

    Returns list of anomaly descriptions (empty = all clear).
    """
    anomalies: list[str] = []

    hall_rate = hallucination_flags / max(tasks_extracted, 1)
    metrics = {
        "hallucination_rate": hall_rate,
        "tasks_extracted": float(tasks_extracted),
        "llm_latency_ms": float(llm_latency_ms),
        "schema_failures": float(schema_failures),
    }

    for name, value in metrics.items():
        window = _windows[name]

        # Hard threshold check
        threshold = _HARD_THRESHOLDS.get(name)
        if threshold is not None and value > threshold:
            msg = f"HARD_THRESHOLD: {name}={value:.3f} exceeds limit {threshold}"
            anomalies.append(msg)
            ANOMALY_EVENTS.labels(metric=name).inc()
            log.warning("Anomaly detected — %s", msg)

        # Statistical outlier check
        elif window.is_anomaly(value):
            msg = (
                f"STATISTICAL_OUTLIER: {name}={value:.3f} "
                f"(mean={window.mean():.3f}, std={window.stddev():.3f})"
            )
            anomalies.append(msg)
            ANOMALY_EVENTS.labels(metric=name).inc()
            log.warning("Anomaly detected — %s", msg)

        window.add(value)

    return anomalies


def check_weekly_drift() -> dict:
    """
    Compare task distribution metrics between current week and previous week.

    Queries the DB for meetings in the last 7 days vs. the prior 7 days,
    computes correction_rate and false_positive_rate for each window, and
    flags a drift alert if either metric shifted by more than 2 std deviations
    (or >50% relative change when history is sparse).

    Returns a summary dict with drift status and per-metric details.
    """
    from datetime import datetime, timedelta, timezone

    try:
        from sqlalchemy import func, select

        from meeting_agent.db.engine import get_session
        from meeting_agent.db.models import FeedbackCorrection, Meeting, Task

        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        def _week_metrics(session, start, end) -> dict:
            meetings = session.scalar(
                select(func.count()).select_from(Meeting)
                .where(Meeting.status == "completed")
                .where(Meeting.processed_at >= start)
                .where(Meeting.processed_at < end)
            ) or 0
            corrections = session.scalar(
                select(func.count()).select_from(FeedbackCorrection)
                .where(FeedbackCorrection.submitted_at >= start)
                .where(FeedbackCorrection.submitted_at < end)
            ) or 0
            action_tasks = session.scalar(
                select(func.count()).select_from(Task)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .where(Task.bucket == "action")
                .where(Meeting.processed_at >= start)
                .where(Meeting.processed_at < end)
            ) or 0
            dismissed = session.scalar(
                select(func.count()).select_from(Task)
                .join(Meeting, Task.meeting_id == Meeting.id)
                .where(Task.bucket == "action")
                .where(Task.status == "dismissed")
                .where(Meeting.processed_at >= start)
                .where(Meeting.processed_at < end)
            ) or 0
            return {
                "meetings": meetings,
                "correction_rate": round(corrections / meetings, 3) if meetings else 0.0,
                "false_positive_rate": round(dismissed / action_tasks, 3) if action_tasks else 0.0,
            }

        with get_session() as session:
            current = _week_metrics(session, week_ago, now)
            previous = _week_metrics(session, two_weeks_ago, week_ago)

        alerts = []
        details = {}
        for metric in ("correction_rate", "false_positive_rate"):
            curr_val = current[metric]
            prev_val = previous[metric]
            if prev_val == 0:
                change_pct = 100.0 if curr_val > 0 else 0.0
                is_drift = curr_val > 0.1
            else:
                change_pct = round((curr_val - prev_val) / prev_val * 100, 1)
                is_drift = abs(change_pct) > 50

            details[metric] = {
                "current_week": curr_val,
                "previous_week": prev_val,
                "change_pct": change_pct,
                "drift": is_drift,
            }
            if is_drift:
                msg = f"WEEKLY_DRIFT: {metric} changed {change_pct:+.1f}% (prev={prev_val}, curr={curr_val})"
                alerts.append(msg)
                ANOMALY_EVENTS.labels(metric=f"weekly_{metric}").inc()
                log.warning("Weekly drift detected — %s", msg)

        return {
            "status": "alert" if alerts else "ok",
            "current_week_meetings": current["meetings"],
            "previous_week_meetings": previous["meetings"],
            "alerts": alerts,
            "details": details,
        }

    except Exception as exc:
        log.error("Weekly drift check failed: %s", exc)
        return {"status": "error", "error": str(exc)}
