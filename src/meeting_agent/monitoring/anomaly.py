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

log = logging.getLogger(__name__)

ANOMALY_EVENTS = Counter(
    "meeting_anomaly_events_total",
    "Number of anomaly events detected",
    labelnames=["metric"],
)

# Rolling window size for computing mean/stddev
_WINDOW = 20


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

    def is_anomaly(self, v: float, z_threshold: float = 3.0) -> bool:
        """Return True if v is more than z_threshold standard deviations from mean."""
        if len(self.values) < 5:
            return False  # not enough data yet
        std = self.stddev()
        if std == 0:
            return False
        return abs(v - self.mean()) / std > z_threshold


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
