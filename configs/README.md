# Configuration

`app.example.yml` is loaded by `src/meeting_agent/config.py` as the default runtime configuration.

Environment variables and `.env` values override the YAML defaults, so secrets and deployment-specific values still stay outside Git. Docker Compose sets `CONFIG_FILE=/app/configs/app.example.yml` and mounts this directory read-only into the API, worker, beat, and trainer containers.
