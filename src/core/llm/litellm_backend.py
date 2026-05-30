"""LiteLLM-based LLM backend for LLMProviderChain.

Replaces per-provider OllamaProvider / OpenRouterProvider with a single class
that delegates to LiteLLM's unified acompletion() interface.

NOT thread-safe at the instance level. One instance must be created per
LLMProviderChain — never shared across concurrent callers. Mutable instance
attributes last_provider_id and last_token_usage are reset and written
per-call with no locking.
"""

from __future__ import annotations

import os
import re

import instructor
import structlog
from litellm import acompletion
from pydantic import BaseModel

from src.core.plugin_circuit_breaker import CircuitBreakerConfig
from src.observability.circuit_breaker import CircuitBreaker

logger = structlog.get_logger(__name__)

# Circuit breaker configs (plan spec). CircuitBreakerConfig carries more fields than
# the observability CircuitBreaker constructor supports (e.g. success_threshold,
# max_half_open_calls, failure_window, performance_threshold_ms are not wired in);
# those advanced fields are preserved here for future use as the circuit breaker
# implementation matures.
_OLLAMA_CB_CONFIG = CircuitBreakerConfig(
    failure_threshold=5,
    recovery_timeout=60,
    success_threshold=1,
    max_half_open_calls=3,
    failure_window=120,
    performance_threshold_ms=120000.0,
)
_REMOTE_CB_CONFIG = CircuitBreakerConfig(
    failure_threshold=3,
    recovery_timeout=300,
    success_threshold=2,
    max_half_open_calls=3,
    failure_window=60,
    performance_threshold_ms=60000.0,
)

# Module-level circuit breakers — shared across all LiteLLMBackend instances so
# an attacker cannot instantiate a fresh breaker with no failure history.
# Use CircuitBreaker (observability) for its allow_request/record_success/record_failure
# manual-tracking API. Constructed from the config constants above so changes to the
# configs take effect without hunting for the hardcoded values below.
_OLLAMA_CB = CircuitBreaker(
    failure_threshold=_OLLAMA_CB_CONFIG.failure_threshold,
    timeout_sec=_OLLAMA_CB_CONFIG.recovery_timeout,
    name="litellm_ollama",
)
_REMOTE_CB = CircuitBreaker(
    failure_threshold=_REMOTE_CB_CONFIG.failure_threshold,
    timeout_sec=_REMOTE_CB_CONFIG.recovery_timeout,
    name="litellm_remote",
)


def _configure_litellm(settings) -> None:
    """Set LiteLLM environment variables and disable telemetry/logging."""
    import litellm

    os.environ.setdefault("OLLAMA_API_BASE", settings.ollama_base_url)
    if settings.openrouter_api_key:
        os.environ.setdefault("OPENROUTER_API_KEY", settings.openrouter_api_key)

    # Prevent LiteLLM from sending telemetry or logging prompts externally
    litellm.telemetry = False
    litellm.success_callback = []
    litellm.failure_callback = []  # prevent failure telemetry from leaking request metadata


