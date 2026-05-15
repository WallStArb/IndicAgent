"""LLMProviderChain — high-level facade over LLMChain.

Composes: SemanticCache → RateLimiter → LLMChain → GuardrailsValidator → Audit.
Callers: `chain = LLMProviderChain(call_type="narrative"); text = await chain.generate(...)`.
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.core.llm.guardrails import GuardrailsValidator
from src.core.llm.providers import LLMChain, OllamaProvider
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
    """High-level LLM chain with caching, rate limiting, budget tracking, and validation.

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

    @property
    def last_provider_id(self) -> str | None:
        """Provider that served the last request — format: 'ollama:qwen3.5:4b'."""
        return self._inner.last_provider_id

    def _build_providers(self, settings: Any) -> list:
        """Build provider list from settings. Currently Ollama-only.

        To add providers: instantiate them here in priority order.
        LLMChain tries each in order, returning the first non-None response.
        """
        if settings is None:
            return [OllamaProvider("nemotron-3-nano:4b")]
        return [OllamaProvider(model=settings.ollama_model, base_url=settings.ollama_base_url)]

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str = "default",
        audit_context: dict | None = None,
    ) -> str | None:
        """Generate a response. Returns None if all providers fail or guardrails reject."""
        # 1. Cache lookup
        if self._cache_ttl > 0:
            cached = _cache.get(system=system, prompt=prompt, model=model)
            if cached is not None:
                LLM_CACHE_HITS.labels(call_type=self._call_type).inc()
                logger.debug("llm_chain.cache_hit", call_type=self._call_type)
                return cached

        # 2. Rate limiter
        limiter = self._rate_limiters.get(self._inner.last_provider_id) or next(
            iter(self._rate_limiters.values()), None
        )
        if limiter is not None:
            await limiter.acquire(tokens=max_tokens)

        # 3. LLM call
        t0 = time.monotonic()
        response = await self._inner.generate(
            prompt, system, max_tokens=max_tokens, timeout=timeout
        )
        latency_s = time.monotonic() - t0
        provider_id = self._inner.last_provider_id or "unknown"

        # 4. Failure
        if response is None:
            record_llm_call(provider_id, self._call_type, latency_s, status="failure")
            return None

        # 5. Guardrails
        if _guardrails.has_schema(self._call_type):
            validated = _guardrails.validate(self._call_type, response)
            if validated is None:
                LLM_GUARDRAILS_REJECTIONS.labels(call_type=self._call_type).inc()
                record_llm_call(
                    provider_id, self._call_type, latency_s, status="guardrails_rejected"
                )
                logger.warning("llm_chain.guardrails_rejected", call_type=self._call_type)
                return None

        # 6. Token counting — provider-reported or len/4 estimate
        token_usage = self._inner.last_token_usage
        actual_total = token_usage.get("total_tokens") if isinstance(token_usage, dict) else None
        tokens = (
            actual_total
            if (actual_total and actual_total > 0)
            else max(1, len(prompt) // 4 + len(response) // 4)
        )

        # 7. Budget recording (observability — never gates execution)
        _budget.record(call_type=self._call_type, provider=provider_id, tokens=tokens)
        if _budget.is_exceeded():
            logger.warning(
                "llm_chain.budget_threshold",
                call_type=self._call_type,
                total_tokens=_budget.total_tokens_today(),
                estimated_cost=_budget.estimated_cost_today(),
            )

        # 8. Metrics
        record_llm_call(provider_id, self._call_type, latency_s, tokens=tokens)

        # 9. Cache put
        if self._cache_ttl > 0:
            _cache.put(
                system=system, prompt=prompt, model=model, response=response, ttl=self._cache_ttl
            )

        # 10. Audit trail
        await self._publish_audit(audit_context, provider_id, latency_s, tokens, response, model)

        logger.debug(
            "llm_chain.generated",
            call_type=self._call_type,
            provider=provider_id,
            latency_ms=round(latency_s * 1000, 1),
        )
        return response

    async def _publish_audit(
        self,
        audit_context: dict | None,
        provider_id: str,
        latency_s: float,
        tokens: int,
        response: str,
        model: str,
    ) -> None:
        """Publish LLM call audit to topic_llm_calls."""
        if audit_context is None or self._producer is None:
            return
        from src.core.stream_keys import topic_llm_calls

        try:
            await self._producer.publish(
                topic_llm_calls(self._settings.env_name),
                {
                    **audit_context,
                    "response": response,
                    "provider": provider_id,
                    "call_type": self._call_type,
                    "tokens_est": tokens,
                    "model": model,
                    "latency_ms": int(latency_s * 1000),
                },
            )
        except Exception:
            logger.exception("auto_audit.publish_failed", call_type=self._call_type)
