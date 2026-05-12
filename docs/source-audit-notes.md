# Source Audit And Remediation Plan

Date: 2026-05-12

Scope:
- Backend API, pipeline, persistence, frontend contracts, MLOps scripts, CI, and repo hygiene.
- Verification performed locally with unit tests and lint.

## Executive Summary

The project has a solid end-to-end shape, but several parts should be fixed before production-style use:

- Backend API trust boundaries are not enforced.
- User/meeting ownership is not modeled in persistence.
- Some important application state is stored in local JSON files instead of Postgres.
- Raw ASR and model artifacts are not stored in an auditable way.
- MLOps data contracts are inconsistent across export, train, evaluation, and retraining.
- CI does not currently cover frontend build, dataset compatibility, migrations, or hygiene checks.
- Local/generated/PII-like artifacts are tracked or present in the repo workspace.

Recommended implementation order:

1. Add backend auth and ownership model.
2. Move worker roster and calendar sync records into Postgres.
3. Normalize transcript/artifact persistence.
4. Fix upload validation, prompt sanitization, and metrics double-counting.
5. Unify MLOps dataset schemas and retraining/evaluation gates.
6. Expand CI and clean repo hygiene.

## Severity Legend

- P0: Security, privacy, or data ownership issue. Fix before broader use.
- P1: Correctness, reliability, or production workflow issue.
- P2: Maintainability, observability, or developer-experience issue.
- P3: Cleanup or documentation improvement.

## P0 Issues

### P0-1 Backend API Lacks Authentication And Authorization

Problem:
- Meeting, worker, feedback, calendar, delete, retrain, and A/B endpoints are callable if the FastAPI service is reachable.
- Frontend sign-in does not protect backend routes.

Evidence:
- `src/meeting_agent/api/main.py`
- `src/meeting_agent/api/calendar_router.py`

Fix:
- Add a backend auth dependency that validates a signed session/JWT/service token.
- Derive `user_id` from the verified token, not from request body or query params.
- Add ownership checks before reading, deleting, editing, syncing, or exporting resources.
- Restrict admin endpoints to admin users or a service role.

Acceptance criteria:
- Unauthenticated requests to protected endpoints return 401.
- Authenticated users cannot read/delete/sync meetings they do not own.
- Admin endpoints reject non-admin users.
- Tests cover positive and negative auth paths.

### P0-2 Google Calendar Token Flow Trusts Request-Supplied User IDs

Problem:
- `/auth/google/token-direct` accepts arbitrary `user_id`.
- `/meetings/{meeting_id}/calendar-sync` trusts `user_id` from query params.

Evidence:
- `src/meeting_agent/api/calendar_router.py`
- `web/app/api/calendar-sync/route.ts`

Fix:
- Remove `user_id` from token-direct body and calendar-sync query usage.
- Store and load tokens by verified backend identity.
- Associate calendar sync with both meeting owner and authenticated user.

Acceptance criteria:
- A user cannot store or overwrite another user's token.
- Calendar sync rejects requests for meetings owned by another user.
- Token store receives only server-derived user IDs.

### P0-3 Token Store Uses Unsanitized User IDs As File Paths

Problem:
- Token file path is `data/tokens/<user_id>.enc`.
- Path separators or crafted IDs could escape the intended directory.

Evidence:
- `src/meeting_agent/integrations/token_store.py`

Fix:
- Use a stable hash such as SHA-256 of the canonical user ID for token filenames.
- Store original user ID inside encrypted token metadata if needed.
- Prefer moving tokens to DB or a secret manager in production.

Acceptance criteria:
- User IDs with path separators cannot affect filesystem paths.
- Unit tests cover path traversal attempts.

### P0-4 Personal And Sensitive Local Data Is Present

Problem:
- `data/workers.json` is tracked and contains personal email addresses.
- Startup seed workers also contain personal email addresses.
- Local cert/key and pgAdmin password files are tracked.

Evidence:
- `data/workers.json`
- `src/meeting_agent/api/main.py`
- `docker/nginx/certs/server.key`
- `docker/pgadmin/pgpass`

