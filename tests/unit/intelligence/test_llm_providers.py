"""Unit tests for LLM provider circuit breaker integration.

Tests verify:
- All four providers (ZAI, OpenRouter, Anthropic, Ollama) use _call_llm_with_circuit_breaker
- Circuit breaker state (success_count, failure_count) tracks LLM provider health
- retry_with_backoff wraps each provider's sync call for retry logic
- Failures return None and increment failure_count
- Successes return content and increment success_count
"""

from __future__ import annotations

import contextlib
import json as _json
from unittest.mock import MagicMock, patch

import pytest

from src.core.llm.providers import (
    LLMChain,
    OllamaProvider,
    OpenRouterProvider,
    _call_llm_with_circuit_breaker,
    _llm_circuit_breaker,
    _ollama_circuit_breaker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_openrouter_response(content: str) -> bytes:
    import json

    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def _make_ollama_stream_lines(content: str) -> list[str]:
    """Build Ollama streaming NDJSON lines for a given content string."""
    lines = [_json.dumps({"message": {"content": content}, "done": False})]
    lines.append(_json.dumps({"message": {"content": ""}, "done": True}))
    return lines


def _make_mock_stream(lines: list[str]):
    """Return an async context manager that yields a mock httpx streaming response."""

    @contextlib.asynccontextmanager
    async def _stream(*args, **kwargs):
        class _Resp:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                for line in lines:
                    yield line

        yield _Resp()

    return _stream


# ---------------------------------------------------------------------------
# _call_llm_with_circuit_breaker tests
# ---------------------------------------------------------------------------


class TestCallLLMWithCircuitBreaker:
    """Test the core circuit breaker helper."""

    def test_module_circuit_breaker_instance_exists(self):
        """_llm_circuit_breaker is a PluginCircuitBreaker with correct config."""
        from src.core.plugin_circuit_breaker import PluginCircuitBreaker

        assert isinstance(_llm_circuit_breaker, PluginCircuitBreaker)
        assert _llm_circuit_breaker.config.failure_threshold == 3
        assert _llm_circuit_breaker.config.recovery_timeout == 300
        assert _llm_circuit_breaker.config.success_threshold == 2
        assert _llm_circuit_breaker.config.performance_threshold_ms == 60000.0

    @pytest.mark.asyncio
    async def test_success_increments_success_count(self):
        """Successful call increments success_count and total_calls."""
        _llm_circuit_breaker.plugin_states.clear()

        def _fn():
            return "hello"

        result = await _call_llm_with_circuit_breaker("test:success", _fn)
        assert result == "hello"

        state = _llm_circuit_breaker.plugin_states["test:success"]
        assert state.success_count == 1
        assert state.total_calls == 1
        assert state.last_success_time is not None

    @pytest.mark.asyncio
    async def test_failure_increments_failure_count(self):
        """Failed call increments failure_count and returns None."""
        _llm_circuit_breaker.plugin_states.clear()

        def _fn():
            raise ConnectionError("connection refused")

        result = await _call_llm_with_circuit_breaker("test:failure", _fn)
        assert result is None

        state = _llm_circuit_breaker.plugin_states["test:failure"]
        assert state.failure_count == 1
        assert state.total_calls == 1
        assert state.last_failure_time is not None

    @pytest.mark.asyncio
    async def test_none_return_does_not_count_as_failure(self):
        """Callable returning None is a success (no exception) — increments success_count."""
        _llm_circuit_breaker.plugin_states.clear()

        def _fn():
            return None

        result = await _call_llm_with_circuit_breaker("test:none-return", _fn)
        assert result is None

        state = _llm_circuit_breaker.plugin_states["test:none-return"]
        assert state.success_count == 1
        assert state.failure_count == 0

    @pytest.mark.asyncio
    async def test_async_callable_is_awaited(self):
        """_call_llm_with_circuit_breaker accepts and awaits async callables."""
        _llm_circuit_breaker.plugin_states.clear()

        async def _async_fn():
            return "async result"

        result = await _call_llm_with_circuit_breaker("test:async", _async_fn)
        assert result == "async result"

    @pytest.mark.asyncio
    async def test_custom_retry_on_excludes_timeout(self):
        """TimeoutError is NOT retried when excluded from retry_on."""
        _llm_circuit_breaker.plugin_states.clear()
        call_count = [0]

        def _fn():
            call_count[0] += 1
            raise TimeoutError("slow model")

        result = await _call_llm_with_circuit_breaker(
            "test:no-retry-timeout",
            _fn,
            retry_on=(ConnectionError, BrokenPipeError),
        )
        assert result is None
        assert call_count[0] == 1  # called exactly once — no retries


# ---------------------------------------------------------------------------
# OpenRouterProvider tests
# ---------------------------------------------------------------------------


class TestOpenRouterProvider:
    def _make_provider(self) -> OpenRouterProvider:
        return OpenRouterProvider(
            model="test-model",
            api_key="test-key",
            base_url="http://fake-openrouter.local",
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() returns parsed content on HTTP success."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_openrouter_response("OpenRouter reply")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "OpenRouter reply"

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None on network exception."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_tracks_failure_in_circuit_breaker(self):
        """Failure increments failure_count in the shared circuit breaker."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _llm_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1

    @pytest.mark.asyncio
    async def test_generate_tracks_success_in_circuit_breaker(self):
        """Success increments success_count in the shared circuit breaker."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_openrouter_response("ok")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _llm_circuit_breaker.plugin_states[provider.provider_id]
        assert state.success_count >= 1


# ---------------------------------------------------------------------------
# OllamaProvider tests
# ---------------------------------------------------------------------------


class TestOllamaProvider:
    def _make_provider(self) -> OllamaProvider:
        return OllamaProvider(
            model="qwen3.5:9b",
            base_url="http://fake-ollama.local",
            num_ctx=4096,
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() assembles streamed chunks into a single response."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch.object(
            provider._client, "stream", _make_mock_stream(_make_ollama_stream_lines("Ollama reply"))
        ):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "Ollama reply"
        await provider.close()

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None when httpx raises ConnectError."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        import httpx

        @contextlib.asynccontextmanager
        async def _failing_stream(*args, **kwargs):
            raise httpx.ConnectError("refused")
            yield  # make it a generator

        with patch.object(provider._client, "stream", _failing_stream):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None
        await provider.close()

    @pytest.mark.asyncio
    async def test_failure_tracked_in_circuit_breaker(self):
        """ConnectError increments failure_count in the ollama-specific circuit breaker."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        import httpx

        @contextlib.asynccontextmanager
        async def _failing_stream(*args, **kwargs):
            raise httpx.ConnectError("refused")
            yield

        with patch.object(provider._client, "stream", _failing_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _ollama_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1
        await provider.close()

    @pytest.mark.asyncio
    async def test_num_ctx_passed_in_options(self):
        """generate() passes num_ctx from provider config in Ollama options."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = OllamaProvider(
            model="qwen3.5:9b", base_url="http://fake-ollama.local", num_ctx=8192
        )
        captured = {}

        @contextlib.asynccontextmanager
        async def _capture_stream(method, url, *, json, timeout, **kwargs):
            captured.update(json)

            class _Resp:
                def raise_for_status(self):
                    pass

                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "ok"}, "done": True})

            yield _Resp()

        with patch.object(provider._client, "stream", _capture_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        assert captured["options"]["num_ctx"] == 8192
        assert captured["options"]["num_predict"] == 100
        await provider.close()

    @pytest.mark.asyncio
    async def test_think_false_in_payload(self):
        """generate() sets think=False to suppress qwen chain-of-thought at API level."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()
        captured = {}

        @contextlib.asynccontextmanager
        async def _capture_stream(method, url, *, json, timeout, **kwargs):
            captured.update(json)

            class _Resp:
                def raise_for_status(self):
                    pass

                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "ok"}, "done": True})

            yield _Resp()

        with patch.object(provider._client, "stream", _capture_stream):
            await provider.generate("prompt", "system", 100, 30.0)

        assert captured["think"] is False
        await provider.close()

    @pytest.mark.asyncio
    async def test_timeout_not_retried(self):
        """TimeoutError from Ollama returns None without retrying (no added load)."""
        _ollama_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()
        call_count = [0]

        @contextlib.asynccontextmanager
        async def _timeout_stream(*args, **kwargs):
            call_count[0] += 1
            raise TimeoutError("model slow")
            yield

        with patch.object(provider._client, "stream", _timeout_stream):
            result = await provider.generate("prompt", "system", 100, 1.0)

        assert result is None
        assert call_count[0] == 1  # no retries
        await provider.close()


# ---------------------------------------------------------------------------
# LLMChain tests
# ---------------------------------------------------------------------------


class TestLLMChain:
    @pytest.mark.asyncio
    async def test_chain_returns_first_success(self):
        """LLMChain returns result from first succeeding provider."""
        _llm_circuit_breaker.plugin_states.clear()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_openrouter_response("Chain reply")

        provider1 = OpenRouterProvider("m1", "k1", base_url="http://fake.local")
        provider2 = OllamaProvider("m2", base_url="http://fake-ollama.local")
        chain = LLMChain([provider1, provider2])

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await chain.generate("prompt", "system", 100, 30.0)

        assert result == "Chain reply"
        assert chain.last_provider_id == provider1.provider_id

    @pytest.mark.asyncio
    async def test_chain_falls_through_to_second_on_failure(self):
        """LLMChain falls through to Ollama when OpenRouter fails."""
        _llm_circuit_breaker.plugin_states.clear()
        _ollama_circuit_breaker.plugin_states.clear()

        or_provider = OpenRouterProvider("m1", "k1", base_url="http://fake.local")
        ollama_provider = OllamaProvider(
            "qwen3.5:9b", base_url="http://fake-ollama.local", num_ctx=4096
        )
        chain = LLMChain([or_provider, ollama_provider])

        @contextlib.asynccontextmanager
        async def _ollama_mock_stream(*args, **kwargs):
            class _Resp:
                def raise_for_status(self):
                    pass

                async def aiter_lines(self):
                    yield _json.dumps({"message": {"content": "Fallback reply"}, "done": True})

            yield _Resp()

        with (
            patch("urllib.request.urlopen", side_effect=ConnectionError("openrouter down")),
            patch.object(ollama_provider._client, "stream", _ollama_mock_stream),
        ):
            result = await chain.generate("prompt", "system", 100, 30.0)

        assert result == "Fallback reply"
        assert chain.last_provider_id == ollama_provider.provider_id
        await ollama_provider.close()


# ---------------------------------------------------------------------------
# LLMProviderChain._build_providers tests
# ---------------------------------------------------------------------------


class TestLLMProviderChainBuildProviders:
    """Tests for LLMProviderChain._build_providers fallback wiring."""

    def _make_settings(self, *, api_key: str = "", models: str = "") -> object:
        from unittest.mock import MagicMock

        s = MagicMock()
        s.ollama_model = "qwen3.5:4b"
        s.ollama_base_url = "http://localhost:11434"
        s.ollama_num_ctx = 16384
        s.openrouter_api_key = api_key
        s.openrouter_models = models
        return s

    def test_ollama_only_when_no_api_key(self):
        """No OpenRouter providers when openrouter_api_key is empty."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider

        chain = LLMProviderChain(call_type="test", settings=self._make_settings())
        providers = chain._inner.providers
        assert len(providers) == 1
        assert isinstance(providers[0], OllamaProvider)

    def test_openrouter_appended_when_api_key_set(self):
        """OpenRouter providers appended after Ollama when api_key is present."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider, OpenRouterProvider

        settings = self._make_settings(
            api_key="sk-test",
            models="google/gemma-4-31b-it:free,nvidia/nemotron:free",
        )
        chain = LLMProviderChain(call_type="test", settings=settings)
        providers = chain._inner.providers

        assert len(providers) == 3
        assert isinstance(providers[0], OllamaProvider)
        assert isinstance(providers[1], OpenRouterProvider)
        assert providers[1].model == "google/gemma-4-31b-it:free"
        assert isinstance(providers[2], OpenRouterProvider)
        assert providers[2].model == "nvidia/nemotron:free"

    def test_ollama_num_ctx_passed_through(self):
        """OllamaProvider receives num_ctx from settings."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OllamaProvider

        settings = self._make_settings()
        settings.ollama_num_ctx = 8192
        chain = LLMProviderChain(call_type="test", settings=settings)
        ollama = chain._inner.providers[0]
        assert isinstance(ollama, OllamaProvider)
        assert ollama._num_ctx == 8192

    def test_whitespace_stripped_from_model_names(self):
        """Model names with surrounding whitespace are stripped."""
        from src.core.llm.chain import LLMProviderChain
        from src.core.llm.providers import OpenRouterProvider

        settings = self._make_settings(
            api_key="sk-test",
            models=" google/gemma-4-31b-it:free , nvidia/nemotron:free ",
        )
        chain = LLMProviderChain(call_type="test", settings=settings)
        or_providers = [p for p in chain._inner.providers if isinstance(p, OpenRouterProvider)]
        assert or_providers[0].model == "google/gemma-4-31b-it:free"
        assert or_providers[1].model == "nvidia/nemotron:free"
