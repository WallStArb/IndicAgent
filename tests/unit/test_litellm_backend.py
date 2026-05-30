"""Unit tests for LiteLLMBackend (TDD).

Tests verify:
- Ollama success path with correct provider_id and token usage
- Fallback to OpenRouter when Ollama fails
- None return when all providers fail
- Provider list construction (ollama-only and ollama+openrouter)
- Token usage is None on total failure
- _normalize_usage handles both Pydantic model and dict shapes
- Ollama calls receive think=False and options.num_ctx kwargs
- <think>...</think> tags are stripped from response content
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_settings(
    ollama_enabled=True,
    ollama_model="nemotron-3-nano:4b",
    ollama_base_url="http://localhost:11434",
    ollama_num_ctx=4096,
    openrouter_api_key="",
    openrouter_models="",
):
    s = MagicMock()
    s.ollama_enabled = ollama_enabled
    s.ollama_model = ollama_model
    s.ollama_base_url = ollama_base_url
    s.ollama_num_ctx = ollama_num_ctx
    s.openrouter_api_key = openrouter_api_key
    s.openrouter_models = openrouter_models
    return s


def _make_litellm_response(content, prompt_tokens=10, completion_tokens=20):
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.total_tokens = prompt_tokens + completion_tokens
    return resp


@pytest.mark.asyncio
async def test_ollama_success():
    """Ollama returns valid response; result matches content, provider_id and usage are set."""
    settings = _make_settings()
    resp = _make_litellm_response("hello world", prompt_tokens=5, completion_tokens=10)

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = resp
        from src.core.llm.litellm_backend import LiteLLMBackend

        backend = LiteLLMBackend(settings)
        result = await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert result == "hello world"
    assert backend.last_provider_id == "ollama/nemotron-3-nano:4b"
    assert backend.last_token_usage is not None
    assert backend.last_token_usage["total_tokens"] > 0


@pytest.mark.asyncio
async def test_fallback_to_openrouter():
    """Ollama raises ConnectionError; openrouter acompletion succeeds; last_provider_id starts with 'openrouter/'."""
    settings = _make_settings(
        openrouter_api_key="sk-xyz",
        openrouter_models="gpt-4",
    )
    resp = _make_litellm_response("openrouter response", prompt_tokens=8, completion_tokens=15)

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Ollama unreachable")
        return resp

    # Do NOT use importlib.reload() inside patch() context — reload re-imports
    # acompletion from litellm, bypassing the patch on the module namespace.
    from src.core.llm.litellm_backend import LiteLLMBackend

    with patch("src.core.llm.litellm_backend.acompletion", side_effect=side_effect):
        backend = LiteLLMBackend(settings)
        result = await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert result == "openrouter response"
    assert backend.last_provider_id is not None
    assert backend.last_provider_id.startswith("openrouter/")


@pytest.mark.asyncio
async def test_generate_returns_none_when_all_providers_fail():
    """All providers raise; result is None and last_provider_id is None."""
    settings = _make_settings()

    from src.core.llm.litellm_backend import LiteLLMBackend

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = ConnectionError("all fail")
        backend = LiteLLMBackend(settings)
        result = await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert result is None
    assert backend.last_provider_id is None


def test_provider_list_ollama_only():
    """openrouter_api_key is empty -> providers contains only the ollama model string."""
    settings = _make_settings(openrouter_api_key="", openrouter_models="")
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(settings)
    assert backend.providers == ["ollama/nemotron-3-nano:4b"]


def test_provider_list_with_openrouter():
    """openrouter_api_key set + two models -> providers has ollama + 2 openrouter strings."""
    settings = _make_settings(
        openrouter_api_key="sk-xyz",
        openrouter_models="gpt-4,claude-3",
    )
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(settings)
    assert "ollama/nemotron-3-nano:4b" in backend.providers
    assert "openrouter/gpt-4" in backend.providers
    assert "openrouter/claude-3" in backend.providers
    assert len(backend.providers) == 3


@pytest.mark.asyncio
async def test_last_token_usage_none_on_failure():
    """All providers fail; last_token_usage is None."""
    settings = _make_settings()

    from src.core.llm.litellm_backend import LiteLLMBackend

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.side_effect = Exception("provider error")
        backend = LiteLLMBackend(settings)
        result = await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert result is None
    assert backend.last_token_usage is None


def test_normalize_usage_from_pydantic_model():
    """_normalize_usage handles object with .prompt_tokens/.completion_tokens/.total_tokens attrs."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    usage_obj = MagicMock()
    usage_obj.prompt_tokens = 5
    usage_obj.completion_tokens = 10
    usage_obj.total_tokens = 15

    result = LiteLLMBackend._normalize_usage(usage_obj)
    assert result == {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}


def test_normalize_usage_from_dict():
    """_normalize_usage handles dict with prompt_tokens/completion_tokens/total_tokens keys."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    usage_dict = {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}
    result = LiteLLMBackend._normalize_usage(usage_dict)
    assert result == {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15}


@pytest.mark.asyncio
async def test_ollama_kwargs_include_think_false_and_num_ctx():
    """acompletion receives think=False and options.num_ctx for Ollama calls."""
    settings = _make_settings(ollama_num_ctx=4096)
    resp = _make_litellm_response("output")

    from src.core.llm.litellm_backend import LiteLLMBackend

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = resp
        backend = LiteLLMBackend(settings)
        await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert mock_ac.called
    call_kwargs = mock_ac.call_args.kwargs
    assert call_kwargs.get("think") is False
    assert call_kwargs.get("options", {}).get("num_ctx") == 4096


@pytest.mark.asyncio
async def test_think_tags_stripped_from_response():
    """<think>...</think> blocks are stripped from response content before returning."""
    settings = _make_settings()
    resp = _make_litellm_response("<think>reasoning here</think>actual output")

    from src.core.llm.litellm_backend import LiteLLMBackend

    with patch("src.core.llm.litellm_backend.acompletion", new_callable=AsyncMock) as mock_ac:
        mock_ac.return_value = resp
        backend = LiteLLMBackend(settings)
        result = await backend.generate("prompt", "system", max_tokens=100, timeout=30.0)

    assert result == "actual output"
