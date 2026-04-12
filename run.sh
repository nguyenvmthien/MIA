#!/usr/bin/env bash
# run.sh — scratch-start script for Meeting Agent
# Usage:
#   ./run.sh            → Docker Compose (recommended, starts everything)
#   ./run.sh local      → Local dev mode (no Docker)
#   ./run.sh stop       → Stop and remove Docker containers
#   ./run.sh clean      → Stop + wipe all volumes (data, models, DB)

set -euo pipefail

MODE="${1:-docker}"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── .env setup ────────────────────────────────────────────────────────────────
setup_env() {
    if [[ ! -f .env ]]; then
        info "No .env found — copying from .env.example"
        cp .env.example .env
        warn "Edit .env and set at minimum:"
        warn "  HF_TOKEN=hf_your_token_here   (free: https://huggingface.co/pyannote/speaker-diarization-3.1)"
        warn "  LANGCHAIN_API_KEY=             (optional — comment out to disable tracing)"
        echo ""
        read -rp "Press Enter to continue with default values, or Ctrl-C to edit .env first..."
    else
        success ".env already exists"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# DOCKER MODE (default)
# ══════════════════════════════════════════════════════════════════════════════
run_docker() {
    info "Starting Meeting Agent via Docker Compose..."
    echo ""

    # Check Docker
    command -v docker &>/dev/null || error "Docker not found. Install from https://docs.docker.com/get-docker/"
    docker info &>/dev/null        || error "Docker daemon is not running. Start Docker Desktop and retry."
    command -v docker &>/dev/null && docker compose version &>/dev/null || \
        error "docker compose not available. Install Docker Desktop >= 4.x"

    setup_env

    info "Building images and pulling dependencies (first run may take ~5 min)..."
    docker compose build --quiet

    info "Starting all services..."
    docker compose up -d

    echo ""
    success "Services started! Waiting for health checks..."
    sleep 10

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Service      URL                   Credentials"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  API          http://localhost:8000  —"
    echo "  API docs     http://localhost:8000/docs"
    echo "  Prometheus   http://localhost:9090  —"
    echo "  Grafana      http://localhost:3000  admin / admin"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    warn "Ollama is pulling qwen2.5:3b and nomic-embed-text on first start."
    warn "The API may return 503 for ~60s while models download."
    echo ""
    info "Tail logs:  docker compose logs -f api worker ollama"
    info "Stop:       ./run.sh stop"
    info "Wipe all:   ./run.sh clean"
}

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL DEV MODE
# ══════════════════════════════════════════════════════════════════════════════
run_local() {
    info "Starting Meeting Agent in local dev mode (no Docker)..."
    echo ""

    # ── System prerequisites ──────────────────────────────────────────────────
    info "Checking system prerequisites..."

    python3 --version &>/dev/null || error "Python 3 not found. Install Python 3.10+."
    PY_VER=$(python3 -c "import sys; print(sys.version_info.minor)")
    [[ "$PY_VER" -ge 10 ]] || error "Python 3.10+ required (found 3.${PY_VER})."
    success "Python $(python3 --version)"

    command -v ffmpeg &>/dev/null || {
        warn "ffmpeg not found."
        if [[ "$(uname)" == "Darwin" ]]; then
            info "Installing ffmpeg via Homebrew..."
            brew install ffmpeg
        else
            error "Install ffmpeg: sudo apt install ffmpeg"
        fi
    }
    success "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"

    command -v ollama &>/dev/null || {
        error "Ollama not found. Download from https://ollama.com and re-run."
    }
    success "Ollama found"

    # ── Ollama models ─────────────────────────────────────────────────────────
    info "Pulling Ollama models (skipped if already cached)..."
    ollama pull qwen2.5:3b
    ollama pull nomic-embed-text
    success "Ollama models ready"

    # ── Python environment ────────────────────────────────────────────────────
    info "Setting up Python virtual environment..."
    if [[ ! -d .venv ]]; then
        python3 -m venv .venv
        success "Created .venv"
    else
        success ".venv already exists"
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate

    info "Installing Python dependencies..."
    pip install --quiet --upgrade pip
    pip install --quiet -e ".[dev]"
    success "Python packages installed"

    # ── .env ──────────────────────────────────────────────────────────────────
    setup_env

    # ── Data directories ──────────────────────────────────────────────────────
    mkdir -p data/audio data/transcripts data/models data/training data/eval
    success "Data directories created"

    # ── External services check ───────────────────────────────────────────────
    echo ""
    warn "External services required (start these separately if not running):"
    warn "  PostgreSQL:  docker run -d -p 5432:5432 -e POSTGRES_USER=meeting -e POSTGRES_PASSWORD=meeting -e POSTGRES_DB=meeting_agent postgres:16-alpine"
    warn "  Redis:       docker run -d -p 6379:6379 redis:7-alpine"
    warn "  Ollama:      ollama serve  (in a separate terminal)"
    echo ""
    read -rp "Are PostgreSQL, Redis, and Ollama running? [y/N] " CONFIRM
    [[ "$CONFIRM" =~ ^[Yy]$ ]] || { warn "Start the services above, then re-run ./run.sh local"; exit 0; }

    # ── Start API ─────────────────────────────────────────────────────────────
    echo ""
    success "Starting API server..."
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  API:      http://localhost:8000"
    echo "  API docs: http://localhost:8000/docs"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    meeting-agent serve --reload
}

# ══════════════════════════════════════════════════════════════════════════════
# STOP / CLEAN
# ══════════════════════════════════════════════════════════════════════════════
run_stop() {
    info "Stopping Docker Compose services..."
    docker compose down
    success "All services stopped"
}

run_clean() {
    warn "This will DELETE all volumes: Postgres data, Ollama models, Prometheus, Grafana."
    read -rp "Are you sure? [y/N] " CONFIRM
    [[ "$CONFIRM" =~ ^[Yy]$ ]] || { info "Aborted."; exit 0; }
    docker compose down -v
    success "All containers and volumes removed"
}

# ══════════════════════════════════════════════════════════════════════════════
# DISPATCH
# ══════════════════════════════════════════════════════════════════════════════
case "$MODE" in
    docker|"")  run_docker ;;
    local)      run_local  ;;
    stop)       run_stop   ;;
    clean)      run_clean  ;;
    *)
        echo "Usage: $0 [docker|local|stop|clean]"
        echo "  docker  — start via Docker Compose (default)"
        echo "  local   — local dev mode without Docker"
        echo "  stop    — stop Docker Compose services"
        echo "  clean   — stop + wipe all volumes"
        exit 1
        ;;
esac
