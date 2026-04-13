# System Overview

## Kiến trúc tổng quan

![System Architecture](diagrams/system_architecture.svg)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI | Streamlit |
| API | FastAPI |
| Async Queue | Celery + Redis |
| ASR + Diarization | WhisperX + Pyannote |
| LLM | Qwen2.5-3B via Ollama |
| Vector Search | FAISS |
| Storage | PostgreSQL |
| Monitoring | Prometheus + Grafana + LangSmith |
| Training | Unsloth + MLflow |
| CI/CD | GitHub Actions + Docker |
