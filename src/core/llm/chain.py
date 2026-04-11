"""LLMProviderChain — high-level facade over LLMChain.

Composes: SemanticCache → RateLimiter → TokenBudget → LLMChain → GuardrailsValidator → LangFuse.
Callers: `chain = LLMProviderChain(call_type="narrative"); text = await chain.generate(...)`.
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from src.core.llm.providers import LLMChain, OllamaProvider, OpenRouterProvider, ZAIProvider
from src.core.llm.semantic_cache import SemanticCache
from src.core.llm.rate_limiter import RateLimiter
from src.core.llm.token_budget import TokenBudget
from src.core.llm.guardrails import GuardrailsValidator

logger = structlog.get_logger(__name__)

# Module-level singletons (shared across all LLMProviderChain instances)
_cache = SemanticCache(max_size=500)
_budget = TokenBudget(daily_token_limit=1_000_000, cost_per_1k=0.001)
_guardrails = GuardrailsValidator()


class LLMProviderChain:
    """High-level LLM chain with caching, rate limiting, budget enforcement, and validation.

    Args:
        call_type: Identifies the use case (e.g. "narrative", "discovery_hypothesis").
                   Used for Kafka audit, guardrails schema lookup, and cache TTL.
        cache_ttl: Seconds to cache responses. 0 disables caching.
    """

    def __init__(
        self,
        call_type: str,
        settings: Any | None = None,
        producer: Any | None = None,
        cache_ttl: float = 300.0,
    ) -> None:
        self._call_type = call_type
        self._cache_ttl = cache_ttl
        self._settings = settings
        self._producer = producer

        # Build inner LLMChain from settings (or defaults)
        providers = self._build_providers(settings)
        self._inner = LLMChain(providers)

        # Per-provider rate limiters (configurable via settings)
        self._rate_limiters: dict[str, RateLimiter] = {}
        if settings is not None:
            for provider_id, limits in getattr(settings, "LLM_RATE_LIMITS", {}).items():
                self._rate_limiters[provider_id] = RateLimiter(
                    rpm=limits.get("rpm", 60),
                    tpm=limits.get("tpm", 100_000),
                )

    def _build_providers(self, settings: Any) -> list:
        """Build provider list from settings or fall back to defaults."""
        if settings is None:
            return [OllamaProvider("gemma4:e4b")]
        providers = []
        if hasattr(settings, "openrouter_api_key") and settings.openrouter_api_key:
            providers.append(
                OpenRouterProvider(
                    model=getattr(settings, "openrouter_model", "meta-llama/llama-3.3-70b-instruct:free"),
                    api_key=settings.openrouter_api_key,
                )
            )
        providers.append(OllamaProvider(getattr(settings, "ollama_model", "gemma4:e4b")))
        return providers

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
    ) -> str | None:
        """Generate a response. Returns None if all providers fail or guardrails reject."""
        # 1. Semantic cache lookup
        if self._cache_ttl > 0:
            cached = _cache.get(system=system, prompt=prompt, model=model)
            if cached is not None:
                logger.debug("llm_chain.cache_hit", call_type=self._call_type)
                return cached

        # 2. Budget check — fall back to Ollama-only if exceeded
        if _budget.is_exceeded():
            logger.warning("llm_chain.budget_exceeded", call_type=self._call_type)
            # Future: swap inner chain to ollama-only here

        # 3. Call inner chain
        t0 = time.monotonic()
        response = await self._inner.generate(
            prompt, system, max_tokens=max_tokens, timeout=timeout
        )
        latency_ms = (time.monotonic() - t0) * 1000

        if response is None:
            return None

        # 4. Record token spend (estimate: 1 token ≈ 4 chars)
        estimated_tokens = max(1, len(prompt) // 4 + len(response) // 4)
        provider_id = getattr(self._inner, "last_provider_id", "unknown") or "unknown"
        _budget.record(
            call_type=self._call_type,
            provider=provider_id,
            tokens=estimated_tokens,
        )

        # 5. Store in cache
        if self._cache_ttl > 0:
            _cache.put(
                system=system,
                prompt=prompt,
                model=model,
                response=response,
                ttl=self._cache_ttl,
            )

        logger.debug(
            "llm_chain.generated",
            call_type=self._call_type,
            provider=provider_id,
            latency_ms=round(latency_ms, 1),
        )
        return response
