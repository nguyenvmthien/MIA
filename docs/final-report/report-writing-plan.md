# Final Report Writing Plan

Purpose: define what must be written in each report section before rewriting the final report.  
Basis: `debai.md` and the current Meeting AI Agent implementation.

## Audit Notes Before Writing

- Treat `docs/project-status.md`, source code, tests, and measured evaluation results as the main sources of truth.
- Do not rely on checklist status alone when making claims in the final report. Some roadmap items may be marked complete for planning convenience but still need evidence before being written as completed work.
- Current defensible claim:
  - The system implements an end-to-end meeting processing pipeline.
  - The system has a GPU-ready fine-tuning and retraining workflow.
  - The current published evaluation numbers are baseline results for Qwen2.5-3B before fine-tuning.
  - Public-domain deployment was attempted but is not completed; local Docker demo is the reliable deployment mode.
- Avoid claiming:
  - A production fine-tuned model has been successfully deployed, unless a concrete artifact, run ID, and evaluation comparison are available.
  - Full GDPR/CCPA compliance.
  - Enterprise-scale cloud production readiness.
  - Complete real-world validation on large real meeting datasets.

## Required Evidence To Use In The Report

- Baseline evaluation:
  - Gold set: `data/eval/gold_synthetic_205.jsonl`.
  - Sample size: 100.
  - Model: `qwen2.5:3b`.
  - Precision: `0.8604`.
  - Recall: `0.6665`.
  - F1: `0.6886`.
  - Assignee accuracy: `0.5232`.
  - Hallucination rate: `0.0`.
  - Schema failure rate: `0.0`.
- Current runtime stack:
  - FastAPI, Next.js, Celery, Redis, PostgreSQL, Ollama, Prometheus, Grafana, Docker Compose.
- Current LLMOps status:
  - Feedback export, dataset validation, evaluation scripts, retrain trigger, MLflow/promotion support are implemented.
  - GPU fine-tuning is prepared but should be described as a controlled extension path unless verified training artifacts are available.
- Current security status:
  - User-scoped access exists for meetings/workers/feedback/calendar paths when backend auth is enabled.
  - PII masking is regex-based and applied mainly before prompt construction/logging.
- Current deployment status:
  - Local Docker deployment is working.
  - Public domain through Cloudflare Tunnel is not finalized and should be discussed as a deployment challenge or future work, not as completed production deployment.

## Required Terminology Definitions

- Correction data:
  - Vietnamese wording: dữ liệu hiệu chỉnh của người dùng.
  - Meaning: records created when a user reviews extracted action items and corrects the model output.
  - Examples:
    - Correcting a wrong task description.
    - Correcting an assignee.
    - Correcting a due date.
    - Marking an extracted task as a false positive.
    - Adding or identifying a missing task.
  - In this project, corrections are stored in PostgreSQL and can be exported as JSONL for evaluation or future fine-tuning.
- Reference labels:
  - Vietnamese wording: đáp án tham chiếu or kết quả kỳ vọng.
  - Avoid using the phrase "nhãn chuẩn" unless the dataset was manually verified or curated as a true gold-standard dataset.
  - For `gold_synthetic_205.jsonl`, describe it as a synthetic evaluation set with expected action items/reference outputs.
  - If human verification is not available, state that it is a benchmark reference set, not a fully human-annotated gold standard.
- Synthetic data:
  - Vietnamese wording: dữ liệu tổng hợp.
  - Meaning: meeting transcripts and expected action items generated programmatically or by an LLM for controlled training/evaluation.
  - Limitation: useful for repeatable benchmarking, but not a substitute for real meeting data.
- Gold set:
  - If used, define it as the evaluation set against which predictions are compared.
  - Clarify whether the "gold" answers are synthetic references or human-annotated labels.
  - In this report, prefer "tập đánh giá tham chiếu" for synthetic benchmark data.
- Dataset/artifact names:
  - Every file name mentioned in the report must be explained the first time it appears.
  - Explain source, schema, role, and limitation before using the file as evidence.

## Reader-First Explanation Rules

- Before using any metric, explain:
  - What the metric measures.
  - Why the metric matters for this project.
  - How the metric is computed in this implementation.
  - What data was used to compute it.
  - What limitations affect its interpretation.
- Before reporting precision, recall, or F1, explain the matching procedure:
  - The model predicts a list of action items from a transcript.
  - Each predicted task is compared with a reference task from the evaluation set.
  - Matching is performed primarily on task description similarity.
  - The implementation uses BM25 first; if BM25 does not match, it falls back to Jaccard token overlap.
  - A reference task can be matched only once.
  - A matched prediction is counted as a true positive.
  - A prediction that does not match any reference task is counted as a false positive.
  - A reference task that is not matched by any prediction is counted as a false negative.
  - Assignee accuracy is computed separately after a description-level match.
