"""LLMProviderChain — high-level facade over LLMChain.

Composes: SemanticCache → RateLimiter → TokenBudget → LLMChain → GuardrailsValidator → LangFuse.
Callers: `chain = LLMProviderChain(call_type="narrative"); text = await chain.generate(...)`.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.core.llm.guardrails import GuardrailsValidator
from src.core.llm.providers import (
    LLMChain,
    OllamaProvider,
    OpenRouterProvider,
)
from src.core.llm.rate_limiter import RateLimiter
from src.core.llm.semantic_cache import SemanticCache
from src.core.llm.token_budget import TokenBudget
from src.observability.metrics import (
    LLM_CACHE_HITS,
    LLM_GUARDRAILS_REJECTIONS,
    record_llm_call,
)

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
        """Build provider list: OpenRouter free → Ollama local."""
        if settings is None:
            return [OllamaProvider("nemotron-3-nano:4b")]
        providers = []

        # 1. OpenRouter free models (thinking suppressed via include_reasoning=false)
        if settings.openrouter_api_key:
            for slug in settings.openrouter_models.split(","):
                slug = slug.strip()
                if slug:
                    providers.append(
                        OpenRouterProvider(model=slug, api_key=settings.openrouter_api_key)
                    )

        # 2. Ollama local (offline fallback)
        providers.append(
            OllamaProvider(model=settings.ollama_model, base_url=settings.ollama_base_url)
        )
        return providers

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
        audit_context: dict | None = None,  # D-06: auto-audit
    ) -> str | None:
        """Generate a response. Returns None if all providers fail or guardrails reject."""
        # 1. Semantic cache lookup
        if self._cache_ttl > 0:
            cached = _cache.get(system=system, prompt=prompt, model=model)
            if cached is not None:
                LLM_CACHE_HITS.labels(call_type=self._call_type).inc()
                logger.debug("llm_chain.cache_hit", call_type=self._call_type)
                return cached

        # D-04: Rate limiter — covers OpenRouter + OllamaCloud + OllamaLocal
        limiter = self._rate_limiters.get(self._inner.last_provider_id) or next(
            iter(self._rate_limiters.values()), None
        )
        if limiter is not None:
            await limiter.acquire(tokens=max_tokens)

        # 2. Budget check — route to Ollama-only if daily budget exceeded
        if _budget.is_exceeded():
            logger.warning("llm_chain.budget_exceeded", call_type=self._call_type)
            ollama_providers = [p for p in self._inner.providers if isinstance(p, OllamaProvider)]
            if not ollama_providers:
                return None
            t0 = time.monotonic()
            response = await LLMChain(ollama_providers).generate(
                prompt, system, max_tokens=max_tokens, timeout=timeout
            )
            latency_s = time.monotonic() - t0
            if response is None:
                record_llm_call("ollama", self._call_type, latency_s, status="failure")
                return None
            estimated_tokens = max(1, len(prompt) // 4 + len(response) // 4)
            _budget.record(call_type=self._call_type, provider="ollama", tokens=estimated_tokens)
            record_llm_call("ollama", self._call_type, latency_s, tokens=estimated_tokens)
            if self._cache_ttl > 0:
                _cache.put(
                    system=system,
                    prompt=prompt,
                    model=model,
                    response=response,
                    ttl=self._cache_ttl,
                )
            return response

        # 3. Call inner chain
        t0 = time.monotonic()
        response = await self._inner.generate(
            prompt, system, max_tokens=max_tokens, timeout=timeout
        )
        latency_s = time.monotonic() - t0
        provider_id = getattr(self._inner, "last_provider_id", "unknown") or "unknown"

        if response is None:
            record_llm_call(provider_id, self._call_type, latency_s, status="failure")
            return None

        # D-05: Use public has_schema() method instead of private _schemas access
        if _guardrails.has_schema(self._call_type):
            validated = _guardrails.validate(self._call_type, response)
            if validated is None:
                LLM_GUARDRAILS_REJECTIONS.labels(call_type=self._call_type).inc()
                record_llm_call(
                    provider_id, self._call_type, latency_s, status="guardrails_rejected"
                )
                logger.warning("llm_chain.guardrails_rejected", call_type=self._call_type)
                return None

        # D-07: Real token counts from provider, with len/4 fallback (Gemini review)
        token_usage = getattr(self._inner, "last_token_usage", None)
        actual_total = token_usage.get("total_tokens") if isinstance(token_usage, dict) else None
        if actual_total is not None and actual_total > 0:
            tokens = actual_total
        else:
            # Fallback: character-count estimate (Gemini review suggestion)
            tokens = max(1, len(prompt) // 4 + (len(response) // 4 if response else 0))

        _budget.record(
            call_type=self._call_type,
            provider=provider_id,
            tokens=tokens,
        )

        record_llm_call(provider_id, self._call_type, latency_s, tokens=tokens)

        # 6. Store in cache
        if self._cache_ttl > 0:
            _cache.put(
                system=system,
                prompt=prompt,
                model=model,
                response=response,
                ttl=self._cache_ttl,
            )

        # D-06: Auto-audit — publish to topic_llm_calls when audit_context provided
        if audit_context is not None and self._producer is not None:
            from src.core.stream_keys import topic_llm_calls

            try:
                await self._producer.publish(
                    topic_llm_calls(self._settings.env_name),
                    {
                        **audit_context,
                        "response": response,
                        "provider": provider_id,
                        "call_type": self._call_type,
                        "tokens": tokens,
                        "model": model,
                    },
                )
            except Exception:
                logger.exception("auto_audit.publish_failed", call_type=self._call_type)

        logger.debug(
            "llm_chain.generated",
            call_type=self._call_type,
            provider=provider_id,
            latency_ms=round(latency_s * 1000, 1),
        )
        return response