class LiteLLMBackend:
    """LiteLLM-based provider backend compatible with LLMProviderChain._inner.

    NOT thread-safe at the instance level. One instance must be created per
    LLMProviderChain — never shared across concurrent callers. Mutable instance
    attributes last_provider_id and last_token_usage are reset and written
    per-call with no locking.

    Interface:
        generate(prompt, system, max_tokens, timeout) -> str | None
        last_provider_id: str | None — LiteLLM model string of successful provider
        last_token_usage: dict | None — {prompt_tokens, completion_tokens, total_tokens}
        providers: list[str] — LiteLLM model strings in priority order
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        self.providers: list[str] = self._build_providers()
        _configure_litellm(settings)
        self.last_provider_id: str | None = None
        self.last_token_usage: dict | None = None
        # Instructor client for structured output. Uses JSON mode for Ollama compatibility.
        # mode=instructor.Mode.JSON is required for non-OpenAI providers (Ollama, OpenRouter).
        import litellm as _litellm

        self._instructor_client = instructor.from_litellm(
            _litellm.acompletion, mode=instructor.Mode.JSON
        )
        self.last_instructor_retries: int = 0
        self.last_failure_reason: str | None = None

    def _build_providers(self) -> list[str]:
        """Build ordered list of LiteLLM model strings from settings."""
        providers: list[str] = []
        if self._settings.ollama_enabled:
            providers.append(f"ollama/{self._settings.ollama_model}")
        if self._settings.openrouter_api_key:
            for model in self._settings.openrouter_models.split(","):
                model = model.strip()
                if model:
                    providers.append(f"openrouter/{model}")
        return providers

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Call each provider in order; return first non-None result or None.

        Resets last_provider_id and last_token_usage at the start of each call.
        Sets them only on a successful response.
        """
        self.last_provider_id = None
        self.last_token_usage = None

        for provider in self.providers:
            cb = self._circuit_breaker_for(provider)
            if not cb.allow_request():
                continue
            try:
                extra = self._build_extra_kwargs(provider)
                response = await acompletion(
                    model=provider,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_tokens,
                    timeout=timeout,
                    **extra,
                )
                content = response.choices[0].message.content or ""
                content = self._strip_thinking_tags(content)
                cb.record_success()
                self.last_provider_id = provider
                self.last_token_usage = self._normalize_usage(response.usage)
                return content
            except Exception as exc:
                cb.record_failure()
                logger.warning(
                    "litellm_backend.provider_failed",
                    provider=provider,
                    error=str(exc)[:120],
                )

        return None

    async def generate_structured(
        self,
        prompt: str,
        system: str,
        response_model: type[BaseModel],
        max_tokens: int = 500,
        timeout: float = 120.0,
    ) -> BaseModel | None:
        """Structured output via instructor with Pydantic validation and multi-provider fallback.

        Uses max_retries=1 per call -- NOT the instructor default of 3.
        With gemma4:e4b at ~50s/call, 3 retries = 150s > the 120s latency_budget_ms
        of all swarm agents.

        Iterates ALL providers with same fallback semantics as generate():
        - Skips providers with open circuit breakers
        - Moves to next provider on exception
        - Returns None only after all providers exhausted

        Uses create_with_completion() to capture raw completion for token usage.
        Sets last_provider_id, last_token_usage, last_instructor_retries as side effects.
        Sets last_failure_reason to one of: 'circuit_open', 'all_providers_exhausted',
        'instructor_validation_failed', 'provider_error'.
        """
        self.last_provider_id = None
        self.last_token_usage = None
        self.last_instructor_retries = 0
        self.last_failure_reason = None

        if not self.providers:
            self.last_failure_reason = "all_providers_exhausted"
            return None

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        for provider in self.providers:
            cb = self._circuit_breaker_for(provider)
            if not cb.allow_request():
                self.last_failure_reason = "circuit_open"
                continue

            extra_kwargs = self._build_extra_kwargs(provider)
            try:
                validated_model, raw_completion = (
                    await self._instructor_client.chat.completions.create_with_completion(
                        model=provider,
                        response_model=response_model,
                        messages=messages,
                        max_tokens=max_tokens,
                        timeout=timeout,
                        max_retries=1,
                        **extra_kwargs,
                    )
                )
                cb.record_success()
                self.last_provider_id = provider
                self.last_token_usage = self._normalize_usage(
                    getattr(raw_completion, "usage", None)
                )
                self.last_instructor_retries = 0
                self.last_failure_reason = None
                return validated_model
            except Exception as exc:
                cb.record_failure()
                # Distinguish validation failure from provider/network failure
                exc_str = str(exc).lower()
                if "validation" in exc_str or "pydantic" in exc_str:
                    self.last_failure_reason = "instructor_validation_failed"
                else:
                    self.last_failure_reason = "provider_error"
                logger.warning(
                    "litellm_backend.generate_structured.provider_failed",
                    provider=provider,
                    error=str(exc)[:120],
                    failure_reason=self.last_failure_reason,
                )

        self.last_failure_reason = "all_providers_exhausted"
        return None

    def _build_extra_kwargs(self, provider: str) -> dict:
        """Return provider-specific extra kwargs for acompletion."""
        if provider.startswith("ollama/"):
            return {
                "think": False,
                "options": {"num_ctx": self._settings.ollama_num_ctx},
            }
        return {}

    def _circuit_breaker_for(self, provider: str) -> CircuitBreaker:
        """Return the appropriate circuit breaker for a given provider string."""
        return _OLLAMA_CB if provider.startswith("ollama/") else _REMOTE_CB

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """Remove <think>...</think> blocks from LLM output."""
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        return cleaned.strip()

    @staticmethod
    def _normalize_usage(usage) -> dict | None:
        """Normalize LiteLLM usage to {prompt_tokens, completion_tokens, total_tokens}.

        Handles both Pydantic model objects (attribute access) and plain dicts.
        Returns None if usage is None or extraction fails.
        """
        if usage is None:
            return None
        try:
            if hasattr(usage, "total_tokens"):
                return {
                    "prompt_tokens": int(usage.prompt_tokens),
                    "completion_tokens": int(usage.completion_tokens),
                    "total_tokens": int(usage.total_tokens),
                }
            if isinstance(usage, dict):
                return {
                    "prompt_tokens": int(usage["prompt_tokens"]),
                    "completion_tokens": int(usage["completion_tokens"]),
                    "total_tokens": int(usage["total_tokens"]),
                }
        except Exception:
            return None
        return None
