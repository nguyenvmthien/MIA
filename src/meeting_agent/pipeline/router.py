"""
Distributed Inference Router — load balances LLM calls across multiple Ollama instances.

Supports:
  - Round-robin distribution
  - Least-loaded routing (tracks in-flight requests per endpoint)
  - Health checks with automatic endpoint exclusion
  - Transparent failover to healthy endpoints

Configuration via env vars or config.py:
  OLLAMA_ENDPOINTS=http://host1:11434,http://host2:11434,http://host3:11434
  OLLAMA_ROUTING_STRATEGY=least_loaded   # or round_robin

For single-GPU setups: falls back to the single OLLAMA_BASE_URL transparently.

Usage (automatically activated when OLLAMA_ENDPOINTS is set):
  The orchestrator imports `routed_chat` instead of calling ollama.chat directly.
"""

import itertools
import logging
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import httpx

from meeting_agent.config import settings

log = logging.getLogger(__name__)

_HEALTH_CHECK_INTERVAL = 30   # seconds between passive health checks
_HEALTH_CHECK_TIMEOUT  = 5    # seconds per health check request
_REQUEST_TIMEOUT       = 120  # seconds per inference request


@dataclass
class Endpoint:
    url: str
    healthy: bool = True
    in_flight: int = 0
    total_requests: int = 0
    total_errors: int = 0
    last_checked: float = field(default_factory=time.monotonic)

    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.total_errors / self.total_requests


