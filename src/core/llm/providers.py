"""LLM provider abstraction — OpenRouter (primary), Ollama (local fallback).

Usage:
    chain = LLMChain([
        OpenRouterProvider("meta-llama/llama-3.3-70b-instruct:free", api_key="sk-..."),
        OllamaProvider("gemma4:e4b"),
    ])
    text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
    # chain.last_provider_id tells you which provider succeeded
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from asyncio import to_thread
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, runtime_checkable

import structlog

# Circuit breaker and retry
from src.core.plugin_circuit_breaker import CircuitBreakerConfig, CircuitState, PluginCircuitBreaker
from src.core.retry_utils import retry_with_backoff

# Circuit breaker metrics
from src.observability.metrics import (
    CIRCUIT_BREAKER_FAILURES_TOTAL,
    CIRCUIT_BREAKER_OPEN_SECONDS,
    CIRCUIT_BREAKER_SUCCESSES_TOTAL,
    CIRCUIT_BREAKER_TRANSITIONS_TOTAL,
)

logger = structlog.get_logger(__name__)


class ProviderRateLimitError(Exception):
    """Raised when a provider returns HTTP 429 — do not retry, trip circuit immediately."""


# Circuit breaker for LLM provider calls — shared across all providers.
# Uses a 5-minute recovery timeout and 3 consecutive failures threshold.
_llm_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=300,  # 5 minutes
        success_threshold=2,
        max_half_open_calls=3,
        failure_window=60,
        performance_threshold_ms=60000.0,  # 60s default timeout
    )
)

# Track when each LLM provider's circuit breaker entered OPEN — keyed by provider_id.
_llm_open_since: dict[str, float] = {}


async def _call_llm_with_circuit_breaker(
    provider_id: str,
    call_fn: Callable,
) -> str | None:
    """Call LLM provider with circuit breaker tracking and retry backoff.

    Args:
        provider_id: Unique provider identifier (e.g., "zai:glm-5")
        call_fn: Synchronous callable that performs the LLM HTTP call.
            Called once per attempt by retry_with_backoff via to_thread.

    Returns:
        LLM response string or None on failure.

    Note:
        retry_with_backoff wraps call_fn with exponential backoff.
        Each retry attempt invokes call_fn fresh (not a pre-built coroutine).
        Circuit breaker state tracks health and opens after failure_threshold failures.
    """
    plugin_state = _llm_circuit_breaker.plugin_states[provider_id]
    previous_state = plugin_state.state

    # --- Pre-call: enforce OPEN / HALF_OPEN gate ---
    if plugin_state.state == CircuitState.OPEN:
        # Default to current time if key missing — treats unknown state as "just opened"
        elapsed = time.monotonic() - _llm_open_since.get(provider_id, time.monotonic())
        if elapsed < _llm_circuit_breaker.config.recovery_timeout:
            logger.warning(
                "llm_circuit_open.skipping",
                provider=provider_id,
                elapsed_s=round(elapsed, 1),
                recovery_timeout=_llm_circuit_breaker.config.recovery_timeout,
            )
            return None
        # Recovery timeout elapsed — allow one probe (HALF_OPEN)
        plugin_state.state = CircuitState.HALF_OPEN
        logger.info("llm_circuit_half_open", provider=provider_id)

    async def _run() -> str | None:
        return await to_thread(call_fn)

    try:
        result = await retry_with_backoff(
            _run,
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            retry_on=(ConnectionError, TimeoutError, BrokenPipeError),
        )
        # Record success metrics
        CIRCUIT_BREAKER_SUCCESSES_TOTAL.labels(plugin_name=provider_id).inc()

        # Record success in circuit breaker
        plugin_state.success_count += 1
        plugin_state.last_success_time = datetime.now()
        plugin_state.total_calls += 1

        # Close circuit after successful HALF_OPEN probe
        if plugin_state.state == CircuitState.HALF_OPEN:
            plugin_state.state = CircuitState.CLOSED
            plugin_state.failure_count = 0
            logger.info("llm_circuit_closed_after_recovery", provider=provider_id)

        # Record state transition if recovered from non-closed state
        if plugin_state.state != previous_state and previous_state != CircuitState.CLOSED:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.labels(
                plugin_name=provider_id,
                from_state=previous_state.name.lower(),
                to_state="closed",
            ).inc()
            # Observe how long this provider's circuit was OPEN before recovery
            if provider_id in _llm_open_since:
                CIRCUIT_BREAKER_OPEN_SECONDS.labels(plugin_name=provider_id).observe(
                    time.monotonic() - _llm_open_since.pop(provider_id)
                )

        return result

    except Exception as exc:
        # Record failure metrics
        CIRCUIT_BREAKER_FAILURES_TOTAL.labels(
            plugin_name=provider_id,
            error_type=type(exc).__name__,
        ).inc()

        # Record failure in circuit breaker
        plugin_state.failure_count += 1
        plugin_state.last_failure_time = datetime.now()
        plugin_state.total_calls += 1

        # Trip circuit to OPEN after failure_threshold consecutive failures
        if (
            plugin_state.state != CircuitState.OPEN
            and plugin_state.failure_count >= _llm_circuit_breaker.config.failure_threshold
        ):
            plugin_state.state = CircuitState.OPEN
            _llm_open_since[provider_id] = time.monotonic()
            logger.warning(
                "llm_circuit_opened",
                provider=provider_id,
                failure_count=plugin_state.failure_count,
            )

        # Record state transition if tripped to OPEN
        if plugin_state.state == CircuitState.OPEN and previous_state != CircuitState.OPEN:
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.labels(
                plugin_name=provider_id,
                from_state=previous_state.name.lower(),
                to_state="open",
            ).inc()
            # Start timing how long this provider's circuit stays OPEN
            if provider_id not in _llm_open_since:
                _llm_open_since[provider_id] = time.monotonic()

        logger.warning(
            "LLM provider call failed",
            provider=provider_id,
            error=str(exc),
        )
        return None


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output.

    Some reasoning models (DeepSeek, GLM, Qwen when /no_think is ignored) emit
    their chain-of-thought wrapped in <think> tags inside the content field.
    Strip those blocks and return only the final answer.
    """
    import re

    # Remove <think>...</think> blocks (possibly multiline, possibly multiple)
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return cleaned.strip()


