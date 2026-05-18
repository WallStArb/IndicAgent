"""LLM provider abstraction — OpenRouter (primary), Ollama local (fallback).

Usage:
    chain = LLMChain([
        OpenRouterProvider("google/gemma-4-31b-it:free", api_key="sk-..."),
        OllamaProvider("nemotron-3-nano:4b"),
    ])
    text = await chain.generate(prompt, system, max_tokens=500, timeout=30.0)
    # chain.last_provider_id tells you which provider succeeded
"""

from __future__ import annotations

import asyncio as _asyncio
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


# Circuit breaker for remote LLM providers (OpenRouter, Ollama Cloud).
# 3 failures → open for 5 minutes.
_llm_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=300,  # 5 minutes
        success_threshold=2,
        max_half_open_calls=3,
        failure_window=60,
        performance_threshold_ms=60000.0,
    )
)

# Lenient circuit breaker for local Ollama — no rate limits, just warmup latency.
# Higher threshold + short recovery so a slow model-load on boot doesn't kill the fallback.
_ollama_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=5,
        recovery_timeout=60,  # 1 minute — recover fast after model loads
        success_threshold=1,
        max_half_open_calls=3,
        failure_window=120,
        performance_threshold_ms=120000.0,  # 2 minutes — allow slow first-load
    )
)

# Track when each LLM provider's circuit breaker entered OPEN — keyed by provider_id.
_llm_open_since: dict[str, float] = {}


