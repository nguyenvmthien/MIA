"""
Stage 4 — Orchestrator: builds prompts, calls Ollama, runs guardrails.

This is the AI/ML CORE — it drives the LLM interaction for both
meeting summarization and action item extraction.

Wired integrations:
  - LangSmith tracing via @traceable
  - Redis prompt cache via pipeline.cache
  - FAISS speaker RAG via pipeline.rag
  - PII masking on logged text via pipeline.pii
"""

import logging
import os
import time
from datetime import date, timedelta

from tenacity import retry, stop_after_attempt, wait_fixed

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import (
    LLM_CALLS,
    LLM_CHUNKS,
    LLM_TOKENS,
    RAG_QUERIES,
    STAGE_LATENCY,
)
from meeting_agent.pipeline.cache import cached_llm_call
from meeting_agent.pipeline.guardrails import GuardrailError, parse_and_validate
from meeting_agent.pipeline.pii import mask_pii
from meeting_agent.pipeline.rag import SpeakerIndex
from meeting_agent.pipeline.router import routed_chat
from meeting_agent.prompts.templates import (
    EXTRACT_TASKS_SYSTEM,
    EXTRACT_TASKS_USER,
    SUMMARIZE_SYSTEM,
    SUMMARIZE_USER,
)
from meeting_agent.schemas.task import ExtractedTask
from meeting_agent.schemas.transcript import TranscriptTurn
from meeting_agent.schemas.worker import WorkerRoster

log = logging.getLogger(__name__)

# ── LangSmith tracing (optional — disabled if API key not set) ────────────────
_traceable = None
if settings.langchain_tracing_v2 and settings.langchain_api_key:
    try:
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langchain_api_key)
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.langchain_project)
        from langsmith import traceable as _traceable_fn
        _traceable = _traceable_fn
        log.info("LangSmith tracing enabled (project: %s)", settings.langchain_project)
    except ImportError:
        log.warning("langsmith not installed — tracing disabled")


def _maybe_trace(fn):
    """Apply @traceable only when LangSmith is configured."""
    if _traceable is not None:
        return _traceable(run_type="llm", name=fn.__name__)(fn)
    return fn


# Max tokens per transcript chunk
CHUNK_TOKEN_BUDGET = 2000
WORDS_PER_TOKEN = 0.75


def _chunk_turns(turns: list[TranscriptTurn], budget: int) -> list[list[TranscriptTurn]]:
    """Split turns into chunks that fit within the token budget."""
    chunks: list[list[TranscriptTurn]] = []
    current: list[TranscriptTurn] = []
    current_words = 0
    for turn in turns:
        est = int(len(turn.text.split()) / WORDS_PER_TOKEN)
        if current and current_words + est > budget:
            chunks.append(current)
            current = [turn]
            current_words = est
        else:
            current.append(turn)
            current_words += est
    if current:
        chunks.append(current)
    return chunks


def _turns_to_text(turns: list[TranscriptTurn]) -> str:
    return "\n".join(f"[{t.display_name}]: {t.text}" for t in turns)


def _next_friday() -> str:
    today = date.today()
    days_ahead = 4 - today.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return (today + timedelta(days=days_ahead)).isoformat()


# ── Core LLM call (traced + cached) ──────────────────────────────────────────

@_maybe_trace
@retry(stop=stop_after_attempt(settings.llm_max_retries), wait=wait_fixed(1))
def _raw_llm_call(
    system_prompt: str,
    user_prompt: str,
    meeting_id: str | None = None,
) -> tuple[str, int]:
    """
    LLM call routed through InferenceRouter (multi-Ollama) or single Ollama.
    Traced by LangSmith when configured.
    """
    LLM_CALLS.inc()
    response = routed_chat(
        model=settings.ollama_llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        options={"temperature": 0.0, "seed": 42},
        meeting_id=meeting_id,
    )
    content: str = response["message"]["content"]
    tokens: int = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)
    LLM_TOKENS.inc(tokens)
    return content, tokens