Fix:
- Replace personal addresses with `example.com` fixtures.
- Remove tracked generated/local credential files from git.
- Add a hygiene check to CI.

Acceptance criteria:
- No personal emails remain in seed fixtures.
- No private keys, generated certs, pgAdmin password files, `__pycache__`, `.pyc`, or `.DS_Store` are tracked.
- CI fails if such files are added again.

## P1 Issues

### P1-1 Worker Roster Is File-Backed Instead Of Database-Backed

Problem:
- Workers are stored in `data/workers.json`.
- API, assignment, frontend, and calendar sync depend on this shared state.
- It has no user/team ownership, no database constraints, and weak concurrency behavior.

Fix:
- Add a `workers` table.
- Suggested columns: `id`, `owner_user_id` or `team_id`, `name`, `email`, `role`, `aliases` JSONB, `skills` JSONB, `created_at`, `updated_at`.
- Migrate worker registry functions to repository functions.
- Seed only sanitized development fixtures.

Acceptance criteria:
- Worker CRUD reads/writes Postgres.
- Worker list is scoped to the authenticated user/team.
- Existing tests are updated to use DB-backed fixtures.

### P1-2 Meeting Ownership Is Missing

Problem:
- Meetings are globally addressable by ID.
- Feedback, deletion, export, participant resolution, and calendar sync are not owner-scoped.

Fix:
- Add `owner_user_id` or `team_id` to `meetings`.
- Add matching ownership to `workers`, `feedback_corrections`, token records, and `calendar_events`.
- Require ownership filters in repository methods.

Acceptance criteria:
- Repository methods accept verified owner context for user-facing reads/writes.
- Cross-user access tests fail before fix and pass after fix.

### P1-3 Calendar Sync Results Are Stored In JSON Files

Problem:
- Created event IDs are persisted to `data/transcripts/{meeting_id}_calendar.json`, not DB.
- There is no idempotency guard, audit trail, or queryable sync status.

Fix:
- Add a `calendar_events` table keyed by meeting/task/user/provider.
- Suggested columns: `id`, `meeting_id`, `task_id`, `user_id`, `provider`, `provider_event_id`, `html_link`, `status`, `last_error`, `created_at`, `updated_at`.
- Upsert by `(meeting_id, task_id, user_id, provider)` before creating duplicate events.

Acceptance criteria:
- Syncing the same task twice does not create duplicate calendar events.
- Event IDs and errors are visible through API/history.

### P1-4 Raw ASR And Transcript Artifacts Need A Deliberate Persistence Model

Current behavior:
- `run_pipeline()` stores `summary.transcript_turns`.
- `upsert_meeting_result()` persists that list into `meetings.transcript_turns` JSONB.
- `get_meeting()` does not return transcript turns.
- Raw WhisperX output, word-level alignment, raw LLM output, and preprocessing metadata are not deliberately stored.

Fix:
- Keep normalized transcript rows for application use.
- Keep raw artifacts for audit/debug/fine-tuning traceability.

Recommended schema:
- `transcript_turns`: `id`, `meeting_id`, `turn_id`, `speaker_id`, `speaker_name`, `worker_id`, `start_ms`, `end_ms`, `text`, `asr_confidence`, `created_at`.
- Optional `transcript_words`: `meeting_id`, `turn_id`, `word`, `start_ms`, `end_ms`, `confidence`, only if word-level review/search/alignment is needed.
- `meeting_artifacts`: `id`, `meeting_id`, `artifact_type`, `storage_uri` or JSONB payload, `checksum`, `metadata` JSONB, `created_at`.
- Artifact types: `uploaded_audio`, `clean_audio`, `asr_raw`, `diarization_raw`, `llm_summary_raw`, `llm_tasks_raw`, `pii_masked_transcript`.

Privacy requirements:
- Apply access controls to raw transcript and audio.
- Add retention policy for raw audio/transcripts.
- Store optional PII-masked transcript for lower-risk previews and analytics.

