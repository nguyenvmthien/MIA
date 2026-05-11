#!/usr/bin/env bash
# run.sh — quick-start script for Meeting Agent
# Usage:
#   ./run.sh            → start via Docker Compose (default)
#   ./run.sh prod       → start with production overrides
#   ./run.sh stop       → stop and remove containers
#   ./run.sh clean      → stop + wipe all volumes (data, DB, models)

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
        warn "  HF_TOKEN=hf_your_token_here"
        warn "  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET  (for calendar sync)"
        echo ""
        read -rp "Press Enter to continue with default values, or Ctrl-C to edit .env first..."
    else
        success ".env already exists"
    fi
}

check_docker() {
    command -v docker &>/dev/null     || error "Docker not found. Install from https://docs.docker.com/get-docker/"
    docker info &>/dev/null            || error "Docker daemon is not running. Start Docker Desktop and retry."
    docker compose version &>/dev/null || error "docker compose not available. Install Docker Desktop >= 4.x"
}

# ══════════════════════════════════════════════════════════════════════════════
# DOCKER MODE (default — dev)
# ══════════════════════════════════════════════════════════════════════════════
run_docker() {
    info "Starting Meeting Agent via Docker Compose..."
    check_docker
    setup_env

    info "Building images (first run may take a few minutes)..."
    docker compose build --quiet

    info "Starting all services..."
    docker compose up -d

    echo ""
    success "Services started! Waiting for health checks..."
    sleep 8

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Service      URL"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Web UI       http://localhost:3001"
    echo "  API          http://localhost:8000"
    echo "  API docs     http://localhost:8000/docs"
    echo "  Grafana      http://localhost:3000   (admin / admin)"
    echo "  pgAdmin      http://localhost:5050"
    echo "  Prometheus   http://localhost:9090"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    warn "Ollama is pulling qwen2.5:3b and nomic-embed-text on first start."
    warn "The API may return 503 for ~60s while models download."
    echo ""
    info "Tail logs:  docker compose logs -f api worker"
    info "Stop:       ./run.sh stop"
    info "Wipe all:   ./run.sh clean"
}

# ══════════════════════════════════════════════════════════════════════════════
# PROD MODE
# ══════════════════════════════════════════════════════════════════════════════
run_prod() {
    info "Starting Meeting Agent in production mode..."
    check_docker
    setup_env

    info "Building images..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml build --quiet

    info "Running DB migrations..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm migrator

    info "Starting all services..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

    success "Production stack started."
    info "Tail logs:  docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api worker"
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
    prod)       run_prod   ;;
    stop)       run_stop   ;;
    clean)      run_clean  ;;
    *)
        echo "Usage: $0 [docker|prod|stop|clean]"
        echo "  docker  — start via Docker Compose, dev mode (default)"
        echo "  prod    — start with production overrides"
        echo "  stop    — stop all services"
        echo "  clean   — stop + wipe all volumes"
        exit 1
        ;;
esac