- Before mentioning "ground truth", be careful:
  - Prefer "reference output" or "expected output" for synthetic data.
  - Use "ground truth" only if explaining that it means the reference answer used by the benchmark, not necessarily a human-verified truth.
- Before drawing conclusions from synthetic evaluation:
  - State that synthetic benchmarks are controlled and repeatable.
  - State that they do not fully represent real-world meeting noise, accents, ambiguity, or organizational context.
- Every technical section should answer:
  - What problem does this component solve?
  - What input does it receive?
  - What output does it produce?
  - Where is it located in the system pipeline?
  - How is success or failure measured?
  - What are its limitations?
- Avoid unexplained abbreviations:
  - Define ASR, STT, RAG, PII, LLMOps, MLOps, WER, DER before use.
  - Use Vietnamese explanations first, then keep English abbreviations in parentheses.
- Avoid naked file names or command names:
  - Do not write only "`gold_synthetic_205.jsonl` was used".
  - Write what the file contains, why it exists, how it is used, and what its limitations are.
- Avoid result-only paragraphs:
  - Do not present numbers without method.
  - Every result table must be preceded by evaluation setup and followed by interpretation.

## Required Model And Component Explanations

Every AI/ML model or core technical component must be introduced before it is used in the system discussion.

- For each model/component, explain:
  - What problem it solves.
  - What role it has in the Meeting AI Agent pipeline.
  - What input it receives.
  - What output it produces.
  - The main architectural or algorithmic idea at a level appropriate for a senior technical reader.
  - Why it was selected for this project.
  - What alternatives exist.
  - What its limitations are.

- WhisperX:
  - Explain that WhisperX is used for automatic speech recognition and word-level alignment.
  - Input: meeting audio after preprocessing.
  - Output: transcript segments/turn text with timing information.
  - Explain that it builds on Whisper-style encoder-decoder speech recognition and adds alignment/diarization integration for more precise timestamps.
  - Explain why timestamp accuracy matters for traceability and speaker turns.
  - Mention limitation: quality depends on audio quality, language, accent, noise, and compute resources.

- Pyannote or diarization component:
  - Explain speaker diarization as "who spoke when".
  - Input: audio or speech segments.
  - Output: speaker labels such as `SPEAKER_00`, `SPEAKER_01` with time ranges.
  - Explain that diarization is different from speech recognition: ASR transcribes words, diarization separates speakers.
  - Mention limitation: overlapping speech, similar voices, and noisy audio can reduce accuracy.

- Qwen2.5-3B via Ollama:
  - Explain that it is the local instruction-following LLM used for summarization and action item extraction.
  - Input: prompt containing meeting date, participants, transcript chunk, and extraction instructions.
  - Output: summary text or structured JSON action items.
  - Explain at a high level that it is a transformer-based autoregressive language model.
  - Explain why a 3B local model was selected: privacy, cost control, Docker/local deployment feasibility.
  - Mention limitation: slower on CPU, lower reasoning capacity than larger cloud models, possible hallucination.

- Embedding/FAISS retrieval:
  - Explain embeddings as vector representations of text.
  - Explain FAISS as an approximate nearest-neighbor index used to retrieve relevant context.
  - Input: transcript text or speaker context.
  - Output: relevant context snippets for prompt enrichment.
  - Mention limitation: retrieval quality depends on embedding quality and indexed content.

- Redis cache:
  - Explain that Redis is not an AI model but supports inference optimization.
  - Input: prompt/model cache key.
  - Output: cached LLM response when available.
  - Explain why caching reduces repeated LLM calls and latency.

- Guardrail module:
  - Explain that guardrails are validation and safety checks around model input/output.
  - Input: transcript text or raw model output.
  - Output: sanitized prompt text, validated tasks, or rejected/flagged output.
  - Include schema validation, jailbreak filtering, PII masking, due-date sanity, and hallucination checks.

## Front Matter

- Title page:
  - Project title: Meeting AI Agent.
  - Course name: Ứng dụng xử lý ngôn ngữ tự nhiên trong doanh nghiệp.
  - Instructors: PhD. Nguyễn Hồng Bữu Long and PhD. Lương An Vinh.
  - Student: Nguyễn Văn Minh Thiện.
  - Student ID: 22127398.
  - This is an individual project; do not include team roles or member contribution tables.
  - Submission date or semester.
