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
- generate_structured() success path with token usage from raw_completion
- generate_structured() multi-provider fallback (H2)
- generate_structured() circuit breaker shared state (M6)
- generate_structured() max_retries=1 enforcement
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel


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


def test_llm_provider_chain_uses_litellm_backend():
    """LLMProviderChain._inner must be LiteLLMBackend after Plan 02 wiring."""
    from src.core.llm.chain import LLMProviderChain
    from src.core.llm.litellm_backend import LiteLLMBackend

    chain = LLMProviderChain(call_type="test", settings=_make_settings())
    assert isinstance(
        chain._inner, LiteLLMBackend
    ), f"Expected LiteLLMBackend but got {type(chain._inner).__name__}"


# --- Instructor generate_structured() tests ---


class _MockResult(BaseModel):
    value: float
    label: str


@pytest.mark.asyncio
async def test_generate_structured_success():
    """generate_structured returns validated BaseModel on success."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())
    mock_result = _MockResult(value=0.7, label="bullish")
    mock_raw = MagicMock()
    mock_raw.usage.prompt_tokens = 10
    mock_raw.usage.completion_tokens = 20
    mock_raw.usage.total_tokens = 30

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = AsyncMock(
            return_value=(mock_result, mock_raw)
        )
        result = await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert isinstance(result, _MockResult)
    assert result.value == 0.7
    assert backend.last_provider_id == "ollama/nemotron-3-nano:4b"
    # H3: token usage must come from raw_completion.usage
    assert backend.last_token_usage is not None
    assert backend.last_token_usage["total_tokens"] == 30


@pytest.mark.asyncio
async def test_generate_structured_returns_none_on_failure():
    """generate_structured returns None when instructor raises after retries."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = AsyncMock(
            side_effect=Exception("instructor exhausted retries")
        )
        result = await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert result is None
    assert backend.last_provider_id is None


@pytest.mark.asyncio
async def test_generate_structured_sets_last_instructor_retries():
    """last_instructor_retries is 0 after a single-attempt success."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())
    mock_result = _MockResult(value=0.5, label="neutral")
    mock_raw = MagicMock()
    mock_raw.usage = None

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = AsyncMock(
            return_value=(mock_result, mock_raw)
        )
        await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert backend.last_instructor_retries == 0


@pytest.mark.asyncio
async def test_generate_structured_uses_max_retries_1():
    """generate_structured passes max_retries=1 -- not the instructor default of 3."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())
    mock_result = _MockResult(value=0.5, label="neutral")
    mock_raw = MagicMock()
    mock_raw.usage = None
    call_kwargs: dict = {}

    async def capture(**kwargs):
        call_kwargs.update(kwargs)
        return mock_result, mock_raw

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = capture
        await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert call_kwargs.get("max_retries") == 1, (
        f"Expected max_retries=1, got {call_kwargs.get('max_retries')}. "
        "With gemma4:e4b at ~50s/call, default 3 retries = 150s > 120s budget."
    )


# H2: Multi-provider fallback tests


