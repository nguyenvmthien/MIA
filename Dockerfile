FROM python:3.11-slim

# System dependencies (ffmpeg for audio, build tools for native extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source
COPY src/ ./src/
COPY .env.example ./.env.example

# Create data directories
RUN mkdir -p data/audio data/transcripts data/models

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