- Table of contents.
- List of figures.
- List of tables.
- Optional list of abbreviations:
  - LLM, LLMOps, ASR, STT, RAG, MLOps, CI/CD, PII, WER, DER.

## Abstract

- State the problem: meeting audio contains important decisions and action items that are difficult to track manually.
- State the objective: build an AI system that converts meeting audio into summaries and structured action items.
- Summarize the methodology:
  - Speech-to-text and diarization.
  - LLM-based summary and action item extraction.
  - Worker assignment.
  - Guardrails.
  - Feedback loop.
  - Monitoring and evaluation.
- Summarize the implementation:
  - FastAPI backend, Next.js frontend, Celery workers, PostgreSQL, Redis, Ollama, Docker.
- Summarize the main results:
  - End-to-end pipeline.
  - Web-based review workflow.
  - Calendar sync.
  - Evaluation and monitoring support.
  - Baseline quantitative metrics for Qwen2.5-3B.
- Keep this section concise, around 200-300 words.

## Chapter 1: Introduction

- Present the real-world problem:
  - Meetings generate many tasks and decisions.
  - Manual note-taking is error-prone and time-consuming.
  - Assignees, deadlines, and follow-up actions can be missed.
- Explain the motivation:
  - NLP and LLMs can transform unstructured meeting audio into structured operational data.
  - The project aligns with LLMOps because it includes data, model, deployment, monitoring, and feedback workflows.
- Define the project objectives:
  - Upload meeting audio.
  - Generate diarized transcript.
  - Generate meeting summary.
  - Extract action items.
  - Resolve assignees using a worker roster.
  - Persist results to a database.
  - Support feedback correction and Google Calendar synchronization.
- Define project scope:
  - Local-first, open-source model stack.
  - Dockerized deployment.
  - Web UI and REST API.
  - LLMOps-oriented evaluation and monitoring.
- Briefly introduce the LLMOps principles applied:
  - Data management.
  - Model selection.
  - Prompt engineering.
  - Inference optimization.
  - Deployment.
  - Monitoring.
  - Feedback loop.
  - Continuous improvement.

## Chapter 2: Literature Review

- Review meeting intelligence systems:
  - Automatic speech recognition.
  - Speaker diarization.
  - Meeting summarization.
  - Action item extraction.
- Review LLM-based information extraction:
  - Instruction-following models.
  - Structured JSON output.
  - Few-shot prompting.
- Review LLMOps:
  - Need for systematic data management, evaluation, deployment, monitoring, and retraining.
  - Difference between a simple LLM demo and an operational LLM system.
- Review related technologies:
  - Whisper or WhisperX for speech-to-text.
  - Pyannote for speaker diarization.
  - Qwen or comparable open-source LLMs.
  - LoRA, QLoRA, and PEFT for efficient fine-tuning.
  - RAG and FAISS for contextual retrieval.
  - Redis caching.
  - Prometheus, Grafana, and LangSmith for observability.
- Identify the gap addressed by the project:
  - Most prototypes focus on prompt-response behavior.
  - This project emphasizes a full LLMOps pipeline around an NLP application.

## Chapter 3: Methodology

- Define the task:
  - Input: meeting audio.
  - Intermediate representation: diarized transcript turns.
  - Output: summary and structured action items.
- Explain data methodology:
  - Real or synthetic meeting data.
  - Transcript schema.
  - Feedback corrections.
  - Dataset validation and compatibility checks.
  - Training/evaluation splits if available.
- Explain NLP pipeline:
  - Ingestion.
  - Audio preprocessing.
  - Speech-to-text.
  - Speaker diarization.
  - Transcript normalization.
  - Prompt construction.
  - LLM extraction.
  - Output validation.
  - Assignment resolution.
- Explain model selection:
  - WhisperX for ASR and word-level timestamps.
  - Pyannote for diarization.
  - Qwen2.5-3B through Ollama for local LLM inference.
  - Embedding model for retrieval if used.
  - Reason for choosing local open-source models.
- Explain fine-tuning and retraining strategy:
  - Synthetic data generation.
  - Feedback corrections.
  - QLoRA/PEFT pipeline.
  - MLflow tracking.
  - Evaluation gate before promotion.
  - State clearly that fine-tuning is part of the prepared lifecycle and requires GPU/manual execution unless verified run artifacts are available.
- Explain prompt engineering:
  - Prompt templates.
  - Few-shot examples.
  - Schema-oriented JSON output.
  - Chunking for long transcripts.
- Explain guardrails:
  - JSON schema validation.
  - Jailbreak and prompt injection filtering.
  - Regex-based PII masking.
  - Hallucination checks.
  - Due date sanity checks.
