FROM python:3.11-slim

# System dependencies (ffmpeg for audio, build tools for native extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching.
# A stub __init__.py lets pip resolve the package metadata without the real source.
COPY pyproject.toml ./
RUN mkdir -p src/meeting_agent && touch src/meeting_agent/__init__.py \
    && pip install --no-cache-dir -e ".[dev]" \
    && rm -rf src/meeting_agent

# Copy real source and reinstall the package (deps already cached above)
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps -e .
COPY .env.example ./.env.example

# Create data directories
RUN mkdir -p data/audio data/transcripts data/models

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
