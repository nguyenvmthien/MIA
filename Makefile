.PHONY: help up down dev restart-api restart-worker worker-rebuild logs deploy deploy-update migrate migrate-prod migrate-new db-shell test test-cov lint lint-fix hygiene dataset-smoke benchmark hf-dataset web-lint web-build mlops-smoke mlops-up mlops-logs train-image train-baseline retrain-check retrain-force backfill-transcripts cleanup-artifacts deploy-promoted-model synthetic export-sft export-rlhf export-finetune

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
	ruff check src/ tests/ scripts/

lint-fix: ## Run ruff with auto-fix
	ruff check --fix src/ tests/ scripts/

hygiene: ## Check for tracked generated files and local secrets
	python3 scripts/check_repo_hygiene.py

dataset-smoke: ## Verify raw/SFT JSONL compatibility with training loader
	$(PYTHONPATH) python3 scripts/dataset_compat_smoke.py

benchmark: ## Run baseline benchmark (MODEL=qwen2.5:3b, GOLD=data/eval/gold_synthetic_205.jsonl, LIMIT=100)
	$(PYTHONPATH) python3 scripts/run_benchmark.py \
		--gold $${GOLD:-data/eval/gold_synthetic_205.jsonl} \
		--baseline-model $${MODEL:-qwen2.5:3b} \
		--limit $${LIMIT:-100} \
		$(if $(CANDIDATE),--candidate-model $(CANDIDATE),)

hf-dataset: ## Prepare local Hugging Face dataset export under hf_dataset/
	python3 scripts/prepare_hf_dataset.py

web-lint: ## Run Next.js/ESLint checks
	cd web && npm run lint

web-build: ## Build the Next.js app
	cd web && npm run build

mlops-smoke: hygiene dataset-smoke ## Run local MLOps smoke checks

mlops-up: ## Start GPU-ready MLOps services: beat, trainer, MLflow
	$(COMPOSE) --profile mlops up -d --build beat trainer mlflow

mlops-logs: ## Tail MLOps scheduler/trainer logs
	$(COMPOSE) --profile mlops logs -f beat trainer mlflow

train-image: ## Build GPU training image with QLoRA dependencies
	$(COMPOSE) --profile mlops build trainer

train-baseline: ## Train lightweight baseline action-turn detector into models/
	$(PYTHONPATH) python3 -m meeting_agent.mlops.train_baseline_detector \
		--gold data/eval/gold_synthetic_205.jsonl \
		--out-dir models/baseline-action-detector

retrain-check: ## Check whether retraining threshold is met
	$(PYTHONPATH) python3 -m meeting_agent.mlops.retrain --check

retrain-force: ## Force retrain through local Python environment
	$(PYTHONPATH) python3 -m meeting_agent.mlops.retrain --force

backfill-transcripts: ## Backfill normalized transcript_turns from legacy JSONB (APPLY=1 to write)
	$(PYTHONPATH) python3 scripts/backfill_transcript_turns.py $(if $(APPLY),--apply,)

cleanup-artifacts: ## Apply artifact retention cleanup (APPLY=1 to write)
	$(PYTHONPATH) python3 scripts/cleanup_artifacts.py $(if $(APPLY),--apply,)

deploy-promoted-model: ## Deploy promotion manifest to Ollama (APPLY=1 to run ollama create)
	python3 scripts/deploy_promoted_model.py $(if $(APPLY),--apply,)

# ── Data pipeline ─────────────────────────────────────────────────────────────

synthetic: ## Generate synthetic meetings (requires GEMINI_API_KEY)
	$(PYTHONPATH) python3 -m meeting_agent.mlops.data_pipeline.synthetic \
		--count 200 --provider gemini \
		--out data/training/synthetic_v1_$$(date +%Y%m%d).jsonl

export-sft: ## Export SFT training data from DB
	$(PYTHONPATH) python3 -m meeting_agent.mlops.data_pipeline.collect_interactions \
		--format sft --out data/training/sft_$$(date +%Y%m%d).jsonl

export-rlhf: ## Export RLHF preference pairs from DB
	$(PYTHONPATH) python3 -m meeting_agent.mlops.data_pipeline.collect_interactions \
		--format rlhf --out data/training/rlhf_$$(date +%Y%m%d).jsonl

export-finetune: ## Export fine-tuning JSONL from DB (legacy format)
	$(PYTHONPATH) python3 -m meeting_agent.mlops.data_pipeline.export_for_finetuning \
		--out data/training/finetuning_$$(date +%Y%m%d).jsonl --min-corrections 1