Acceptance criteria:
- Completed meetings have normalized transcript turns in DB.
- Raw ASR/LLM artifacts are recoverable for audit.
- API exposes transcript only to authorized owners.
- Fine-tuning export uses persisted full transcripts instead of fabricated text.

### P1-5 Prompt Injection And PII Guardrails Are Not Applied Before LLM Calls

Problem:
- `sanitize_input()` exists but raw transcript text is used in LLM prompts.

Fix:
- Sanitize each transcript turn before prompt construction.
- Block or quarantine meetings containing injection patterns.
- Keep raw transcript for authorized audit, but send safe text to prompts/logs.

Acceptance criteria:
- Tests prove malicious transcript text is blocked before `_call_llm`.
- PII masking behavior is explicit for logs/traces.

### P1-6 Upload Validation Happens Too Late

Problem:
- `/meetings` writes uploaded content before validating extension/size.

Fix:
- Validate filename extension before writing.
- Enforce maximum upload bytes while streaming.
- Return 413 for oversized files and 415/422 for unsupported formats.

Acceptance criteria:
- Oversized files do not fully write to disk.
- Unsupported extensions are rejected before Celery dispatch.

### P1-7 Job Metrics Are Double-Counted

Problem:
- `JOBS_TOTAL(completed)` and failure counters are incremented in both pipeline and Celery wrapper.

Fix:
- Make Celery/job wrapper own job counters.
- Pipeline stages should own stage metrics only.

Acceptance criteria:
- One completed job increments completed counter once.
- One failed job increments failed counter once.

## P1 MLOps Issues

### P1-8 Dataset Contracts Are Inconsistent

Problem:
- `train/dataset.py` expects raw rows with `transcript`, `meeting_date`, `participants`, `roster`, `action_items`.
- `data_pipeline/export_for_finetuning.py` exports `instruction`, `input`, `output`.
- `data_pipeline/collect_interactions.py` exports `instruction`, `input`, `output`, plus metadata.
- `train/evaluate.py` expects gold rows with `transcript_turns`, `roster`, `action_items`.

Fix:
- Define canonical schemas:
  - Raw meeting record.
  - SFT record.
  - RLHF preference record.
  - Eval gold record.
- Make `train/dataset.py` load both raw records and SFT records through explicit adapters.
- Document schema versions in each JSONL.

Acceptance criteria:
- Any file produced by `export_for_finetuning.py` or `collect_interactions.py --format sft` can be loaded by `train/dataset.py`.
- Dataset compatibility smoke test is in CI.

### P1-9 Feedback Retraining Uses Weak Fabricated Inputs

Problem:
- `train/retrain.py` builds `transcript` as `[Action item]: {original_description}`.
- This loses meeting context and teaches a different task than production extraction.
- False positives are skipped instead of becoming negative examples.

Fix:
- Export feedback examples by joining `feedback_corrections` to the original meeting transcript and corrected tasks.
- Use dismissed false positives as negative or preference examples.

Acceptance criteria:
- Retraining examples include full transcript text from the meeting.
- False positives are represented in either SFT empty-output records or RLHF rejected examples.

### P1-10 Retraining Validation Fails Open

Problem:
- Retrain validates only the first data file and continues when validation fails.

Fix:
- Validate every assembled data file.
- Fail retraining if validation fails.
- Validate schema, date format, duplicate rate, empty transcript rate, label shape, and train/eval leakage.

Acceptance criteria:
- Invalid training data aborts retraining before GPU work begins.
- Validation report is saved as an artifact.

### P1-11 Model Promotion Is Not Connected To Serving

Problem:
- MLflow stage transition does not update Ollama model tags or serving config.
- `OLLAMA_LLM_MODEL` remains unchanged unless manually edited.

Fix:
- Define promotion output:
  - generated Ollama model name/tag
  - Modelfile or deployment metadata
  - immutable artifact path/checksum
  - serving config update mechanism
- Require manual approval or explicit deploy command before production routing changes.

Acceptance criteria:
- A promoted model can be referenced by a concrete Ollama tag.
- Serving config change is auditable and reversible.

### P1-12 Evaluation Overrides Are Unreliable