def _extract_message_content(choices: list[dict]) -> str | None:
    """Extract content from LLM response, supporting both content and reasoning fields.

    Args:
        choices: List of choice objects from LLM API response

    Returns:
        String content if found, None if extraction fails or no choices available
    """
    if not choices:
        return None
    msg = choices[0].get("message")
    if not msg or not isinstance(msg, dict):
        return None
    # Prefer content over reasoning — reasoning is raw thinking, content is the answer
    content = msg.get("content") or ""
    cleaned = _strip_thinking_tags(content)
    return cleaned or None


def _default_llm_timeout() -> float:
    """Get default LLM timeout from Settings."""
    from src.config.settings import Settings

    return Settings().llm_timeout_sec


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal protocol every LLM backend must satisfy."""

    provider_id: str

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        """Return generated text, or None on failure."""
        ...


class OpenRouterProvider:
    """Calls OpenRouter /api/v1/chat/completions (OpenAI-compatible)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or _default_llm_timeout()
        self.provider_id = f"openrouter:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    result = json.loads(resp.read())
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise ProviderRateLimitError("HTTP 429: Too Many Requests") from exc
                raise
            choices = result.get("choices") or []
            return _extract_message_content(choices)

        return await _call_llm_with_circuit_breaker(self.provider_id, _call)


class OllamaProvider:
    """Calls local Ollama /api/chat."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or _default_llm_timeout()
        self.provider_id = f"ollama:{model}"

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "think": False,
                "options": {"num_predict": max_tokens},
            }
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
            raw = result.get("message", {}).get("content", "").strip()
            return _strip_thinking_tags(raw) or None

        return await _call_llm_with_circuit_breaker(self.provider_id, _call)


class LLMChain:
    """Try each provider in order; return first non-None result."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self.last_provider_id: str | None = None

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        for provider in self.providers:
            result = await provider.generate(prompt, system, max_tokens, timeout)
            if result is not None:
                self.last_provider_id = provider.provider_id
                return result
        self.last_provider_id = None
        return None