async def _call_llm_with_circuit_breaker(
    provider_id: str,
    call_fn: Callable,
    circuit_breaker: PluginCircuitBreaker | None = None,
    retry_on: tuple[type[Exception], ...] = (ConnectionError, TimeoutError, BrokenPipeError),
) -> str | None:
    """Call LLM provider with circuit breaker tracking and retry backoff.

    Args:
        provider_id: Unique provider identifier (e.g., "zai:glm-5")
        call_fn: Sync or async callable that performs the LLM HTTP call.
        circuit_breaker: Circuit breaker to use. Defaults to _llm_circuit_breaker
            (remote providers). Pass _ollama_circuit_breaker for local Ollama.
        retry_on: Exception types that trigger a retry. Pass a narrower tuple to
            exclude e.g. TimeoutError for local Ollama (retrying a hung model adds
            load, not recovery).

    Returns:
        LLM response string or None on failure.
    """
    cb = circuit_breaker or _llm_circuit_breaker
    plugin_state = cb.plugin_states[provider_id]
    previous_state = plugin_state.state

    # --- Pre-call: enforce OPEN / HALF_OPEN gate ---
    if plugin_state.state == CircuitState.OPEN:
        # Default to current time if key missing — treats unknown state as "just opened"
        elapsed = time.monotonic() - _llm_open_since.get(provider_id, time.monotonic())
        if elapsed < cb.config.recovery_timeout:
            logger.warning(
                "llm_circuit_open.skipping",
                provider=provider_id,
                elapsed_s=round(elapsed, 1),
                recovery_timeout=cb.config.recovery_timeout,
            )
            return None
        # Recovery timeout elapsed — allow one probe (HALF_OPEN)
        plugin_state.state = CircuitState.HALF_OPEN
        logger.info("llm_circuit_half_open", provider=provider_id)

    async def _run() -> str | None:
        if _asyncio.iscoroutinefunction(call_fn):
            return await call_fn()
        return await to_thread(call_fn)

    try:
        result = await retry_with_backoff(
            _run,
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            retry_on=retry_on,
        )
        # Record success metrics
        CIRCUIT_BREAKER_SUCCESSES_TOTAL.add(1, {"plugin_name": provider_id})

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
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.add(
                1,
                {
                    "plugin_name": provider_id,
                    "from_state": previous_state.name.lower(),
                    "to_state": "closed",
                },
            )
            # Observe how long this provider's circuit was OPEN before recovery
            if provider_id in _llm_open_since:
                CIRCUIT_BREAKER_OPEN_SECONDS.record(
                    time.monotonic() - _llm_open_since.pop(provider_id),
                    {"plugin_name": provider_id},
                )

        return result

    except Exception as exc:
        # Record failure metrics
        CIRCUIT_BREAKER_FAILURES_TOTAL.add(
            1, {"plugin_name": provider_id, "error_type": type(exc).__name__}
        )

        # Record failure in circuit breaker
        plugin_state.failure_count += 1
        plugin_state.last_failure_time = datetime.now()
        plugin_state.total_calls += 1

        # Trip circuit to OPEN after failure_threshold consecutive failures
        if (
            plugin_state.state != CircuitState.OPEN
            and plugin_state.failure_count >= cb.config.failure_threshold
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
            CIRCUIT_BREAKER_TRANSITIONS_TOTAL.add(
                1,
                {
                    "plugin_name": provider_id,
                    "from_state": previous_state.name.lower(),
                    "to_state": "open",
                },
            )
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
    """Remove <think>...</think> blocks from LLM output (Qwen when /no_think is ignored)."""
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


class _OpenAICompatProvider:
    """Base for providers using the /chat/completions endpoint (OpenRouter, DeepSeek)."""

    _provider_prefix: str = ""
    _default_base_url: str = ""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = (base_url or self._default_base_url).rstrip("/")
        self.timeout = timeout or _default_llm_timeout()
        self.provider_id = f"{self._provider_prefix}:{model}"
        self._circuit_breaker = _llm_circuit_breaker
        self._last_usage: dict | None = None

    def _extra_payload_fields(self) -> dict:
        return {}

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        _usage: list[dict] = []

        def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "stream": False,
                **self._extra_payload_fields(),
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
            usage = result.get("usage", {})
            if usage:
                _usage.append(usage)
            return _extract_message_content(choices)

        result = await _call_llm_with_circuit_breaker(
            self.provider_id, _call, circuit_breaker=self._circuit_breaker
        )
        if _usage:
            self._last_usage = _usage[0]
        return result


class OpenRouterProvider(_OpenAICompatProvider):
    """Calls OpenRouter /api/v1/chat/completions (OpenAI-compatible).

    Suppresses chain-of-thought on reasoning-capable free models so they
    return clean JSON instead of verbose CoT.
    """

    _provider_prefix = "openrouter"
    _default_base_url = "https://openrouter.ai/api/v1"

    def _extra_payload_fields(self) -> dict:
        return {"include_reasoning": False, "reasoning": {"effort": "none"}}


class OllamaProvider:
    """Calls local Ollama /api/chat using async httpx streaming.

    Streaming (stream=True) ensures asyncio cancellation propagates to the
    HTTP socket — when the caller's wait_for fires, the connection closes and
    Ollama stops generating. Non-streaming (stream=False) with urllib left
    the runner alive for the full generation duration.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        timeout: float | None = None,
        num_ctx: int = 4096,
    ) -> None:
        import httpx

        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout or _default_llm_timeout()
        self._num_ctx = num_ctx
        self.provider_id = f"ollama:{model}"
        self._circuit_breaker = _ollama_circuit_breaker
        self._client = httpx.AsyncClient()

    async def generate(
        self,
        prompt: str,
        system: str,
        max_tokens: int,
        timeout: float,
    ) -> str | None:
        import httpx

        async def _call() -> str | None:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "stream": True,
                "think": False,
                "options": {"num_predict": max_tokens, "num_ctx": self._num_ctx},
            }
            try:
                chunks: list[str] = []
                async with self._client.stream(
                    "POST",
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        content = data.get("message", {}).get("content", "")
                        if content:
                            chunks.append(content)
                        if data.get("done"):
                            break
                return _strip_thinking_tags("".join(chunks)) or None
            except httpx.TimeoutException as exc:
                raise TimeoutError(f"Ollama request timed out: {exc}") from exc
            except httpx.ConnectError as exc:
                raise ConnectionError(f"Ollama connection failed: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ConnectionError(f"Ollama HTTP {exc.response.status_code}") from exc
            except httpx.RequestError as exc:
                raise ConnectionError(f"Ollama request error: {exc}") from exc

        return await _call_llm_with_circuit_breaker(
            self.provider_id,
            _call,
            circuit_breaker=self._circuit_breaker,
            retry_on=(ConnectionError, BrokenPipeError),
        )

    async def close(self) -> None:
        """Close the shared httpx client. Call on service shutdown."""
        await self._client.aclose()


class LLMChain:
    """Try each provider in order; return first non-None result."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self.last_provider_id: str | None = None
        self.last_token_usage: dict | None = None

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
                self.last_token_usage = getattr(provider, "_last_usage", None)
                return result
        self.last_provider_id = None
        self.last_token_usage = None
        return None