Problem:
- `train/evaluate.py` mutates `os.environ["OLLAMA_LLM_MODEL"]`, but settings may already be instantiated.
- Prompt monkey-patching happens after importing `extract_action_items`, while orchestrator imports prompt constants at module load.

Fix:
- Pass model and prompt mode explicitly into extraction/evaluation functions.
- Avoid monkey-patching module constants.

Acceptance criteria:
- Tests prove zero-shot/few-shot/finetuned modes use different prompts/models.

### P1-13 Drift Logging Uses Nonexistent Fields

Problem:
- Drift logging reads `token_count` and `hallucination_flag` from task dicts, but `ExtractedTask` does not define them.

Fix:
- Compute drift features from `RunMetrics`, guardrail counters, resolved task counts, and actual LLM token totals.

Acceptance criteria:
- Drift records contain nonzero token counts when LLM calls occur.
- Hallucination-related drift fields match guardrail output.

### P1-14 A/B Routing Needs Explicit Enablement And Guardrails

Problem:
- If `.ab_test_state.json` says active, model routing overrides production inference.

Fix:
- Add explicit `AB_TEST_ENABLED=true`.
- Add minimum sample size, rollback, ownership, and admin authorization.
- Record assignment decisions in meeting metadata.

Acceptance criteria:
- A/B routing is off unless explicitly enabled.
- Each meeting records model variant and experiment ID.

## P2 Issues

### P2-1 CI Coverage Is Incomplete

Current gaps:
- No frontend lint/build in CI.
- No dataset export/load smoke test.
- No Alembic migration smoke test against Postgres.
- No hygiene check for generated files/secrets.
- Docker CI builds root `Dockerfile`, but not necessarily API, worker, and web images in the main CI path.

Fix:
- Add CI jobs:
  - `ruff check src/ tests/ train/ data_pipeline/`
  - backend tests
  - `web/npm ci`, `npm run lint`, `npm run build`
  - Alembic upgrade smoke against Postgres
  - dataset schema compatibility smoke
  - generated-file/secret hygiene check
  - Docker build for API, worker, web

Acceptance criteria:
- CI catches current ruff failures and future frontend build breaks.
- CI catches schema mismatch between export and train loader.

### P2-2 Current Ruff Check Fails

Command:
- `PYTHONPATH=src ruff check src/ tests/ train/ data_pipeline/`

Current result:
- 7 lint errors in MLOps/data scripts:
  - `data_pipeline/collect_interactions.py`
  - `data_pipeline/synthetic.py`
  - `data_pipeline/tts_audio.py`
  - `data_pipeline/tts_macos.py`
  - `train/evaluate.py`

Acceptance criteria:
- Ruff passes locally and in CI.

### P2-3 Repository Hygiene Is Inconsistent

Problem:
- `.gitignore` ignores data and caches, but some generated/local files are already tracked.

Fix:
- Remove tracked generated files and local secrets from git.
- Keep sanitized example fixtures separately.

Acceptance criteria:
- `git ls-files` shows no `__pycache__`, `.pyc`, `.DS_Store`, local cert private keys, pgAdmin password files, or runtime data.

### P2-4 Timestamps Use Deprecated `datetime.utcnow()`

Problem:
- Python 3.13 warns that `datetime.utcnow()` is deprecated.

Fix:
- Use timezone-aware `datetime.now(datetime.UTC)` or `datetime.now(timezone.utc)`.

Acceptance criteria:
- Test suite runs without UTC deprecation warnings.

## P3 Improvements

- Add architecture documentation for auth, persistence, MLOps data contracts, and model promotion.
- Add runbooks for retraining, rollback, drift alerts, and A/B experiments.
- Add sample `.env.example` values that are safe and complete.
- Add local developer commands for API, worker, web, tests, and lint in one place.

## Proposed Database Migration Plan

Migration A: ownership foundation
- Add `users` table if local user records are needed, or store external user subject directly.
- Add `owner_user_id` to `meetings`.
- Backfill existing rows with a development owner.

