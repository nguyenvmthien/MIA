FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    git \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[dev]"

COPY alembic/ ./alembic/
COPY alembic.ini ./

RUN mkdir -p data/audio data/transcripts data/tokens data/models data/training

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
