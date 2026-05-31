"""Unit tests for src/core/ai/llm_adapter.py — make_llm_adapter() FunctionModel bridge."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelRequest, SystemPromptPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, ModelRequestParameters, ToolDefinition

from src.core.ai.llm_adapter import _extract_json, make_llm_adapter
from src.core.ai.worker_context import WorkerContext

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TOOL_SCHEMA = {"type": "object", "properties": {"value": {"type": "number"}}}
_TOOL_NAME = "final_result"


def _make_agent_info(output_tools=None) -> AgentInfo:
    """Build a minimal AgentInfo for tests."""
    if output_tools is None:
        td = ToolDefinition(name=_TOOL_NAME, parameters_json_schema=_TOOL_SCHEMA)
        output_tools = [td]
    return AgentInfo(
        function_tools=[],
        allow_text_output=False,
        output_tools=output_tools,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
        instructions=None,
    )


def _make_messages(user_content: str = "hello", include_system: str | None = None) -> list:
    """Build a messages list with one ModelRequest containing a UserPromptPart."""
    parts = []
    if include_system is not None:
        parts.append(SystemPromptPart(content=include_system))
    parts.append(UserPromptPart(content=user_content))
    return [ModelRequest(parts=parts)]


def _make_audit_base() -> dict:
    return {
        "call_id": "PLACEHOLDER",
        "called_at": "PLACEHOLDER",
        "agent_id": "x",
        "prompt": "hello",
    }


class _FakeChain:
    """Fake LLMProviderChain that records kwargs and returns a fixed response."""

    def __init__(self, return_value: str | None = '{"value": 1.0}'):
        self.calls: list[dict] = []
        self.return_value = return_value

    async def generate(self, **kwargs) -> str | None:
        self.calls.append(dict(kwargs))
        return self.return_value


def _make_worker_context(chain: _FakeChain) -> WorkerContext:
    return WorkerContext(signal_context=object(), llm_chain=chain)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_response_format_and_system():
    """chain.generate receives response_format carrying the schema and the closured system string."""
    chain = _FakeChain()
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    response = await adapter.function(messages, info)

    assert len(chain.calls) == 1
    call = chain.calls[0]
    assert call["system"] == "SYS"
    assert call["prompt"] == "hello"
    rf = call["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == _TOOL_NAME
    assert rf["json_schema"]["schema"] == _TOOL_SCHEMA


@pytest.mark.asyncio
async def test_tool_call_part_args_is_raw_string():
    """Returned ModelResponse has a single ToolCallPart with args as a raw string (not dict)."""
    chain = _FakeChain(return_value='{"value": 1.0}')
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    response = await adapter.function(messages, info)

    assert len(response.parts) == 1
    part = response.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.tool_name == _TOOL_NAME
    assert part.args == '{"value": 1.0}'
    assert isinstance(part.args, str)  # must NOT be json.loads-ed


@pytest.mark.asyncio
async def test_none_response_yields_empty_parts():
    """When chain.generate returns None the response has empty parts."""
    chain = _FakeChain(return_value=None)
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    response = await adapter.function(messages, info)

    assert response.parts == []


@pytest.mark.asyncio
async def test_per_request_call_id_uniqueness():
    """Two consecutive _request calls (retry simulation) produce two DIFFERENT call_ids."""
    chain = _FakeChain()
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    # Simulate pydantic-ai retrying output validation - calls _request twice.
    await adapter.function(messages, info)
    await adapter.function(messages, info)

    assert len(chain.calls) == 2
    call_id_1 = chain.calls[0]["audit_context"]["call_id"]
    call_id_2 = chain.calls[1]["audit_context"]["call_id"]

    assert call_id_1 != "PLACEHOLDER"
    assert call_id_2 != "PLACEHOLDER"
    assert call_id_1 != call_id_2  # One call_id per physical request, no duplicate audit rows.


@pytest.mark.asyncio
async def test_audit_base_preservation():
    """Per-request audit dict carries agent_id and prompt from the audit base."""
    chain = _FakeChain()
    wc = _make_worker_context(chain)
    audit_base = _make_audit_base()
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=audit_base
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    await adapter.function(messages, info)

    recorded = chain.calls[0]["audit_context"]
    assert recorded["agent_id"] == "x"
    assert recorded["prompt"] == "hello"


@pytest.mark.asyncio
async def test_empty_output_tools_raises_runtime_error():
    """When output_tools is empty, _request raises RuntimeError with the expected message."""
    chain = _FakeChain()
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info(output_tools=[])
    messages = _make_messages("hello")

    with pytest.raises(RuntimeError, match="typed output tool schema missing"):
        await adapter.function(messages, info)


@pytest.mark.asyncio
async def test_prose_fallback_extracts_json_substring():
    """When chain returns prose-wrapped JSON, ToolCallPart.args is the JSON substring only."""
    chain = _FakeChain(return_value='Here is the answer: {"value": 1.0} done')
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="SYS", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    messages = _make_messages("hello")

    response = await adapter.function(messages, info)

    part = response.parts[0]
    assert isinstance(part, ToolCallPart)
    assert part.args == '{"value": 1.0}'


@pytest.mark.asyncio
async def test_system_isolation_ignores_system_prompt_parts():
    """When a SystemPromptPart is in the messages, chain still receives the closured system string."""
    chain = _FakeChain()
    wc = _make_worker_context(chain)
    adapter = make_llm_adapter(
        wc, system="CLOSURED_SYSTEM", max_tokens=256, timeout=10.0, audit_context=_make_audit_base()
    )
    info = _make_agent_info()
    # Include a SystemPromptPart with different content - it must be ignored.
    messages = _make_messages("hello", include_system="PART_SYSTEM_CONTENT")

    await adapter.function(messages, info)

    call = chain.calls[0]
    assert call["system"] == "CLOSURED_SYSTEM"
    assert call["system"] != "PART_SYSTEM_CONTENT"


# ---------------------------------------------------------------------------
# _extract_json unit tests (pure function, no async needed)
# ---------------------------------------------------------------------------


def test_extract_json_with_preamble():
    assert _extract_json('preamble {"a": 1} trailer') == '{"a": 1}'


def test_extract_json_plain_json():
    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_no_braces():
    assert _extract_json("no json here") == "no json here"


def test_extract_json_nested():
    assert _extract_json('text {"outer": {"inner": 2}} more') == '{"outer": {"inner": 2}}'


def test_extract_json_empty_string():
    assert _extract_json("") == ""
