.PHONY: help up down dev prod migrate logs test lint build worker-rebuild

COMPOSE      = docker compose -f docker-compose.yml
COMPOSE_PROD = $(COMPOSE) -f docker-compose.prod.yml
PYTHONPATH   = PYTHONPATH=src

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Dev stack ─────────────────────────────────────────────────────────────────

up: ## Start full dev stack (docker compose up -d)
	$(COMPOSE) up -d

down: ## Stop all containers
	$(COMPOSE) down

dev: ## Start dev stack and tail API logs
	$(COMPOSE) up -d
	$(COMPOSE) logs -f api worker

restart-api: ## Rebuild and restart API container only
	$(COMPOSE) up -d --build api

restart-worker: ## Rebuild and restart worker container only
	$(COMPOSE) up -d --build worker

worker-rebuild: ## Rebuild worker image from scratch (no cache)
	$(COMPOSE) build --no-cache worker
	$(COMPOSE) up -d worker

logs: ## Tail API + worker logs
	$(COMPOSE) logs -f api worker

# ── Production ────────────────────────────────────────────────────────────────

deploy: ## Deploy production stack (requires .env with all prod values)
	$(COMPOSE_PROD) pull
	$(COMPOSE_PROD) up -d --build

deploy-update: ## Zero-downtime update: rebuild API + worker, keep DB/Redis/Ollama running
	$(COMPOSE_PROD) up -d --build --no-deps api worker

# ── Database ──────────────────────────────────────────────────────────────────

migrate: ## Run Alembic migrations (dev)
	$(COMPOSE) run --rm migrator alembic upgrade head

migrate-prod: ## Run Alembic migrations (prod)
	$(COMPOSE_PROD) run --rm migrator alembic upgrade head

migrate-new: ## Create a new Alembic migration (MSG="description")
	$(COMPOSE) run --rm migrator alembic revision --autogenerate -m "$(MSG)"

db-shell: ## Open psql shell
	docker exec -it meeting-agent-postgres-1 psql -U $${POSTGRES_USER:-meeting} -d $${POSTGRES_DB:-meeting_agent}

# ── Tests & Linting ───────────────────────────────────────────────────────────

test: ## Run test suite
	$(PYTHONPATH) pytest tests/ -v

test-cov: ## Run tests with coverage report
	$(PYTHONPATH) pytest tests/ --cov=meeting_agent --cov-report=term-missing

lint: ## Run ruff linter
	ruff check src/ tests/

lint-fix: ## Run ruff with auto-fix
	ruff check --fix src/ tests/

# ── Data pipeline ─────────────────────────────────────────────────────────────

synthetic: ## Generate synthetic meetings (requires GEMINI_API_KEY)
	$(PYTHONPATH) python data_pipeline/synthetic.py \
		--count 200 --provider gemini \
		--out data/training/synthetic_v1_$$(date +%Y%m%d).jsonl

export-sft: ## Export SFT training data from DB
	$(PYTHONPATH) python data_pipeline/collect_interactions.py \
		--format sft --out data/training/sft_$$(date +%Y%m%d).jsonl

export-rlhf: ## Export RLHF preference pairs from DB
	$(PYTHONPATH) python data_pipeline/collect_interactions.py \
		--format rlhf --out data/training/rlhf_$$(date +%Y%m%d).jsonl

export-finetune: ## Export fine-tuning JSONL from DB (legacy format)
	$(PYTHONPATH) python data_pipeline/export_for_finetuning.py \
		--out data/training/finetuning_$$(date +%Y%m%d).jsonl --min-corrections 1