- Explain LLMOps workflow:
  - Data collection.
  - Evaluation.
  - Training or retraining.
  - Deployment.
  - Monitoring.
  - Feedback loop.
- Define evaluation methodology:
  - Precision, recall, F1.
  - Schema validity.
  - Hallucination rate.
  - Due date accuracy.
  - Assignee accuracy.
  - Latency.
  - Token usage.
  - Correction rate.

## Chapter 4: Implementation

- Present the system architecture:
  - Next.js frontend.
  - FastAPI backend.
  - Celery workers.
  - Redis broker/cache.
  - PostgreSQL database.
  - Ollama model runtime.
  - Prometheus and Grafana monitoring.
  - Docker Compose deployment.
- Include a workflow diagram:
  - Audio upload.
  - Job queue.
  - Worker processing.
  - STT and diarization.
  - LLM extraction.
  - Database persistence.
  - UI review.
  - Feedback and calendar sync.
- Describe backend implementation:
  - Meeting upload endpoint.
  - Polling endpoint.
  - Worker and participant management.
  - Feedback API.
  - Calendar sync API.
  - Authentication and user scoping.
- Describe frontend implementation:
  - Upload page.
  - Processing state.
  - Task review.
  - Assignee editing.
  - Meeting history.
  - Google login and calendar synchronization.
- Describe database design:
  - Meetings.
  - Tasks.
  - Workers.
  - Transcript turns.
  - Feedback corrections.
  - Calendar events.
- Describe asynchronous processing:
  - Celery queue.
  - Redis broker and backend.
  - Job statuses: pending, processing, completed, failed.
- Describe MLOps implementation:
  - Dataset generation.
  - Dataset validation.
  - Evaluation scripts.
  - Retraining pipeline.
  - Model promotion helper.
- Describe monitoring implementation:
  - Prometheus metrics.
  - Grafana dashboard.
  - Business metrics.
  - Anomaly detection.
- Describe optimization techniques:
  - Transcript chunking.
  - Redis prompt cache.
  - FAISS speaker context.
  - Local Ollama inference.
  - Containerized services.
- Describe security and compliance implementation:
  - User-scoped data access.
  - Token encryption.
  - Regex-based PII masking.
  - Prompt injection filtering.
  - Guardrails for LLM output.
- Include an "Implemented vs Prepared vs Future Work" table:
  - Implemented: upload pipeline, STT/diarization path, LLM extraction, feedback, calendar sync, monitoring, evaluation scripts, Docker Compose.
  - Prepared: GPU fine-tuning, MLflow tracking, model promotion, A/B runtime routing, public-domain deployment path.
  - Future work: larger real dataset, production cloud deployment, stronger PII/DLP, autoscaling, additional integrations.
- Include a requirement-to-implementation mapping table:
  - Model selection and fine-tuning.
  - Data management and preprocessing.
  - Deployment and inference optimization.
  - Monitoring and observability.
  - Prompt engineering and guardrails.
  - Scalability and cost optimization.
  - Ethics and compliance.
  - Continuous improvement and automation.

## Chapter 5: Evaluation

- Define evaluation setup:
  - Dataset used.
  - Number and type of samples.
  - Baseline model.
  - Candidate model if applicable.
- Present functional evaluation:
  - Audio upload.
  - Transcript generation.
  - Summary generation.
  - Action item extraction.
  - Feedback correction.
  - Calendar synchronization.
  - Concurrent multi-user upload test.
- Present model evaluation:
  - Precision.
  - Recall.
  - F1.
  - Schema validity.
  - Hallucination rate.
  - Due date match.
  - Assignee resolution accuracy.
- Present system evaluation:
  - End-to-end latency.
  - Stage-level latency.
  - Queue behavior.
  - Docker deployment behavior.
  - Resource constraints.
- Present monitoring observations:
  - Prometheus metrics.
  - Grafana dashboards.
  - Correction rate.
  - False positive rate.
  - Training-ready samples.
  - Anomaly alerts.
- Include comparisons where available:
  - Baseline vs candidate model.
  - Zero-shot vs few-shot vs fine-tuned mode.
  - Different prompt or model configurations.
  - If candidate/fine-tuned results are not available, explicitly mark baseline as the main evaluated model and discuss fine-tuning as future improvement.
- Discuss the meaning of results:
  - What works well.
  - What remains weak.
  - Likely technical causes.
  - Explain that high precision and zero schema failure indicate reliable structured output, while recall and assignee accuracy remain improvement targets.

## Chapter 6: Challenges & Limitations

