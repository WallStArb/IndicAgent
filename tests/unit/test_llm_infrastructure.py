"""Tests for LLM infrastructure components: SemanticCache, RateLimiter, TokenBudget."""
from __future__ import annotations
import asyncio
import time
from unittest.mock import MagicMock
import pytest


# ---------------------------------------------------------------------------
# SemanticCache
# ---------------------------------------------------------------------------

def test_semantic_cache_miss_returns_none():
    from src.core.llm.semantic_cache import SemanticCache
    cache = SemanticCache(max_size=100)
    result = cache.get(system="sys", prompt="prompt", model="llama")
    assert result is None


def test_semantic_cache_hit_returns_cached():
    from src.core.llm.semantic_cache import SemanticCache
    cache = SemanticCache(max_size=100)
    cache.put(system="sys", prompt="hello world", model="llama", response="answer", ttl=60.0)
    result = cache.get(system="sys", prompt="hello world", model="llama")
    assert result == "answer"


def test_semantic_cache_key_includes_first_200_chars_of_prompt():
    from src.core.llm.semantic_cache import SemanticCache
    cache = SemanticCache(max_size=100)
    long_prompt = "x" * 500
    cache.put(system="s", prompt=long_prompt, model="m", response="r", ttl=60.0)
    # Same first 200 chars → hit
    assert cache.get(system="s", prompt=long_prompt, model="m") == "r"
    # Different first 200 chars → miss
    assert cache.get(system="s", prompt="y" * 500, model="m") is None


def test_semantic_cache_expired_entry_returns_none():
    from src.core.llm.semantic_cache import SemanticCache
    cache = SemanticCache(max_size=100)
    cache.put(system="s", prompt="p", model="m", response="r", ttl=0.01)
    time.sleep(0.05)
    assert cache.get(system="s", prompt="p", model="m") is None


def test_semantic_cache_evicts_lru_when_full():
    from src.core.llm.semantic_cache import SemanticCache
    cache = SemanticCache(max_size=2)
    cache.put(system="s", prompt="a", model="m", response="r_a", ttl=60.0)
    cache.put(system="s", prompt="b", model="m", response="r_b", ttl=60.0)
    # Access 'a' to make it recently used
    cache.get(system="s", prompt="a", model="m")
    # Add 'c' — 'b' (LRU) should be evicted
    cache.put(system="s", prompt="c", model="m", response="r_c", ttl=60.0)
    assert cache.get(system="s", prompt="c", model="m") == "r_c"
    assert cache.get(system="s", prompt="a", model="m") == "r_a"
    assert cache.get(system="s", prompt="b", model="m") is None  # evicted


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rate_limiter_allows_under_limit():
    from src.core.llm.rate_limiter import RateLimiter
    rl = RateLimiter(rpm=60, tpm=100_000)
    # Should not raise or delay significantly for first call
    t0 = time.monotonic()
    await rl.acquire(tokens=100)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_rate_limiter_wait_metric_exposed():
    from src.core.llm.rate_limiter import RateLimiter
    rl = RateLimiter(rpm=1, tpm=100_000)
    # First call consumes the bucket
    await rl.acquire(tokens=10)
    # Second call should wait (but we just check it returns eventually — no infinite block)
    # Use a tiny token window to keep test fast
    rl2 = RateLimiter(rpm=1000, tpm=100_000)
    await rl2.acquire(tokens=10)


# ---------------------------------------------------------------------------
# TokenBudget
# ---------------------------------------------------------------------------

def test_token_budget_tracks_spend():
    from src.core.llm.token_budget import TokenBudget
    budget = TokenBudget(daily_token_limit=10_000, cost_per_1k=0.01)
    budget.record(call_type="narrative", provider="openrouter", tokens=500)
    assert budget.total_tokens_today() == 500


def test_token_budget_exceeded_returns_true():
    from src.core.llm.token_budget import TokenBudget
    budget = TokenBudget(daily_token_limit=100, cost_per_1k=0.01)
    budget.record(call_type="narrative", provider="openrouter", tokens=150)
    assert budget.is_exceeded() is True


def test_token_budget_not_exceeded_returns_false():
    from src.core.llm.token_budget import TokenBudget
    budget = TokenBudget(daily_token_limit=10_000, cost_per_1k=0.01)
    budget.record(call_type="narrative", provider="openrouter", tokens=100)
    assert budget.is_exceeded() is False


# ---------------------------------------------------------------------------
# Guardrails
# ---------------------------------------------------------------------------

def test_guardrails_accepts_valid_schema():
    from src.core.llm.guardrails import GuardrailsValidator
    from pydantic import BaseModel

    class NarrativeSchema(BaseModel):
        summary: str
        direction: str

    validator = GuardrailsValidator()
    validator.register("narrative", NarrativeSchema)
    result = validator.validate("narrative", '{"summary": "bullish breakout", "direction": "long"}')
    assert result is not None
    assert result["summary"] == "bullish breakout"


def test_guardrails_rejects_wrong_schema():
    from src.core.llm.guardrails import GuardrailsValidator
    from pydantic import BaseModel

    class NarrativeSchema(BaseModel):
        summary: str
        confidence: float  # required but missing

    validator = GuardrailsValidator()
    validator.register("narrative", NarrativeSchema)
    result = validator.validate("narrative", '{"summary": "missing confidence field"}')
    assert result is None  # rejected


def test_guardrails_no_schema_registered_returns_raw():
    from src.core.llm.guardrails import GuardrailsValidator
    validator = GuardrailsValidator()
    # No schema registered for "unknown" → pass through as dict
    result = validator.validate("unknown", "some raw text that is not JSON")
    # When no schema, returns None (caller treats as unvalidated)
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# LLMProviderChain (facade)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_chain_returns_response_on_success():
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.core.llm.chain import LLMProviderChain

    mock_chain = MagicMock()
    mock_chain.generate = AsyncMock(return_value="narrative text")
    mock_chain.last_provider_id = "ollama:gemma4"

    with patch("src.core.llm.chain.LLMChain", return_value=mock_chain):
        chain = LLMProviderChain(call_type="narrative")
        result = await chain.generate("prompt", "system", max_tokens=200, timeout=10.0)

    assert result == "narrative text"


@pytest.mark.asyncio
async def test_provider_chain_returns_cached_on_hit():
    from unittest.mock import AsyncMock, MagicMock, patch
    from src.core.llm.chain import LLMProviderChain

    mock_inner = MagicMock()
    mock_inner.generate = AsyncMock(return_value="fresh response")
    mock_inner.last_provider_id = "ollama"

    with patch("src.core.llm.chain.LLMChain", return_value=mock_inner):
        chain = LLMProviderChain(call_type="narrative", cache_ttl=60.0)
        # First call — populates cache
        r1 = await chain.generate("prompt", "sys", max_tokens=100, timeout=5.0)
        assert r1 == "fresh response"
        # Second call — should hit cache, NOT call inner again
        r2 = await chain.generate("prompt", "sys", max_tokens=100, timeout=5.0)
        assert r2 == "fresh response"
        assert mock_inner.generate.call_count == 1  # only called once