def _call_llm(
    system_prompt: str,
    user_prompt: str,
    meeting_id: str | None = None,
) -> tuple[str, int]:
    """LLM call with Redis prompt cache + PII-masked logging."""
    log.debug("LLM call | system=%s…", mask_pii(system_prompt[:80]))

    def _call_fn(sys_p: str, usr_p: str) -> tuple[str, int]:
        return _raw_llm_call(sys_p, usr_p, meeting_id=meeting_id)

    return cached_llm_call(
        model=settings.ollama_llm_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        call_fn=_call_fn,
    )


# ── Public pipeline functions ─────────────────────────────────────────────────

def extract_action_items(
    turns: list[TranscriptTurn],
    roster: WorkerRoster,
    meeting_date: str,
    meeting_id: str,
) -> tuple[list[ExtractedTask], int]:
    """
    Extract action items from all transcript turns via chunked LLM calls.

    Uses FAISS speaker RAG to enrich context when the index is ready.

    Returns:
        - flat list of ExtractedTask across all chunks
        - total tokens used
    """
    t0 = time.monotonic()
    participants = sorted({t.display_name for t in turns})
    chunks = _chunk_turns(turns, CHUNK_TOKEN_BUDGET)

    # Build speaker index for RAG context enrichment
    speaker_index = SpeakerIndex()
    speaker_index.build(turns)

    system_prompt = EXTRACT_TASKS_SYSTEM.format(
        roster=roster.names_for_prompt(),
        friday=_next_friday(),
    )

    all_tasks: list[ExtractedTask] = []
    total_tokens = 0

    for chunk_idx, chunk in enumerate(chunks):
        transcript_text = _turns_to_text(chunk)

        # RAG: retrieve relevant past context for this chunk
        rag_context = ""
        if speaker_index.is_ready:
            relevant = speaker_index.query(transcript_text, top_k=3)
            if relevant:
                rag_context = "\nRELEVANT CONTEXT:\n" + "\n".join(relevant)
                RAG_QUERIES.labels(result="hit").inc()
            else:
                RAG_QUERIES.labels(result="miss").inc()
        LLM_CHUNKS.inc()

        user_prompt = EXTRACT_TASKS_USER.format(
            meeting_date=meeting_date,
            participants=", ".join(participants),
            transcript=transcript_text + rag_context,
        )

        source_turn_ids = [t.turn_id for t in chunk]
        task_id_prefix = f"{meeting_id}_c{chunk_idx}"

        try:
            raw_output, tokens = _call_llm(system_prompt, user_prompt, meeting_id=meeting_id)
            total_tokens += tokens
            tasks = parse_and_validate(
                raw_output,
                roster=roster,
                turns=chunk,
                source_turn_ids=source_turn_ids,
                task_id_prefix=task_id_prefix,
            )
            all_tasks.extend(tasks)
        except GuardrailError as exc:
            log.warning("Guardrail error in chunk %d: %s", chunk_idx, exc)
            continue

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    STAGE_LATENCY.labels(stage="llm").observe(elapsed_ms / 1000)
    return all_tasks, total_tokens


def summarize_meeting(
    turns: list[TranscriptTurn],
    meeting_date: str,
    duration_ms: int,
) -> str:
    """Generate a concise meeting summary via the LLM."""
    participants = sorted({t.display_name for t in turns})
    duration_minutes = duration_ms // 60000

    full_text = _turns_to_text(turns)
    words = full_text.split()
    if len(words) > int(CHUNK_TOKEN_BUDGET * 2 * WORDS_PER_TOKEN):
        limit = int(CHUNK_TOKEN_BUDGET * 2 * WORDS_PER_TOKEN)
        full_text = " ".join(words[:limit]) + " [truncated]"

    user_prompt = SUMMARIZE_USER.format(
        meeting_date=meeting_date,
        participants=", ".join(participants),
        duration_minutes=duration_minutes,
        transcript=full_text,
    )

    summary, _ = _call_llm(SUMMARIZE_SYSTEM, user_prompt)
    return summary.strip()
