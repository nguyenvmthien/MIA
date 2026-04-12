## Plan: Meeting Agent MVP for Task Delivery

Build an asynchronous meeting-processing pipeline that converts audio to diarized transcript with WhisperX, then uses local GGUF LLM inference (Qwen 3.5B Q4) to produce structured summaries and worker-assigned tasks. Prioritize correctness of task extraction, deterministic output schemas, and measurable quality gates before optimization.

**Steps**
1. Confirm scope and success metrics: lock operating mode as batch-first (upload audio -> output artifacts), supported audio formats, target language(s), and acceptance thresholds (WER, diarization error, task precision/recall, latency). This step defines all downstream test gates.
2. Phase 1 - Data contracts and baseline architecture (*blocks all later implementation*): define canonical schemas for `TranscriptTurn`, `MeetingSummary`, `ExtractedTask`, `WorkerRoster`, and `RunMetrics`; define C4 artifacts to produce (System Context, Container, Component for processing service, Dynamic for batch flow, Deployment).
3. Phase 1 - Environment and model readiness (*parallel with step 2*): pin runtime (Python 3.10/3.11), validate WhisperX execution path, validate Qwen GGUF runtime via llama.cpp/ollama, define model/version registry naming and artifact storage paths.
4. Phase 2 - Pipeline skeleton (*depends on 2 and 3*): implement ingestion -> preprocessing -> WhisperX STT+diarization -> segmentation -> LLM extraction -> post-processing -> persistence as independently testable stages with structured logging and stage-level timings.
5. Phase 2 - Assignment logic (*parallel with step 4 once schema exists*): implement worker resolution strategy (exact name, alias match, role/skill hint fallback, unresolved queue), plus confidence scoring and explicit `unassigned` handling.
6. Phase 3 - Prompting and extraction reliability (*depends on 4 and 5*): build prompt templates with strict JSON output constraints, include meeting metadata and worker roster grounding, add guardrails for missing due dates/owners/ambiguous statements.
7. Phase 3 - Evaluation harness (*parallel with step 6*): create a labeled evaluation set from real/synthetic meetings and automated scorers for task precision/recall/F1, schema validity rate, hallucination rate, and summary quality rubric.
8. Phase 4 - Observability and operations (*depends on 4*): emit metrics per stage (duration, error rate, token count, extraction count, confidence distribution), set alert thresholds, and create minimal dashboards for throughput/latency/quality drift.
9. Phase 4 - Performance and cost optimization (*depends on 7 and 8*): optimize chunking, batching, cache reusable context (roster embeddings/speaker profiles), profile GPU/CPU memory, and tune for target latency per meeting hour.
10. Phase 5 - Release readiness (*depends on all prior steps*): package with Docker, add CI checks (lint, unit, integration, eval smoke), publish runbook and failure playbooks, and execute UAT with business users.

**Implementation/Test Plan Table**
| Phase | Goal | Key Deliverables | Dependencies | Verification Gate (must pass) |
|---|---|---|---|---|
| 0. Scope Lock | Remove ambiguity | Final KPI targets, language/speaker assumptions, input/output contract approved | None | Stakeholder sign-off on KPI table and schemas |
| 1. Contracts + Runtime | Stable foundation | Versioned schemas, model/runtime pinned, C4 baseline diagrams | 0 | Schema validation tests pass at 100% on fixtures; model smoke tests pass |
| 2. E2E Skeleton | Working pipeline | Batch processing from audio to JSON outputs | 1 | 5-sample integration run succeeds with 0 schema failures |
| 3. Task Assignment Quality | Correct owner mapping | Alias/role mapping, unresolved-task queue, confidence model | 2 | Assignment precision >= 0.85 on labeled set |
| 4. Extraction Reliability | Robust structured output | Prompt templates, guardrails, ambiguity handling | 2,3 | Task recall >= 0.90, hallucination <= 0.05 |
| 5. Observability + Ops | Operable service | Metrics, dashboards, alerts, error taxonomy | 2 | P95 stage timings visible; alert simulation succeeds |
| 6. Optimization | Meet latency/cost targets | Chunk/batch tuning, cache strategy, model config tuning | 4,5 | End-to-end P95 latency target met for 1-hour meeting |
| 7. Release + UAT | Production readiness | CI/CD, container image, runbook, UAT results | 1-6 | UAT pass and rollback drill completed |