class InferenceRouter:
    """
    Routes Ollama chat requests across multiple endpoints.

    Thread-safe: uses a lock for in-flight counters and round-robin state.
    """

    def __init__(self, endpoints: list[str], strategy: str = "least_loaded"):
        if not endpoints:
            raise ValueError("At least one endpoint is required")
        self._endpoints = [Endpoint(url=url.rstrip("/")) for url in endpoints]
        self._strategy = strategy
        self._lock = threading.Lock()
        self._rr: Iterator = itertools.cycle(self._endpoints)
        log.info(
            "InferenceRouter initialized: %d endpoints, strategy=%s",
            len(self._endpoints), strategy,
        )
        # Start background health checker
        t = threading.Thread(target=self._health_loop, daemon=True)
        t.start()

    # ── Health checking ───────────────────────────────────────────────────────

    def _check_health(self, ep: Endpoint) -> bool:
        try:
            resp = httpx.get(f"{ep.url}/api/tags", timeout=_HEALTH_CHECK_TIMEOUT)
            return resp.status_code == 200
        except Exception:
            return False

    def _health_loop(self) -> None:
        while True:
            time.sleep(_HEALTH_CHECK_INTERVAL)
            for ep in self._endpoints:
                was_healthy = ep.healthy
                ep.healthy = self._check_health(ep)
                ep.last_checked = time.monotonic()
                if was_healthy and not ep.healthy:
                    log.warning("Endpoint went unhealthy: %s", ep.url)
                elif not was_healthy and ep.healthy:
                    log.info("Endpoint recovered: %s", ep.url)

    def _healthy_endpoints(self) -> list[Endpoint]:
        healthy = [ep for ep in self._endpoints if ep.healthy]
        if not healthy:
            log.warning("All endpoints unhealthy — using all as fallback")
            return list(self._endpoints)
        return healthy

    # ── Routing strategies ────────────────────────────────────────────────────

    def _pick_round_robin(self) -> Endpoint:
        with self._lock:
            for _ in range(len(self._endpoints)):
                ep = next(self._rr)
                if ep.healthy:
                    return ep
        return self._endpoints[0]

    def _pick_least_loaded(self) -> Endpoint:
        candidates = self._healthy_endpoints()
        with self._lock:
            return min(candidates, key=lambda ep: ep.in_flight)

    def _pick(self) -> Endpoint:
        if self._strategy == "round_robin":
            return self._pick_round_robin()
        return self._pick_least_loaded()

    # ── Public chat interface ─────────────────────────────────────────────────

    def chat(self, model: str, messages: list[dict], options: dict | None = None) -> dict:
        """
        Route a chat request to the best available endpoint.
        Retries on the next endpoint if the chosen one fails.
        """
        tried: set[str] = set()
        last_exc: Exception | None = None

        for _ in range(len(self._endpoints)):
            ep = self._pick()
            if ep.url in tried:
                continue
            tried.add(ep.url)

            with self._lock:
                ep.in_flight += 1
                ep.total_requests += 1

            try:
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    **({"options": options} if options else {}),
                }
                resp = httpx.post(
                    f"{ep.url}/api/chat",
                    json=payload,
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                log.debug("Routed to %s — tokens=%s", ep.url,
                          data.get("eval_count", "?"))
                return data

            except Exception as exc:
                last_exc = exc
                with self._lock:
                    ep.total_errors += 1
                    ep.healthy = False
                log.warning("Endpoint %s failed (%s) — trying next", ep.url, exc)

            finally:
                with self._lock:
                    ep.in_flight = max(0, ep.in_flight - 1)

        raise RuntimeError(
            f"All endpoints failed. Last error: {last_exc}"
        )

    def stats(self) -> list[dict]:
        return [
            {
                "url": ep.url,
                "healthy": ep.healthy,
                "in_flight": ep.in_flight,
                "total_requests": ep.total_requests,
                "error_rate": round(ep.error_rate(), 4),
            }
            for ep in self._endpoints
        ]


# ── Singleton router (built once at import time) ──────────────────────────────

def _build_router() -> InferenceRouter | None:
    """
    Build the router from OLLAMA_ENDPOINTS env var.
    Falls back to None (single endpoint) when not set.
    """
    import os
    endpoints_str = os.environ.get("OLLAMA_ENDPOINTS", "").strip()
    if not endpoints_str:
        return None   # single-node mode — use ollama library directly

    endpoints = [e.strip() for e in endpoints_str.split(",") if e.strip()]
    strategy = os.environ.get("OLLAMA_ROUTING_STRATEGY", "least_loaded")
    return InferenceRouter(endpoints, strategy=strategy)


_router: InferenceRouter | None = _build_router()


def routed_chat(
    model: str,
    messages: list[dict],
    options: dict | None = None,
    meeting_id: str | None = None,
) -> dict:
    """
    Drop-in replacement for `ollama.chat(...)`.

    - When OLLAMA_ENDPOINTS is set: routes through the InferenceRouter.
    - Otherwise: falls back to the standard ollama library.
    - When an A/B test is active and meeting_id is provided, overrides model selection.
    """
    # A/B model override
    effective_model = model
    ab_experiment_id: str | None = None
    if meeting_id:
        try:
            import sys
            from pathlib import Path as _Path
            sys.path.insert(0, str(_Path(__file__).parent.parent.parent.parent / "train"))
            from ab_test import get_model_for_meeting, load_state as _ab_load_state
            effective_model = get_model_for_meeting(meeting_id)
            if effective_model != model:
                log.info("A/B override: meeting=%s model=%s→%s", meeting_id, model, effective_model)
            _ab_state = _ab_load_state()
            ab_experiment_id = _ab_state.get("experiment_id") if _ab_state.get("active") else None
        except Exception as e:
            log.debug("A/B test lookup failed (non-fatal): %s", e)

    start_ms = time.monotonic() * 1000

    if _router is not None:
        result = _router.chat(effective_model, messages, options)
    else:
        import ollama as ollama_client  # type: ignore
        client = ollama_client.Client(host=settings.ollama_base_url)
        response = client.chat(
            model=effective_model,
            messages=messages,
            options=options or {},
        )
        result = response.model_dump()  # type: ignore[union-attr]

    # Log A/B result metrics
    if meeting_id and ab_experiment_id:
        try:
            from ab_test import log_result as _ab_log
            latency_ms = time.monotonic() * 1000 - start_ms
            eval_count = result.get("eval_count") or 0
            prompt_count = result.get("prompt_eval_count") or 0
            _ab_log(
                experiment_id=ab_experiment_id,
                model=effective_model,
                meeting_id=meeting_id,
                metrics={
                    "llm_latency_ms": round(latency_ms, 1),
                    "total_tokens": eval_count + prompt_count,
                },
            )
        except Exception as e:
            log.debug("A/B result logging failed (non-fatal): %s", e)

    return result


def router_stats() -> list[dict]:
    """Return per-endpoint health/load stats (for the /admin/router-stats API endpoint)."""
    if _router is None:
        return [{"url": settings.ollama_base_url, "healthy": True,
                 "in_flight": 0, "total_requests": 0, "error_rate": 0.0}]
    return _router.stats()