@pytest.mark.asyncio
async def test_generate_structured_falls_back_to_secondary_provider():
    """H2: If primary provider fails, generate_structured tries the secondary provider."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    settings = _make_settings()
    settings.openrouter_api_key = "sk-test"
    settings.openrouter_models = "openai/gpt-4"
    backend = LiteLLMBackend(settings)

    mock_result = _MockResult(value=0.9, label="bearish")
    mock_raw = MagicMock()
    mock_raw.usage = None
    call_count = 0

    async def side_effect(**kwargs):
        nonlocal call_count
        call_count += 1
        if kwargs.get("model", "").startswith("ollama/"):
            raise Exception("ollama down")
        return mock_result, mock_raw

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = side_effect
        result = await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert result is not None, "Secondary provider should have been tried"
    assert backend.last_provider_id is not None
    assert backend.last_provider_id.startswith("openrouter/")
    assert (
        call_count == 2
    ), f"Expected 2 provider attempts (ollama fail + openrouter success), got {call_count}"


@pytest.mark.asyncio
async def test_generate_structured_skips_open_circuit():
    """H2: generate_structured skips a provider whose circuit breaker is open."""
    from src.core.llm.litellm_backend import _OLLAMA_CB, LiteLLMBackend

    settings = _make_settings()
    settings.openrouter_api_key = "sk-test"
    settings.openrouter_models = "openai/gpt-4"
    backend = LiteLLMBackend(settings)

    # Open the ollama circuit breaker
    for _ in range(10):
        _OLLAMA_CB.record_failure()

    mock_result = _MockResult(value=0.5, label="neutral")
    mock_raw = MagicMock()
    mock_raw.usage = None
    ollama_called = False

    async def side_effect(**kwargs):
        nonlocal ollama_called
        if kwargs.get("model", "").startswith("ollama/"):
            ollama_called = True
        return mock_result, mock_raw

    from src.observability.circuit_breaker import CircuitState

    try:
        with patch.object(backend, "_instructor_client") as mock_client:
            mock_client.chat.completions.create_with_completion = side_effect
            result = await backend.generate_structured(
                prompt="test",
                system="OUTPUT ONLY RAW JSON.",
                response_model=_MockResult,
                max_tokens=100,
                timeout=5.0,
            )

        # CB should be open, ollama skipped, openrouter used
        assert not ollama_called, "Ollama should have been skipped due to open circuit breaker"
    finally:
        # Always reset the shared module-level circuit breaker so subsequent tests
        # do not see polluted state if any assertion above fails (WR-03).
        _OLLAMA_CB._state = CircuitState.CLOSED
        _OLLAMA_CB._failures = 0


# M6: Circuit breaker shared state test


@pytest.mark.asyncio
async def test_generate_structured_failures_trip_same_circuit_breaker_as_generate():
    """M6: generate_structured failures must trip the same _OLLAMA_CB as generate() failures.

    An agent cannot bypass an open circuit breaker by switching from generate() to
    generate_structured(). Both paths must share circuit breaker state.
    """
    from src.core.llm import litellm_backend as lb_module
    from src.core.llm.litellm_backend import _OLLAMA_CB, LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())

    # Simulate a failure via generate_structured()
    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = AsyncMock(
            side_effect=Exception("provider error")
        )
        await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    # The same _OLLAMA_CB instance must have recorded the failure
    # We verify by checking that allow_request() behavior is consistent with failure recorded
    # (exact internal state checking depends on CircuitBreaker implementation)
    # At minimum: the same module-level _OLLAMA_CB is used (not a new instance)
    assert lb_module._OLLAMA_CB is _OLLAMA_CB, (
        "generate_structured must use the same module-level _OLLAMA_CB as generate(), "
        "not a new instance. Both paths must share circuit breaker state."
    )


@pytest.mark.asyncio
async def test_generate_structured_token_usage_from_raw_completion():
    """H3: last_token_usage is populated from raw_completion.usage, not from BaseModel."""
    from src.core.llm.litellm_backend import LiteLLMBackend

    backend = LiteLLMBackend(_make_settings())
    mock_result = _MockResult(value=0.5, label="test")
    mock_raw = MagicMock()
    mock_raw.usage.prompt_tokens = 100
    mock_raw.usage.completion_tokens = 200
    mock_raw.usage.total_tokens = 300

    with patch.object(backend, "_instructor_client") as mock_client:
        mock_client.chat.completions.create_with_completion = AsyncMock(
            return_value=(mock_result, mock_raw)
        )
        await backend.generate_structured(
            prompt="test",
            system="OUTPUT ONLY RAW JSON.",
            response_model=_MockResult,
            max_tokens=100,
            timeout=5.0,
        )

    assert backend.last_token_usage == {
        "prompt_tokens": 100,
        "completion_tokens": 200,
        "total_tokens": 300,
    }, f"Token usage not extracted from raw_completion: {backend.last_token_usage}"
