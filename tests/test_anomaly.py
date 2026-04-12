"""Tests for the rolling-window anomaly detector."""

import pytest

from meeting_agent.monitoring.anomaly import _RollingWindow, check_run

# ── _RollingWindow ────────────────────────────────────────────────────────────

def test_rolling_window_mean():
    w = _RollingWindow()
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        w.add(v)
    assert w.mean() == pytest.approx(3.0)


def test_rolling_window_stddev():
    w = _RollingWindow()
    for v in [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]:
        w.add(v)
    assert w.stddev() > 0


def test_rolling_window_empty_mean():
    assert _RollingWindow().mean() == 0.0


def test_rolling_window_single_no_stddev():
    w = _RollingWindow()
    w.add(5.0)
    assert w.stddev() == 0.0


def test_rolling_window_not_enough_data_no_anomaly():
    """Fewer than 5 points — never flag anomaly."""
    w = _RollingWindow()
    for v in [1.0, 2.0, 3.0]:
        w.add(v)
    assert w.is_anomaly(1000.0) is False


def test_rolling_window_uniform_no_anomaly():
    """All same values → stddev=0 → never flag anomaly."""
    w = _RollingWindow()
    for _ in range(10):
        w.add(5.0)
    assert w.is_anomaly(5.0) is False
    assert w.is_anomaly(5.1) is False


def test_rolling_window_detects_outlier():
    w = _RollingWindow()
    # Build a window with real variance around 5.0 ± 1.0
    for v in [4.0, 5.0, 6.0, 5.0, 4.5, 5.5, 4.8, 5.2, 4.9, 5.1]:
        w.add(v)
    # 1000 is >> 3σ away from mean ~5.0 with std ~0.5
    assert w.is_anomaly(1000.0) is True


# ── check_run ─────────────────────────────────────────────────────────────────

def test_check_run_all_clear():
    anomalies = check_run(
        hallucination_flags=0,
        tasks_extracted=5,
        schema_failures=0,
        llm_latency_ms=3000,
    )
    assert isinstance(anomalies, list)


def test_check_run_hard_threshold_hallucination():
    """Hallucination rate > 10% must trigger a HARD_THRESHOLD anomaly."""
    anomalies = check_run(
        hallucination_flags=3,
        tasks_extracted=5,   # rate = 0.6 → way above 0.10 threshold
        schema_failures=0,
        llm_latency_ms=3000,
    )
    assert any("hallucination_rate" in a for a in anomalies)
    assert any("HARD_THRESHOLD" in a for a in anomalies)


def test_check_run_hard_threshold_schema_failures():
    """More than 3 schema failures must trigger HARD_THRESHOLD."""
    anomalies = check_run(
        hallucination_flags=0,
        tasks_extracted=5,
        schema_failures=5,
        llm_latency_ms=3000,
    )
    assert any("schema_failures" in a for a in anomalies)


def test_check_run_returns_list():
    result = check_run(0, 0, 0, 0)
    assert isinstance(result, list)
