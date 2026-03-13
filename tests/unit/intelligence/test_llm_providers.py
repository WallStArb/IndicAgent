"""Unit tests for LLM provider circuit breaker integration.

Tests verify:
- All four providers (ZAI, OpenRouter, Anthropic, Ollama) use _call_llm_with_circuit_breaker
- Circuit breaker state (success_count, failure_count) tracks LLM provider health
- retry_with_backoff wraps each provider's sync call for retry logic
- Failures return None and increment failure_count
- Successes return content and increment success_count
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.intelligence.llm_providers import (
    AnthropicProvider,
    LLMChain,
    OllamaProvider,
    OpenRouterProvider,
    ZAIProvider,
    _call_llm_with_circuit_breaker,
    _llm_circuit_breaker,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openrouter_response(content: str) -> bytes:
    import json
    return json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode()


def _make_anthropic_response(text: str) -> bytes:
    import json
    return json.dumps({
        "content": [{"text": text}]
    }).encode()


def _make_zai_response(content: str) -> bytes:
    import json
    return json.dumps({
        "choices": [{"message": {"content": content}}]
    }).encode()


def _make_ollama_response(content: str) -> bytes:
    import json
    return json.dumps({
        "message": {"content": content}
    }).encode()


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
# AnthropicProvider tests
# ---------------------------------------------------------------------------

class TestAnthropicProvider:
    def _make_provider(self) -> AnthropicProvider:
        return AnthropicProvider(
            model="claude-test",
            api_key="sk-test",
            base_url="http://fake-anthropic.local",
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() returns text from content block on success."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_anthropic_response("Anthropic reply")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "Anthropic reply"

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None on network exception."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_failure_tracked_in_circuit_breaker(self):
        """Failure increments failure_count for this provider_id."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _llm_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1


# ---------------------------------------------------------------------------
# ZAIProvider tests
# ---------------------------------------------------------------------------

class TestZAIProvider:
    def _make_provider(self) -> ZAIProvider:
        return ZAIProvider(
            model="glm-5",
            api_key="zai-key",
            base_url="http://fake-zai.local",
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() returns content from choices on success."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_zai_response("ZAI reply")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "ZAI reply"

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None on network exception."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_failure_tracked_in_circuit_breaker(self):
        """Failure increments failure_count for this provider_id."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _llm_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1


# ---------------------------------------------------------------------------
# OllamaProvider tests
# ---------------------------------------------------------------------------

class TestOllamaProvider:
    def _make_provider(self) -> OllamaProvider:
        return OllamaProvider(
            model="qwen3.5:9b",
            base_url="http://fake-ollama.local",
        )

    @pytest.mark.asyncio
    async def test_generate_success(self):
        """generate() returns message content on success."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _make_ollama_response("Ollama reply")

        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result == "Ollama reply"

    @pytest.mark.asyncio
    async def test_generate_failure_returns_none(self):
        """generate() returns None on network exception."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            result = await provider.generate("prompt", "system", 100, 30.0)

        assert result is None

    @pytest.mark.asyncio
    async def test_failure_tracked_in_circuit_breaker(self):
        """Failure increments failure_count for this provider_id."""
        _llm_circuit_breaker.plugin_states.clear()
        provider = self._make_provider()

        with patch("urllib.request.urlopen", side_effect=ConnectionError("refused")):
            await provider.generate("prompt", "system", 100, 30.0)

        state = _llm_circuit_breaker.plugin_states[provider.provider_id]
        assert state.failure_count >= 1


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
        """LLMChain tries next provider when first returns None."""
        _llm_circuit_breaker.plugin_states.clear()

        provider1 = OpenRouterProvider("m1", "k1", base_url="http://fake.local")
        provider2 = OllamaProvider("qwen3.5:9b", base_url="http://fake-ollama.local")
        chain = LLMChain([provider1, provider2])

        ollama_resp = MagicMock()
        ollama_resp.__enter__ = lambda s: s
        ollama_resp.__exit__ = MagicMock(return_value=False)
        ollama_resp.read.return_value = _make_ollama_response("Fallback reply")

        call_count = [0]

        def _urlopen_side_effect(req, timeout=None):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("first fails")
            return ollama_resp

        with patch("urllib.request.urlopen", side_effect=_urlopen_side_effect):
            # First provider will fail 3 times (retries), then second succeeds
            result = await chain.generate("prompt", "system", 100, 30.0)

        assert result == "Fallback reply"
        assert chain.last_provider_id == provider2.provider_id
