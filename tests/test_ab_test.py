import importlib


def test_ab_test_requires_explicit_runtime_enablement(monkeypatch, tmp_path):
    ab_test = importlib.import_module("meeting_agent.mlops.ab_test")
    monkeypatch.setattr(ab_test, "_STATE_FILE", tmp_path / ".ab_test_state.json")
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "champion")
    monkeypatch.delenv("AB_TEST_ENABLED", raising=False)

    ab_test.save_state({
        "active": True,
        "experiment_id": "ab_test",
        "model_a": "champion",
        "model_b": "challenger",
        "traffic_b": 1.0,
        "started_at": "2026-05-13T00:00:00+00:00",
    })

    assignment = ab_test.get_assignment_for_meeting("meeting-1")

    assert assignment["enabled"] is False
    assert assignment["model"] == "champion"


def test_ab_test_assignment_includes_variant_when_enabled(monkeypatch, tmp_path):
    ab_test = importlib.import_module("meeting_agent.mlops.ab_test")
    monkeypatch.setattr(ab_test, "_STATE_FILE", tmp_path / ".ab_test_state.json")
    monkeypatch.setenv("AB_TEST_ENABLED", "true")

    ab_test.save_state({
        "active": True,
        "experiment_id": "ab_test",
        "model_a": "champion",
        "model_b": "challenger",
        "traffic_b": 1.0,
        "started_at": "2026-05-13T00:00:00+00:00",
    })

    assignment = ab_test.get_assignment_for_meeting("meeting-1", default_model="champion")

    assert assignment["enabled"] is True
    assert assignment["experiment_id"] == "ab_test"
    assert assignment["model"] == "challenger"
    assert assignment["variant"] == "B"
