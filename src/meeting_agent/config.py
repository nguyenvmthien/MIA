"""Central configuration via pydantic-settings — reads from env / .env file."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql://meeting:meeting@localhost:5432/meeting_agent"

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "qwen2.5:3b"
    ollama_embed_model: str = "nomic-embed-text"

    # WhisperX (use "large-v3" for production quality; "base" is fast for demos)
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_batch_size: int = 16
    whisper_language: str = "en"

    # Pyannote
    hf_token: str = ""
    enable_diarization: bool = True

    # LangSmith (optional)
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "meeting-agent"

    # Storage
    audio_storage_path: str = "./data/audio"
    transcript_storage_path: str = "./data/transcripts"
    workers_storage_path: str = "./data/workers.json"
    artifact_retention_days: int = 30
    raw_audio_retention_days: int = 7
    pii_artifact_retention_days: int = 14

    # App
    log_level: str = "INFO"
    max_audio_duration_hours: int = 4
    llm_max_retries: int = 3
    task_confidence_threshold: float = 0.6
    pending_meeting_timeout_minutes: int = 10


settings = Settings()
