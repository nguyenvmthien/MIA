from pathlib import Path

from meeting_agent.config import Settings, _load_config_file


def test_yaml_config_file_maps_to_settings_fields(tmp_path: Path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
app:
  log_level: DEBUG
  max_audio_duration_hours: 2
database:
  url: postgresql://example/db
redis:
  url: redis://example:6379/0
celery:
  broker_url: redis://broker:6379/0
  result_backend: redis://backend:6379/1
inference:
  llm_model: test-model
  embedding_model: test-embed
  ollama_base_url: http://ollama:11434
  task_confidence_threshold: 0.75
speech:
  whisper_model: tiny
  batch_size: 4
monitoring:
  anomaly_window_size: 9
  anomaly_z_threshold: 2.5
retraining:
  min_corrections: 12
  output_dir: models/test
""",
        encoding="utf-8",
    )

    defaults = _load_config_file(config_path)
    settings = Settings(**defaults)

    assert settings.database_url == "postgresql://example/db"
    assert settings.redis_url == "redis://example:6379/0"
    assert settings.celery_broker_url == "redis://broker:6379/0"
    assert settings.ollama_llm_model == "test-model"
    assert settings.whisper_model == "tiny"
    assert settings.whisper_batch_size == 4
    assert settings.task_confidence_threshold == 0.75
    assert settings.anomaly_window_size == 9
    assert settings.anomaly_z_threshold == 2.5
    assert settings.retrain_min_corrections == 12
    assert settings.retrain_output_dir == "models/test"


def test_environment_overrides_yaml_defaults(monkeypatch):
    monkeypatch.setenv("OLLAMA_LLM_MODEL", "env-model")
    monkeypatch.setenv("ANOMALY_WINDOW_SIZE", "31")

    settings = Settings()

    assert settings.ollama_llm_model == "env-model"
    assert settings.anomaly_window_size == 31
