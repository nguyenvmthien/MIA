"""Redis prompt cache — avoids re-running LLM for identical (prompt, model) pairs."""

import hashlib
import json
import logging
from collections.abc import Callable

try:
    import redis as redis_lib
    _redis_available = True
except ImportError:
    _redis_available = False

from meeting_agent.config import settings
from meeting_agent.monitoring.metrics import CACHE_HITS, CACHE_MISSES

log = logging.getLogger(__name__)

_client: "redis_lib.Redis | None" = None
_CACHE_TTL_SECONDS = 60 * 60 * 24  # 24 hours


def _get_client():
    global _client
    if _client is None and _redis_available:
        try:
            _client = redis_lib.from_url(settings.redis_url, decode_responses=True)
            _client.ping()
        except Exception as exc:
            log.warning("Redis unavailable — prompt cache disabled: %s", exc)
            _client = None
    return _client


def _cache_key(model: str, system: str, user: str) -> str:
    payload = json.dumps({"model": model, "system": system, "user": user}, sort_keys=True)
    return "prompt_cache:" + hashlib.sha256(payload.encode()).hexdigest()


def cached_llm_call(
    model: str,
    system_prompt: str,
    user_prompt: str,
    call_fn: Callable[[str, str], tuple[str, int]],
) -> tuple[str, int]:
    """
    Wrap an LLM call with Redis caching.

    If an identical (model, system, user) tuple was called before and the result
    is still in cache, return it immediately without hitting Ollama.

    Args:
        model: Ollama model name (used as part of cache key)
        system_prompt: system message
        user_prompt: user message
        call_fn: callable(system, user) -> (content, tokens)

    Returns:
        (content, tokens) — tokens = 0 on cache hit
    """
    client = _get_client()
    key = _cache_key(model, system_prompt, user_prompt)

    if client:
        try:
            cached = client.get(key)
            if cached:
                log.debug("Prompt cache HIT for key %s", key[:16])
                CACHE_HITS.inc()
                return cached, 0
        except Exception as exc:
            log.warning("Redis GET failed: %s", exc)

    CACHE_MISSES.inc()
    content, tokens = call_fn(system_prompt, user_prompt)

    if client:
        try:
            client.setex(key, _CACHE_TTL_SECONDS, content)
        except Exception as exc:
            log.warning("Redis SET failed: %s", exc)

    return content, tokens
