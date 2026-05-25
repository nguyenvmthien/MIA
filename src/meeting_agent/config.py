"""Central configuration.

Defaults come from ``configs/app.example.yml`` when present. Environment
variables and ``.env`` values still override those defaults, which keeps secrets
and deployment-specific values out of the YAML file.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


def _flatten_config(data: dict[str, Any]) -> dict[str, Any]:
    """Map the assignment YAML structure to Settings field names."""
    app = data.get("app") or {}
    database = data.get("database") or {}
    redis = data.get("redis") or {}
    celery = data.get("celery") or {}
    inference = data.get("inference") or {}
    speech = data.get("speech") or {}
    tracing = data.get("tracing") or {}
    storage = data.get("storage") or {}
    monitoring = data.get("monitoring") or {}
    retraining = data.get("retraining") or {}

    mapped = {
        "database_url": database.get("url"),
        "redis_url": redis.get("url"),
        "celery_broker_url": celery.get("broker_url"),
        "celery_result_backend": celery.get("result_backend"),
        "ollama_base_url": inference.get("ollama_base_url"),
        "ollama_llm_model": inference.get("llm_model"),
        "ollama_embed_model": inference.get("embedding_model"),
        "whisper_model": speech.get("whisper_model"),
        "whisper_device": speech.get("device"),
        "whisper_compute_type": speech.get("compute_type"),
        "whisper_batch_size": speech.get("batch_size"),
        "whisper_language": speech.get("language"),
        "enable_diarization": speech.get("enable_diarization"),
        "hf_token": speech.get("hf_token"),
        "langchain_tracing_v2": tracing.get("langchain_tracing_v2"),
        "langchain_api_key": tracing.get("langchain_api_key"),
        "langchain_project": tracing.get("langchain_project"),
        "audio_storage_path": storage.get("audio_path"),
        "transcript_storage_path": storage.get("transcript_path"),
        "workers_storage_path": storage.get("workers_path"),
        "artifact_retention_days": storage.get("artifact_retention_days"),
        "raw_audio_retention_days": storage.get("raw_audio_retention_days"),
        "pii_artifact_retention_days": storage.get("pii_artifact_retention_days"),
        "log_level": app.get("log_level"),
        "max_audio_duration_hours": app.get("max_audio_duration_hours"),
        "llm_max_retries": inference.get("max_retries"),
        "task_confidence_threshold": inference.get("task_confidence_threshold"),
        "pending_meeting_timeout_minutes": app.get("pending_meeting_timeout_minutes"),
        "prometheus_endpoint": monitoring.get("prometheus_endpoint"),
        "anomaly_window_size": monitoring.get("anomaly_window_size"),
        "anomaly_z_threshold": monitoring.get("anomaly_z_threshold"),
        "retrain_min_corrections": retraining.get("min_corrections"),
        "retrain_output_dir": retraining.get("output_dir"),
    }
    return {key: value for key, value in mapped.items() if value is not None}


def _load_config_file(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Load YAML config defaults from disk.

    ``CONFIG_FILE`` or ``MEETING_AGENT_CONFIG`` can point at another YAML file.
    Missing files are tolerated so local scripts can still run without a config
    artifact checked out.
    """
    config_path = Path(
        path
        or os.environ.get("CONFIG_FILE")
        or os.environ.get("MEETING_AGENT_CONFIG")
        or "configs/app.example.yml"
    )
    if not config_path.exists():
        return {}

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
    return _flatten_config(raw)


_CONFIG_DEFAULTS = _load_config_file()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = _CONFIG_DEFAULTS.get(
        "database_url", "postgresql://meeting:meeting@localhost:5432/meeting_agent"
    )

    # Redis / Celery
    redis_url: str = _CONFIG_DEFAULTS.get("redis_url", "redis://localhost:6379/0")
    celery_broker_url: str = _CONFIG_DEFAULTS.get("celery_broker_url", "redis://localhost:6379/0")
    celery_result_backend: str = _CONFIG_DEFAULTS.get(
        "celery_result_backend", "redis://localhost:6379/1"
    )

    # Ollama
    ollama_base_url: str = _CONFIG_DEFAULTS.get("ollama_base_url", "http://localhost:11434")
    ollama_llm_model: str = _CONFIG_DEFAULTS.get("ollama_llm_model", "qwen2.5:3b")
    ollama_embed_model: str = _CONFIG_DEFAULTS.get("ollama_embed_model", "nomic-embed-text")

    # WhisperX (use "large-v3" for production quality; "base" is fast for demos)
    whisper_model: str = _CONFIG_DEFAULTS.get("whisper_model", "base")
    whisper_device: str = _CONFIG_DEFAULTS.get("whisper_device", "cpu")
    whisper_compute_type: str = _CONFIG_DEFAULTS.get("whisper_compute_type", "int8")
    whisper_batch_size: int = _CONFIG_DEFAULTS.get("whisper_batch_size", 16)
    whisper_language: str = _CONFIG_DEFAULTS.get("whisper_language", "en")

    # Pyannote
    hf_token: str = _CONFIG_DEFAULTS.get("hf_token", "")
    enable_diarization: bool = _CONFIG_DEFAULTS.get("enable_diarization", True)

    # LangSmith (optional)
    langchain_tracing_v2: bool = _CONFIG_DEFAULTS.get("langchain_tracing_v2", False)
    langchain_api_key: str = _CONFIG_DEFAULTS.get("langchain_api_key", "")
    langchain_project: str = _CONFIG_DEFAULTS.get("langchain_project", "meeting-agent")

    # Storage
    audio_storage_path: str = _CONFIG_DEFAULTS.get("audio_storage_path", "./data/audio")
    transcript_storage_path: str = _CONFIG_DEFAULTS.get(
        "transcript_storage_path", "./data/transcripts"
    )
    workers_storage_path: str = _CONFIG_DEFAULTS.get("workers_storage_path", "./data/workers.json")
    artifact_retention_days: int = _CONFIG_DEFAULTS.get("artifact_retention_days", 30)
    raw_audio_retention_days: int = _CONFIG_DEFAULTS.get("raw_audio_retention_days", 7)
    pii_artifact_retention_days: int = _CONFIG_DEFAULTS.get("pii_artifact_retention_days", 14)

    # App
    log_level: str = _CONFIG_DEFAULTS.get("log_level", "INFO")
    max_audio_duration_hours: int = _CONFIG_DEFAULTS.get("max_audio_duration_hours", 4)
    llm_max_retries: int = _CONFIG_DEFAULTS.get("llm_max_retries", 3)
    task_confidence_threshold: float = _CONFIG_DEFAULTS.get("task_confidence_threshold", 0.6)
    pending_meeting_timeout_minutes: int = _CONFIG_DEFAULTS.get(
        "pending_meeting_timeout_minutes", 60
    )

    # Monitoring / MLOps
    prometheus_endpoint: str = _CONFIG_DEFAULTS.get("prometheus_endpoint", "/metrics")
    anomaly_window_size: int = _CONFIG_DEFAULTS.get("anomaly_window_size", 20)
    anomaly_z_threshold: float = _CONFIG_DEFAULTS.get("anomaly_z_threshold", 3.0)
    retrain_min_corrections: int = _CONFIG_DEFAULTS.get("retrain_min_corrections", 50)
    retrain_output_dir: str = _CONFIG_DEFAULTS.get(
        "retrain_output_dir", "models/qwen-meeting-latest"
    )


settings = Settings()