**Testing Matrix (Post-Implementation)**
| Test Type | Scope | Dataset/Method | Pass Criteria | Frequency |
|---|---|---|---|---|
| Unit | Parsers, schema validators, assignment resolver, prompt response parser | Synthetic fixtures and edge-case transcripts | >= 90% critical-path coverage; 0 critical failures | Every PR |
| Integration | Stage chaining (ingest -> STT -> diarization -> LLM -> persistence) | 5-10 representative meetings | 100% valid JSON outputs; no stage crash | Every PR |
| E2E Functional | Full batch run with worker delivery output | Real meeting recordings + roster | Task precision >= 0.85, recall >= 0.90 | Nightly |
| Quality Evaluation | Summary and task quality | Labeled gold set + rubric review | Hallucination <= 5%; summary rubric >= 4/5 avg | Nightly/Release |
| Load/Stress | Concurrent meeting processing | Synthetic concurrent jobs | No OOM; error rate < 1%; bounded queue growth | Weekly |
| Latency Profiling | Stage and total timing | Timed benchmark corpus | Meet defined P95 latency target | Weekly/Release |
| Resilience | Failure injection (bad audio, missing roster, model timeout) | Chaos/error scenarios | Graceful degradation and retry behavior verified | Weekly |
| Security/Compliance | Data handling and access controls | Checklist + static scan + manual review | No sensitive leak in logs; retention policy enforced | Release |

**Relevant files**
- `/Users/thiennguyen/Library/CloudStorage/GoogleDrive-nguyenvmthien@gmail.com/My Drive/A+SCHOOL-HK11/applied-llm/MEETING-AGENT/doc.md` - Source project constraints (LLMOps, monitoring, governance, report requirements).
- `/Users/thiennguyen/Library/CloudStorage/GoogleDrive-nguyenvmthien@gmail.com/My Drive/A+SCHOOL-HK11/applied-llm/MEETING-AGENT/require.md` - Core requirement themes (modeling, deployment, monitoring, compliance, automation).
- `/Users/thiennguyen/Library/CloudStorage/GoogleDrive-nguyenvmthien@gmail.com/My Drive/A+SCHOOL-HK11/applied-llm/MEETING-AGENT/c4model.md` - C4 modeling guidance to structure architecture artifacts.

**Verification**
1. Run schema conformance tests on sample outputs from each stage and fail on any missing/extra required fields.
2. Run benchmark suite on labeled meetings and compute precision/recall/F1 for extracted tasks plus unresolved-task rate.
3. Validate diarization quality against annotated speaker turns and track diarization error as a release gate.
4. Execute latency benchmark for 1-hour audio across target hardware and validate P95 objective.
5. Validate observability by triggering synthetic failures and ensuring alerts fire with actionable context.
6. Execute UAT with business reviewers and confirm delivery format is directly usable by assigned workers.

**Decisions**
- Included scope: batch meeting processing, structured summary, task extraction, worker assignment, observability, and test gates.
- Excluded from MVP: live streaming transcription, multilingual optimization beyond primary language, and model fine-tuning pipeline.
- Assumptions: worker roster is available; initial deployment is internal and asynchronous; Qwen GGUF local inference is acceptable for privacy/cost.

**Further Considerations**
1. Assignment strategy: Option A strict name/alias mapping (fastest), Option B hybrid rule + embedding similarity (better recall), Option C human review queue first (highest trust).
2. Runtime choice: Option A `llama-cpp-python` direct integration (more control), Option B `ollama` service wrapper (faster setup).
3. QA target setting: Option A aggressive thresholds for launch, Option B staged thresholds (soft launch then tighten after feedback).