- Technical challenges:
  - Speech recognition quality.
  - Speaker diarization errors.
  - Long transcript chunking.
  - Local LLM latency.
  - JSON reliability.
  - Assignee resolution.
  - Google OAuth and Calendar integration.
  - Docker networking and public-domain demo setup.
- Data limitations:
  - Limited real meeting data.
  - Synthetic data may not fully represent real meetings.
  - Feedback sample size may still be small.
- Model limitations:
  - Small local LLM has limited reasoning capacity.
  - Hallucination can still occur.
  - Due date inference is uncertain.
  - Multilingual robustness requires more validation.
- System limitations:
  - Not yet deployed as a fully managed public cloud service.
  - Public domain/Cloudflare Tunnel setup is not finalized.
  - Throughput depends on local hardware.
  - Scaling requires additional infrastructure.
- Security and compliance limitations:
  - PII masking is regex-based, not full DLP.
  - Stored artifacts may need stronger redaction policy.
  - Real meeting usage requires consent and retention policies.

## Chapter 7: Future Work

- Improve dataset quality:
  - Collect more real meetings with permission.
  - Expand English and Vietnamese coverage.
  - Improve annotation quality.
- Improve model quality:
  - Tune extraction prompts.
  - Train or deploy a stronger fine-tuned model.
  - Improve recall and assignee accuracy.
- Improve speech processing:
  - Better diarization.
  - Better multilingual speech recognition.
  - Better speaker-to-worker resolution.
- Improve security and compliance:
  - NER-based PII detection.
  - Full artifact redaction.
  - Audit logs.
  - Stronger retention policy.
- Improve production readiness:
  - Cloud deployment.
  - HTTPS/domain.
  - Rate limiting.
  - Autoscaling.
  - Better multi-tenant ownership.
- Add more integrations:
  - Slack.
  - Jira.
  - Notion.
  - Trello or Asana.
  - Outlook Calendar.
- Improve evaluation:
  - Larger gold datasets.
  - Human evaluation.
  - A/B testing with real traffic.
  - Longitudinal monitoring.

## Chapter 8: Conclusion

- Summarize the system:
  - Meeting audio is transformed into transcript, summary, and action items.
  - Results are reviewable through a web interface.
  - Tasks can be corrected and synchronized to calendar events.
- Summarize LLMOps coverage:
  - Data management.
  - Model selection.
  - Prompt engineering.
  - Deployment.
  - Monitoring.
  - Evaluation.
  - Feedback loop.
  - Automation.
  - Guardrails.
- Summarize achieved outcomes:
  - End-to-end working pipeline.
  - Dockerized architecture.
  - Web application.
  - Async processing.
  - Monitoring and evaluation support.
- State the impact:
  - Reduces manual meeting follow-up effort.
  - Converts unstructured meeting audio into operational tasks.
  - Provides a foundation for enterprise workflow automation.
- Close with a balanced conclusion:
  - The project demonstrates a practical LLMOps-driven NLP system.
  - Further work is needed before large-scale production deployment.

## References

Include citations for:

- Whisper or WhisperX.
- Pyannote diarization.
- Qwen or selected open-source LLM family.
- LoRA, QLoRA, and PEFT.
- RAG and FAISS.
- LLMOps or MLOps principles.
- Hallucination and guardrails.
- Prometheus, Grafana, Docker, FastAPI, Celery, PostgreSQL, Redis if cited as technical foundations.

## Appendices

Potential appendix items:

- API endpoint summary.
- Database schema.
- Docker Compose service list.
- Sample transcript input.
- Sample JSON output.
- Sample prompt template.
- Screenshots of UI.
- Screenshots of Grafana dashboard.
- Evaluation command outputs.
- GitHub repository link.
- Setup and run instructions.

## Writing Standards

- The final report must be written in Vietnamese.
- English can be used only for technical terms, official tool names, model names, framework names, citations, and code identifiers.
- Planning notes and outlines may be written in English, but chapter content, explanations, captions, and academic discussion should be in Vietnamese.
- Use a formal academic tone.
- Avoid marketing language.
- Avoid unsupported claims.
- Clearly distinguish implemented features from planned future work.
- Use diagrams and tables where they improve readability.
- Include a requirement-to-implementation mapping table.
- Include a separate "Implemented vs Prepared vs Future Work" table so the report does not overstate system maturity.
- Be precise about limitations:
  - PII masking is regex-based.
  - The system is not full GDPR compliance.
  - Public cloud deployment is not fully completed.
  - Real-world performance depends on data quality and hardware.
  - Fine-tuning is GPU-ready/prepared unless supported by a specific completed training run and promoted artifact.
