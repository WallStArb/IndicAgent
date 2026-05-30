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

import structlog
from litellm import acompletion

from src.core.plugin_circuit_breaker import CircuitBreakerConfig
from src.observability.circuit_breaker import CircuitBreaker

logger = structlog.get_logger(__name__)

# Module-level circuit breakers — shared across all LiteLLMBackend instances so
# an attacker cannot instantiate a fresh breaker with no failure history.
# Use CircuitBreaker (observability) for its allow_request/record_success/record_failure
# manual-tracking API. PluginCircuitBreaker is preserved for the config constants below.
_OLLAMA_CB = CircuitBreaker(
    failure_threshold=5,
    timeout_sec=60,
    name="litellm_ollama",
)
_REMOTE_CB = CircuitBreaker(
    failure_threshold=3,
    timeout_sec=300,
    name="litellm_remote",
)

# Circuit breaker configs preserved for reference (match plan spec)
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


def _configure_litellm(settings) -> None:
    """Set LiteLLM environment variables and disable telemetry/logging."""
    import litellm

    os.environ.setdefault("OLLAMA_API_BASE", settings.ollama_base_url)
    if settings.openrouter_api_key:
        os.environ.setdefault("OPENROUTER_API_KEY", settings.openrouter_api_key)

    # Prevent LiteLLM from sending telemetry or logging prompts externally
    litellm.telemetry = False
    litellm.success_callback = []


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
