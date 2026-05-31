"""LLMAdapter — pydantic-ai FunctionModel bridge to LLMProviderChain.

make_llm_adapter() returns a FunctionModel that intercepts pydantic-ai's structured-output
request, extracts the result_type JSON schema from output_tools, routes the call through
LLMProviderChain.generate() (with schema as response_format for grammar-constrained output),
and wraps the raw JSON string in a ToolCallPart that pydantic-ai validates against result_type.

Design notes:
- The FunctionModel is single-use per _run_typed() call (Pitfall 3: do not share across calls).
- audit_context is a BASE dict whose call_id/called_at are placeholders; each _request()
  invocation stamps a fresh call_id + called_at so that a pydantic-ai validation retry
  produces a DISTINCT llm_calls row rather than a duplicate sharing one call_id.
  (One call_id per physical LLM call, not per _run_typed() invocation.)
- system is always the caller-provided string; it is NEVER derived from message parts.
  SystemPromptPart entries in the message history are ignored.
- The empty-output_tools guard fails fast with a clear RuntimeError rather than silently
  defaulting a schema (output_tools empty means result_type is unset or pydantic-ai chose
  text mode).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src.core.service_utils import format_iso_ts

if TYPE_CHECKING:
    from src.core.ai.worker_context import WorkerContext


def _extract_json(text: str) -> str:
    """Extract the JSON object substring from a potentially prose-wrapped response.

    Returns the substring from the first '{' to the last '}' (inclusive) when both
    are present and the opening brace precedes the closing brace. Otherwise returns
    the original text unchanged.

    This is a safety net for models (e.g. gemma4) that occasionally emit preamble text
    before the JSON payload even when response_format is set. Do NOT json.loads the
    result - pydantic-ai validates the args string itself.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and start < end:
        return text[start : end + 1]
    return text


def make_llm_adapter(
    worker_context: WorkerContext,
    system: str,
    max_tokens: int,
    timeout: float,
    audit_context: dict[str, Any],
) -> FunctionModel:
    """Build a single-use pydantic-ai FunctionModel that routes through LLMProviderChain.

    Args:
        worker_context: Immutable per-run container; provides the LLMProviderChain.
        system: System prompt string. Always passed as-is to chain.generate(); never
            derived from message parts.
        max_tokens: Token limit forwarded to chain.generate().
        timeout: Request timeout (seconds) forwarded to chain.generate().
        audit_context: BASE audit dict (agent_id, symbol, signal_id, prompt_version,
            prompt, etc.). call_id and called_at are placeholders - the adapter stamps
            fresh values per physical chain.generate() call so that pydantic-ai retries
            produce distinct llm_calls rows instead of duplicate call_ids.

    Returns:
        A FunctionModel instance. Construct a new one for each _run_typed() call.
    """
    chain = worker_context.llm_chain
    audit_base = audit_context

    async def _request(
        messages: list[Any],
        info: AgentInfo,
    ) -> ModelResponse:
        # 1. Output-tool guard: fail fast if pydantic-ai selected text mode or
        #    result_type is unset - there is no schema to pass as response_format.
        if not info.output_tools:
            raise RuntimeError(
                "typed output tool schema missing - result_type may be unset or"
                " pydantic-ai selected text mode"
            )
        tool = info.output_tools[0]
        tool_name = tool.name
        schema = tool.parameters_json_schema

        # 2. Prompt extraction: take content from the latest UserPromptPart in the
        #    message history. Ignore all other part types (SystemPromptPart,
        #    ToolReturnPart, RetryPromptPart) and any non-ModelRequest messages.
        #    The caller-provided `system` string (closured above) is always the system
        #    prompt; it is never derived from message parts.
        prompt = ""
        for msg in reversed(messages):
            if not isinstance(msg, ModelRequest):
                continue
            for part in reversed(msg.parts):
                if isinstance(part, UserPromptPart):
                    content = part.content
                    if isinstance(content, list):
                        # Multipart: join only str elements, skip binary/image parts.
                        prompt = " ".join(c for c in content if isinstance(c, str))
                    else:
                        prompt = content
                    break
            else:
                # No UserPromptPart in this request; keep scanning earlier messages.
                continue
            break  # Found the latest UserPromptPart - done.

        # 3. Per-request audit: copy the base and stamp a fresh call_id + called_at.
        #    A pydantic-ai validation retry re-enters _request and mints a NEW call_id,
        #    so each chain.generate() call produces a distinct llm_calls row.
        req_audit = dict(audit_base)
        req_audit["call_id"] = str(uuid4())
        req_audit["called_at"] = format_iso_ts(datetime.now(UTC))

        # 4. Build response_format for litellm/Ollama JSON-schema grammar constraint.
        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {"name": tool_name, "schema": schema},
        }

        # 5. Route through LLMProviderChain - never call the LLM backend directly.
        raw = await chain.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            timeout=timeout,
            audit_context=req_audit,
            response_format=response_format,
        )

        # 6. None means all providers failed or guardrails rejected - return empty
        #    ModelResponse; the agent's compute() wrapper converts this to neutral.
        if raw is None:
            return ModelResponse(parts=[])

        # 7. Prose-strip fallback for gemma4 preambles (response_format should already
        #    constrain output, but this is a safety net). Do NOT json.loads - pydantic-ai
        #    validates the args string itself.
        args = _extract_json(raw)

        # 8. Wrap in a ToolCallPart so pydantic-ai can validate against result_type.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args=args,
                    tool_call_id=str(uuid4()),
                )
            ]
        )

    return FunctionModel(_request)
