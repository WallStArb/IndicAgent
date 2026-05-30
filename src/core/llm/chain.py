"""LLMProviderChain — high-level facade over LiteLLMBackend.

Composes: SemanticCache → RateLimiter → LiteLLMBackend → Audit.
Callers: `chain = LLMProviderChain(call_type="narrative"); text = await chain.generate(...)`.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from opentelemetry.metrics import CallbackOptions
from opentelemetry.metrics import Observation as _Observation
from opentelemetry.trace import StatusCode
from pydantic import BaseModel

from src.core.llm.litellm_backend import LiteLLMBackend
from src.core.llm.rate_limiter import RateLimiter
from src.core.llm.semantic_cache import SemanticCache
from src.core.llm.token_budget import TokenBudget
from src.observability.metrics import (
    LLM_CACHE_HITS,
    LLM_RESPONSE_CHARS,
    _meter,
    record_llm_call,
)
from src.observability.otel import get_tracer

logger = structlog.get_logger(__name__)
_tracer = get_tracer("llm.chain")

# Module-level singletons (shared across all LLMProviderChain instances)
_cache = SemanticCache(max_size=500)
_budget = TokenBudget(daily_token_limit=1_000_000, cost_per_1k=0.001)


_EMPTY_ATTRS: dict[str, str] = {}


def _observe_budget_pct(options: CallbackOptions):
    yield _Observation(_budget.utilization_pct(), _EMPTY_ATTRS)


_meter.create_observable_gauge(
    "llm_token_budget_pct_used",
    callbacks=[_observe_budget_pct],
    description="Daily token budget utilization 0-100",
    unit="%",
)


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

        self._inner = LiteLLMBackend(settings)

        self._rate_limiters: dict[str, RateLimiter] = self._make_rate_limiters(settings)

    @property
    def last_provider_id(self) -> str | None:
        """Provider that served the last request — format: 'ollama/nemotron-3-nano:4b'."""
        return self._inner.last_provider_id

    @staticmethod
    def _make_rate_limiters(settings: Any) -> dict[str, RateLimiter]:
        limiters: dict[str, RateLimiter] = {}
        if settings is not None:
            for provider_id, limits in getattr(settings, "LLM_RATE_LIMITS", {}).items():
                limiters[provider_id] = RateLimiter(
                    rpm=limits.get("rpm", 60),
                    tpm=limits.get("tpm", 100_000),
                    provider_id=provider_id,
                )
        return limiters

    async def close(self) -> None:
        """No-op: LiteLLM manages its own HTTP connection pool internally."""
        pass

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
        with _tracer.start_as_current_span(
            "llm.generate",
            attributes={"call_type": self._call_type, "model": model},
        ) as span:
            try:
                return await self._generate_inner(
                    span, prompt, system, max_tokens, timeout, model, audit_context
                )
            except Exception as exc:
                span.set_status(StatusCode.ERROR, str(exc))
                span.record_exception(exc)
                raise

    async def _generate_inner(
        self,
        span: Any,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
        model: str,
        audit_context: dict | None,
    ) -> str | None:
        if self._cache_ttl > 0:
            cached = _cache.get(system=system, prompt=prompt, model=model)
            if cached is not None:
                LLM_CACHE_HITS.add(1, {"call_type": self._call_type})
                span.set_attribute("llm.cache_hit", True)
                logger.debug("llm_chain.cache_hit", call_type=self._call_type)
                return cached

        limiter = self._rate_limiters.get(self._inner.last_provider_id) or next(
            iter(self._rate_limiters.values()), None
        )
        if limiter is not None:
            await limiter.acquire(tokens=max_tokens)

        t0 = time.monotonic()
        response = await self._inner.generate(
            prompt, system, max_tokens=max_tokens, timeout=timeout
        )
        latency_s = time.monotonic() - t0
        provider_id = self._inner.last_provider_id or "unknown"
        span.set_attribute("llm.provider", provider_id)
        span.set_attribute("llm.latency_ms", round(latency_s * 1000, 1))

        if response is None:
            record_llm_call(provider_id, self._call_type, latency_s, status="failure")
            span.set_attribute("llm.status", "failure")
            return None

        LLM_RESPONSE_CHARS.record(
            len(response), {"provider": provider_id, "call_type": self._call_type}
        )

        token_usage = self._inner.last_token_usage
        actual_total = token_usage.get("total_tokens") if isinstance(token_usage, dict) else None
        tokens = (
            actual_total
            if (actual_total and actual_total > 0)
            else max(1, len(prompt) // 4 + len(response) // 4)
        )
        span.set_attribute("llm.tokens", tokens)

        # budget is observability-only — never gates execution
        _budget.record(call_type=self._call_type, provider=provider_id, tokens=tokens)
        if _budget.is_exceeded():
            logger.warning(
                "llm_chain.budget_threshold",
                call_type=self._call_type,
                total_tokens=_budget.total_tokens_today(),
                estimated_cost=_budget.estimated_cost_today(),
            )

        record_llm_call(provider_id, self._call_type, latency_s, tokens=tokens)

        if self._cache_ttl > 0:
            _cache.put(
                system=system, prompt=prompt, model=model, response=response, ttl=self._cache_ttl
            )

        await self._publish_audit(audit_context, provider_id, latency_s, tokens, response, model)

        logger.debug(
            "llm_chain.generated",
            call_type=self._call_type,
            provider=provider_id,
            latency_ms=round(latency_s * 1000, 1),
        )
        return response

    async def generate_structured(
        self,
        prompt: str,
        system: str,
        response_model: type[BaseModel],
        max_tokens: int = 500,
        timeout: float = 120.0,
        audit_context: dict | None = None,
        extra_audit: dict | None = None,
    ) -> BaseModel | None:
        """Structured output via instructor. Returns validated BaseModel or None on failure.

        Publishes an llm_calls audit row on BOTH success and failure (H1).
        Accepts extra_audit kwarg for additional audit fields, same as generate() (M4).
        Sets llm.instructor_retries span attribute.
        """
        with _tracer.start_as_current_span(
            "llm.generate_structured",
            attributes={"call_type": self._call_type},
        ) as span:
            t0 = time.monotonic()
            result = await self._inner.generate_structured(
                prompt=prompt,
                system=system,
                response_model=response_model,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            latency_s = time.monotonic() - t0
            provider_id = self._inner.last_provider_id or "unknown"
            retries = self._inner.last_instructor_retries
            failure_reason = getattr(self._inner, "last_failure_reason", None)

            span.set_attribute("llm.provider", provider_id)
            span.set_attribute("llm.latency_ms", round(latency_s * 1000, 1))
            span.set_attribute("llm.instructor_retries", retries)

            if result is None:
                # H1: Publish audit row on failure. Note: generate_structured always uses
                # the default provider order (model selection not supported in structured path).
                # The model field reflects the actual provider used, not a routing override.
                failure_audit = dict(audit_context or {})
                failure_audit.update(extra_audit or {})
                failure_audit["succeeded"] = False
                failure_audit["parse_success"] = False
                if failure_reason:
                    failure_audit["failure_reason"] = failure_reason
                await self._publish_audit(failure_audit, provider_id, latency_s, 0, "", provider_id)
                record_llm_call(provider_id, self._call_type, latency_s, status="failure")
                span.set_attribute("llm.status", "failure")
                if failure_reason:
                    span.set_attribute("llm.failure_reason", failure_reason)
                return None

            response_str = result.model_dump_json()
            token_usage = self._inner.last_token_usage
            actual_total = (
                token_usage.get("total_tokens") if isinstance(token_usage, dict) else None
            )
            tokens = (
                actual_total
                if (actual_total and actual_total > 0)
                else max(1, len(prompt) // 4 + len(response_str) // 4)
            )
            span.set_attribute("llm.tokens", tokens)
            record_llm_call(provider_id, self._call_type, latency_s, tokens=tokens)

            success_audit = dict(audit_context or {})
            success_audit.update(extra_audit or {})
            await self._publish_audit(
                success_audit, provider_id, latency_s, tokens, response_str, provider_id
            )
            return result

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
        if audit_context is None or self._producer is None or self._settings is None:
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

    async def _publish_parse_failure(self, call_id: str) -> None:
        """Publish corrective parse_success=False for a call that failed JSON parsing."""
        if self._producer is None or self._settings is None:
            return
        from src.core.stream_keys import topic_llm_calls

        try:
            await self._producer.publish(
                topic_llm_calls(self._settings.env_name),
                {"call_id": call_id, "parse_success": False, "_parse_update": True},
            )
        except Exception:
            logger.exception("auto_audit.parse_failure_publish_failed", call_id=call_id)
