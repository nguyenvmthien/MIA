"""Tests for the Redis prompt cache (Redis mocked)."""

from unittest.mock import MagicMock, patch

from meeting_agent.pipeline.cache import _cache_key, cached_llm_call


def test_cache_key_deterministic():
    k1 = _cache_key("model-a", "sys", "usr")
    k2 = _cache_key("model-a", "sys", "usr")
    assert k1 == k2
    assert k1.startswith("prompt_cache:")


def test_cache_key_different_inputs():
    k1 = _cache_key("model-a", "sys1", "usr")
    k2 = _cache_key("model-a", "sys2", "usr")
    assert k1 != k2


def test_cache_hit_returns_cached_value():
    mock_client = MagicMock()
    mock_client.get.return_value = "cached response"
    call_fn = MagicMock()

    with patch("meeting_agent.pipeline.cache._get_client", return_value=mock_client):
        content, tokens = cached_llm_call("m", "sys", "usr", call_fn)

    assert content == "cached response"
    assert tokens == 0
    call_fn.assert_not_called()


def test_cache_miss_calls_fn_and_stores():
    mock_client = MagicMock()
    mock_client.get.return_value = None
    call_fn = MagicMock(return_value=("llm response", 42))

    with patch("meeting_agent.pipeline.cache._get_client", return_value=mock_client):
        content, tokens = cached_llm_call("m", "sys", "usr", call_fn)

    assert content == "llm response"
    assert tokens == 42
    call_fn.assert_called_once_with("sys", "usr")
    mock_client.setex.assert_called_once()


def test_cache_disabled_when_redis_unavailable():
    """When Redis is unavailable, call_fn is still called and result returned."""
    call_fn = MagicMock(return_value=("response", 10))

    with patch("meeting_agent.pipeline.cache._get_client", return_value=None):
        content, tokens = cached_llm_call("m", "sys", "usr", call_fn)

    assert content == "response"
    assert tokens == 10
    call_fn.assert_called_once()


def test_redis_get_error_falls_through():
    """If Redis.get raises, the LLM is still called."""
    mock_client = MagicMock()
    mock_client.get.side_effect = Exception("connection refused")
    call_fn = MagicMock(return_value=("fallback", 5))

    with patch("meeting_agent.pipeline.cache._get_client", return_value=mock_client):
        content, tokens = cached_llm_call("m", "sys", "usr", call_fn)

    assert content == "fallback"
    call_fn.assert_called_once()
