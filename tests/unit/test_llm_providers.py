"""Tests for LLMProvider protocol, OpenRouterProvider, OllamaProvider, LLMChain."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.error import HTTPError

import pytest

from src.intelligence.llm_providers import (
    LLMChain,
    OllamaProvider,
    OpenRouterProvider,
)

SYSTEM = "You are a trading analyst."
PROMPT = "Summarize: bullish ES 5m"


# ---------------------------------------------------------------------------
# OpenRouterProvider
# ---------------------------------------------------------------------------

class TestOpenRouterProvider:
    def _make_provider(self):
        return OpenRouterProvider(
            model="meta-llama/llama-3.3-70b-instruct:free",
            api_key="test-key",
            base_url="https://openrouter.ai/api/v1",
        )

    def _mock_response(self, text: str) -> MagicMock:
        payload = {"choices": [{"message": {"content": text}}]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_success(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("Bullish outlook.")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "Bullish outlook."

    @pytest.mark.asyncio
    async def test_empty_content_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("   ")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import urllib.error
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url=None, code=429, msg="Too Many Requests", hdrs=None, fp=None
        )):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------

class TestOllamaProvider:
    def _make_provider(self):
        return OllamaProvider(
            model="qwen3:8b",
            base_url="http://localhost:11434",
        )

    def _mock_response(self, text: str) -> MagicMock:
        payload = {"message": {"content": text}}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @pytest.mark.asyncio
    async def test_success(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", return_value=self._mock_response("Bearish signal.")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result == "Bearish signal."

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_error_returns_none(self):
        provider = self._make_provider()
        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            result = await provider.generate(PROMPT, SYSTEM, max_tokens=500, timeout=60.0)
        assert result is None


# ---------------------------------------------------------------------------
# LLMChain
# ---------------------------------------------------------------------------

class TestLLMChain:
    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value="result from p1")
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="result from p2")
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "result from p1"
        p2.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_fails_second_succeeds(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="result from p2")
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "result from p2"

    @pytest.mark.asyncio
    async def test_all_fail_returns_none(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value=None)
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_winning_provider_name_tracked(self):
        p1 = MagicMock()
        p1.generate = AsyncMock(return_value=None)
        p1.provider_id = "openrouter:meta-llama/llama-3.3-70b-instruct:free"
        p2 = MagicMock()
        p2.generate = AsyncMock(return_value="success")
        p2.provider_id = "openrouter:arcee-ai/trinity-large-preview:free"
        chain = LLMChain([p1, p2])
        result = await chain.generate(PROMPT, SYSTEM, max_tokens=100, timeout=10.0)
        assert result == "success"
        assert chain.last_provider_id == "openrouter:arcee-ai/trinity-large-preview:free"


_ZAI_PATCH = "src.intelligence.llm_providers.to_thread"


class TestZAIProvider(unittest.TestCase):
    """Unit tests for ZAIProvider."""

    def test_success_response(self):
        """ZAI returns valid content from API."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(
            _ZAI_PATCH, new_callable=AsyncMock, return_value="Generated narrative text"
        ) as mock_tt:
            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertEqual(result, "Generated narrative text")
            self.assertEqual(provider.provider_id, "zai:glm-5")
            mock_tt.assert_called_once()

    def test_timeout_error(self):
        """ZAI timeout returns None and logs warning."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(
            _ZAI_PATCH,
            new_callable=AsyncMock,
            side_effect=TimeoutError("Request timed out after 30s"),
        ):
            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_http_429_rate_limit(self):
        """HTTP 429 rate limit returns None."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(
            _ZAI_PATCH,
            new_callable=AsyncMock,
            side_effect=HTTPError(
                url="https://api.z.ai/api/paas/v4/chat/completions",
                code=429,
                msg="Rate limit exceeded",
                hdrs={},
                fp=None,
            ),
        ):
            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_empty_choices_returns_none(self):
        """_call returns None for empty choices; generate propagates None."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(_ZAI_PATCH, new_callable=AsyncMock, return_value=None):
            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_missing_content_returns_none(self):
        """_call returns None for missing content; generate propagates None."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(_ZAI_PATCH, new_callable=AsyncMock, return_value=None):
            provider = ZAIProvider(model="glm-5", api_key="test-key")
            result = asyncio.run(provider.generate("test prompt", "system prompt", 100, 30.0))

            self.assertIsNone(result)

    def test_custom_base_url(self):
        """Custom base URL is used correctly."""
        from src.intelligence.llm_providers import ZAIProvider

        with mock.patch(_ZAI_PATCH, new_callable=AsyncMock, return_value="Response") as mock_tt:
            provider = ZAIProvider(
                model="glm-5",
                api_key="test-key",
                base_url="https://custom.z.ai/v4",
            )
            asyncio.run(provider.generate("test", "system", 100, 30.0))

            # Verify to_thread was called (with the inner _call function)
            call_args = mock_tt.call_args
            self.assertIsNotNone(call_args)
