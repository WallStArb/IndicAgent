"""Unit tests for response_format threading through LiteLLMBackend and LLMProviderChain.

Covers:
- LiteLLMBackend.generate() forwards response_format to acompletion() when provided
- LiteLLMBackend.generate() omits response_format from acompletion() when not provided
- LLMProviderChain.generate() forwards response_format to _inner.generate()
- LLMProviderChain.generate() passes response_format=None to _inner when omitted

Note: instructor has a broken transitive import in the installed version
(mistralai.Mistral). LiteLLMBackend imports instructor at module level, so we
stub sys.modules before importing the module under test.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub broken instructor package before importing the modules under test
# ---------------------------------------------------------------------------


def _stub_instructor():
    """Insert minimal instructor stub into sys.modules so litellm_backend imports cleanly."""
    if "instructor" not in sys.modules:
        instructor_stub = types.ModuleType("instructor")
        instructor_stub.from_litellm = MagicMock(return_value=MagicMock())
        instructor_stub.Mode = SimpleNamespace(JSON="json")
        sys.modules["instructor"] = instructor_stub
    # Prevent any deep sub-import chains from running
    for sub in [
        "instructor.processing",
        "instructor.processing.multimodal",
        "instructor.processing.function_calls",
        "instructor.core",
        "instructor.core.patch",
        "instructor.providers",
        "instructor.providers.mistral",
        "instructor.providers.mistral.client",
    ]:
        if sub not in sys.modules:
            sys.modules[sub] = types.ModuleType(sub)


_stub_instructor()

# Now safe to import the modules under test
from src.core.llm.chain import LLMProviderChain  # noqa: E402
from src.core.llm.litellm_backend import LiteLLMBackend  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    """Minimal settings stub for LiteLLMBackend construction."""
    s = MagicMock()
    s.ollama_enabled = True
    s.ollama_model = "x"
    s.ollama_base_url = "http://localhost:11434"
    s.ollama_num_ctx = 4096
    s.openrouter_api_key = ""
    s.openrouter_models = ""
    return s


def _make_completion_response(content: str = "hello"):
    """Fake acompletion response with the fields generate() accesses."""
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = 5
    resp.usage.completion_tokens = 5
    resp.usage.total_tokens = 10
    return resp


def _make_backend() -> LiteLLMBackend:
    """Construct a LiteLLMBackend bypassing __init__ to avoid real litellm setup."""
    backend = LiteLLMBackend.__new__(LiteLLMBackend)
    backend._settings = _make_settings()
    backend.providers = ["ollama/x"]
    backend.last_provider_id = None
    backend.last_token_usage = None
    backend.last_instructor_retries = 0
    backend.last_failure_reason = None
    backend._instructor_client = MagicMock()
    return backend


# ---------------------------------------------------------------------------
# LiteLLMBackend tests
# ---------------------------------------------------------------------------


class TestLiteLLMBackendResponseFormat:
    """Tests that response_format reaches acompletion() exactly when provided."""

    @pytest.mark.asyncio
    async def test_response_format_forwarded_to_acompletion(self):
        """acompletion() kwargs include response_format when provided."""
        recorded: list[dict] = []

        async def fake_acompletion(**kwargs):
            recorded.append(kwargs)
            return _make_completion_response()

        backend = _make_backend()
        schema = {"type": "json_schema", "json_schema": {"name": "out", "schema": {}}}

        with patch("src.core.llm.litellm_backend.acompletion", side_effect=fake_acompletion):
            result = await backend.generate(
                "prompt", "system", max_tokens=10, timeout=1.0, response_format=schema
            )

        assert result is not None
        assert len(recorded) == 1
        assert "response_format" in recorded[0], "response_format must be in acompletion kwargs"
        assert recorded[0]["response_format"] == schema

    @pytest.mark.asyncio
    async def test_response_format_absent_when_not_provided(self):
        """acompletion() kwargs must NOT contain response_format when omitted."""
        recorded: list[dict] = []

        async def fake_acompletion(**kwargs):
            recorded.append(kwargs)
            return _make_completion_response()

        backend = _make_backend()

        with patch("src.core.llm.litellm_backend.acompletion", side_effect=fake_acompletion):
            result = await backend.generate("prompt", "system", max_tokens=10, timeout=1.0)

        assert result is not None
        assert len(recorded) == 1
        assert (
            "response_format" not in recorded[0]
        ), "response_format must be absent from acompletion kwargs when not provided"


# ---------------------------------------------------------------------------
# LLMProviderChain tests
# ---------------------------------------------------------------------------


class TestLLMProviderChainResponseFormat:
    """Tests that LLMProviderChain.generate() forwards response_format to _inner."""

    def _make_chain(self) -> LLMProviderChain:
        """Construct LLMProviderChain bypassing __init__ to avoid real LiteLLMBackend setup."""
        chain = LLMProviderChain.__new__(LLMProviderChain)
        chain._call_type = "test"
        chain._cache_ttl = 0
        chain._settings = None
        chain._producer = None
        chain._rate_limiters = {}
        inner = MagicMock()
        inner.last_provider_id = "ollama/x"
        inner.last_token_usage = {"total_tokens": 10}
        chain._inner = inner
        return chain

    @pytest.mark.asyncio
    async def test_chain_forwards_response_format_to_inner(self):
        """chain.generate() with response_format passes it to _inner.generate()."""
        recorded: list[dict] = []

        async def fake_inner_generate(prompt, system, **kwargs):
            recorded.append(kwargs)
            return '{"k": "v"}'

        chain = self._make_chain()
        chain._inner.generate = fake_inner_generate

        schema = {"k": "v"}
        result = await chain.generate(
            "prompt", "system", max_tokens=10, timeout=1.0, response_format=schema
        )

        assert result is not None
        assert len(recorded) == 1
        assert "response_format" in recorded[0], "response_format must be forwarded to inner"
        assert recorded[0]["response_format"] == schema

    @pytest.mark.asyncio
    async def test_chain_passes_none_response_format_when_omitted(self):
        """chain.generate() without response_format passes response_format=None to inner."""
        recorded: list[dict] = []

        async def fake_inner_generate(prompt, system, **kwargs):
            recorded.append(kwargs)
            return "hello"

        chain = self._make_chain()
        chain._inner.generate = fake_inner_generate
        chain._inner.last_token_usage = {"total_tokens": 5}

        result = await chain.generate("prompt", "system", max_tokens=10, timeout=1.0)

        assert result is not None
        assert len(recorded) == 1
        assert (
            recorded[0].get("response_format") is None
        ), "response_format must be None when not provided"