Migration B: worker roster
- Add `workers` table.
- Optional: add `worker_aliases` and `worker_skills`, or store aliases/skills as JSONB.
- Migrate `data/workers.json` to sanitized DB seed or one-time import script.

Migration C: transcript normalization and artifacts
- Add `transcript_turns`.
- Add optional `transcript_words`.
- Add `meeting_artifacts`.
- Backfill from `meetings.transcript_turns`.

Migration D: calendar event persistence
- Add `calendar_events`.
- Add unique constraint on `(meeting_id, task_id, user_id, provider)`.

Migration E: ownership expansion
- Add owner/team fields to feedback and tokens/calendar-related tables if needed.
- Add indexes for owner-scoped listing.

## Proposed MLOps Data Contract

Raw meeting record:
```json
{
  "schema_version": "meeting_raw_v1",
  "meeting_id": "uuid",
  "meeting_date": "YYYY-MM-DD",
  "participants": ["Alice Chen", "Bob Kim"],
  "roster": {"workers": []},
  "transcript_turns": [
    {
      "turn_id": "t1",
      "speaker_id": "SPEAKER_00",
      "speaker_name": "Alice Chen",
      "start_ms": 0,
      "end_ms": 1000,
      "text": "Please send the report.",
      "asr_confidence": 0.93
    }
  ],
  "action_items": []
}
```

SFT record:
```json
{
  "schema_version": "sft_v1",
  "instruction": "system prompt",
  "input": "user prompt or transcript text",
  "output": "[{\"description\":\"Send report\",...}]",
  "source_meeting_id": "uuid",
  "model_version": "qwen2.5:3b"
}
```

RLHF record:
```json
{
  "schema_version": "rlhf_v1",
  "prompt": "transcript or full prompt",
  "chosen": "[...]",
  "rejected": "[...]",
  "source_meeting_id": "uuid",
  "feedback_type": "correction|false_positive"
}
```

Eval gold record:
```json
{
  "schema_version": "eval_gold_v1",
  "meeting_id": "eval_001",
  "meeting_date": "YYYY-MM-DD",
  "roster": {"workers": []},
  "transcript_turns": [],
  "action_items": []
}
```

## Implementation Checklist

Phase 1: Safety and ownership
- Add auth dependency. Not started.
- Add owner fields and ownership checks. Not started.
- Fix Google token flow. Not started.
- Sanitize token filenames. Done in first implementation slice.
- Remove personal seed data. Partially done for API seed workers; tracked `data/workers.json` still needs cleanup/removal.

Phase 2: Persistence
- Move workers to DB.
- Add calendar events table.
- Add transcript/artifact tables.
- Backfill from existing JSONB transcript data.

Phase 3: Pipeline correctness
- Apply prompt sanitization. Done for transcript text sent to orchestrator prompts.
- Validate uploads before writing. Done for extension, streaming size limit, and `ffprobe` audio content validation in the API endpoint and ingest layer.
- Fix job metric double-counting. Done by moving job status counting out of `run_pipeline()`.
- Fix timezone-aware datetime warnings. Done for app-side timestamp paths covered by tests.
- Add frontend job resume. Done: active meeting id is stored in browser storage, restored on page load, and History links can reopen processing/review.

Phase 4: MLOps repair
- Define canonical schemas.
- Update exporters/loaders/evaluation to use adapters.
- Fix retraining validation and feedback export.
- Fix drift logging.
- Add explicit A/B enablement.

Phase 5: CI and hygiene
- Fix ruff failures. Done; full ruff passes locally.
- Add web lint/build.
- Add migration and dataset smoke tests.
- Add generated-file/secret hygiene job.
- Remove tracked generated/local files.

## Verification So Far

- `PYTHONPATH=src pytest tests/ -q` passed: 122 tests.
- `PYTHONPATH=src ruff check src/ tests/ train/ data_pipeline/` passed.
- Python 3.13 `datetime.utcnow()` warnings were removed from the app-side tested code paths.
- Remaining warnings are from FAISS/SWIG import internals during one orchestrator sanitization test.
- `python3 train/finetune.py --help` works in the local shell.
