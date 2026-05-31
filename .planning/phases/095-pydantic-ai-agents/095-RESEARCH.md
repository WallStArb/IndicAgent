# Phase 095: Pydantic AI Execution Layer - Research

**Researched:** 2026-05-31
**Domain:** pydantic-ai >=1.0 custom Model bridge, structured output, dependency injection
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**WorkerContext (Ring 0 dep container)**
- D-01: Location — `src/core/ai/worker_context.py`. Ring 0 portable infrastructure.
- D-02: Implementation — `@dataclass(frozen=True)`. Not a Pydantic model.
- D-03: Fields — Four fields: `signal_context: Any`, `llm_chain: LLMProviderChain`, `db_pool: Any | None = None`, `memory_client: Any | None = None`. `signal_context` typed as `Any` to preserve Ring 0 boundary.
- D-04: Ring boundary — TYPE_CHECKING-only import for `LLMProviderChain` type annotation.

**LLMAdapter (pydantic-ai Model bridge)**
- D-05: Location — `src/core/ai/llm_adapter.py`. Ring 0 infrastructure.
- D-06: Routing — `LLMAdapter` implements pydantic-ai's `Model` protocol. Its `request()` method calls `LLMProviderChain.generate()`. Circuit breaking, failover, rate limiting, and audit trail preserved. Never bypass the chain.
- D-07: Audit injection — `LLMAdapter` constructed with `WorkerContext`. `request()` reads `agent_id`, `prompt_version`, and `symbol` to build `audit_context` before calling `chain.generate()`.
- D-08: Retry — Inherit pydantic-ai `Agent` retry defaults via `retries=` parameter. `LLMAdapter` is a thin bridge, not a retry controller.
- D-09: Structured output — Extract JSON schema from `model_request_parameters` (the `result_type` model schema), pass as `response_format` to `chain.generate()` for Ollama grammar-constrained generation.

**`_run_typed()` on BaseAIWorker**
- D-10: Placement — `result_type: ClassVar[type[BaseModel] | None] = None` and `_run_typed()` live on `BaseAIWorker`.
- D-11: Signature — `async def _run_typed(self, context: SignalContext, prompt: str, system: str, max_tokens: int | None = None) -> BaseModel`. Timeout from `self._timeout_s`. `max_tokens` falls back to `_default_max_tokens: ClassVar[int] = 2048`.
- D-12: Return type — Returns the `result_type` instance directly. Caller converts to `AgentOutput` via `_build_multiplier_output()`.
- D-13: Error on misconfiguration — Calling `_run_typed()` when `result_type is None` raises `RuntimeError` immediately.

**SkepticEvaluator — straight replacement, not parallel experiment**
- D-14: No parallel class — `SkepticEvaluator` is migrated directly. No `SkepticPydanticEvaluator`, no feature gate.
- D-15: Migration — `SkepticEvaluator._compute()` replaces `_llm_generate_structured` call with `await self._run_typed(...)`. `agent_id` renamed `"skeptic_v1"` to `"skeptic"`.
- D-16: No ENABLE_PYDANTIC_SKEPTIC gate — remove it.

### Claude's Discretion
- None specified beyond the locked decisions above.

### Deferred Ideas (OUT OF SCOPE)
- Zep episodic memory (Phase 097) — `memory_client` field reserved but not wired.
- DSPy prompt optimization (Phase 098).
- Narrative/risk agent typed output migration.
- Qualitative pipeline todos (P-CTX-03a, P-CTX-03b, P-CTX-04).
</user_constraints>

---

## Summary

pydantic-ai 1.0 (released September 4, 2025, current as of May 2026 at v1.104.0) provides a typed agent framework with structured output validation. The key deliverable for Phase 095 is **not** replacing `LiteLLMBackend` — it is adding a thin bridge so pydantic-ai's `Agent` can use our existing `LLMProviderChain` as its model backend, preserving circuit breaking, audit trail, and caching.

The architecture is: `BaseAIWorker._run_typed()` constructs a `pydantic_ai.Agent` with `LLMAdapter` as the model, calls `agent.run()`, and returns the validated `result_type` instance. `LLMAdapter` implements the `Model` abstract class. Its `request()` method extracts the JSON schema from `model_request_parameters.output_tools[0].parameters_json_schema`, passes it as `response_format` to `chain.generate()`, then wraps the raw JSON response in a `ModelResponse` with a `ToolCallPart` that pydantic-ai can validate against the schema.

The key insight is that pydantic-ai's default `ToolOutput` mode passes the `result_type` JSON schema to the model as a "tool" parameter schema, then expects the model to respond with a tool call. For a custom `Model`, we intercept this at `request()` time, use the schema to constrain our LLM call, and return a fake tool-call response that pydantic-ai validates with Pydantic.

**Primary recommendation:** Implement `LLMAdapter` as a `FunctionModel` wrapper (simpler than full `Model` subclass) using pydantic-ai's `FunctionModel`, or as a minimal `Model` subclass overriding only `request()`. Both approaches are viable; the `FunctionModel` path is lower friction for this use case.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pydantic-ai` | `>=1.0,<2` | Agent framework with typed output | 1.0 stable API; `output_type` enforces schema at call boundary |
| `pydantic` | `>=2.12.0` (already installed) | Validation | Schema-builds `result_type`; already in use |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pydantic-ai-slim` | same | No extra model SDKs | If we want minimal deps — the `-slim` package has no built-in model clients, just core framework |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `FunctionModel` (simpler bridge) | Full `Model` subclass | Full subclass is 3x more code, requires implementing `request()` properly with `ModelResponse`. `FunctionModel` accepts a plain async function — use it. |
| pydantic-ai `Agent` per call | One `Agent` class-level singleton | Singleton means fixed `result_type` per class — correct for our use case since `result_type` is a `ClassVar` |

**Installation:**
```bash
uv pip install "pydantic-ai>=1.0,<2"
```
Add to `requirements.txt`: `pydantic-ai>=1.0,<2`

## Architecture Patterns

### Recommended Project Structure
```
src/core/ai/
├── base_agent.py          # BaseAIWorker — add _run_typed() + result_type ClassVar
├── evaluator.py           # Evaluator — unchanged
├── worker_context.py      # NEW: WorkerContext frozen dataclass
├── llm_adapter.py         # NEW: LLMAdapter (FunctionModel-based bridge)
├── output.py              # AgentOutput — unchanged
└── ...

src/intelligence/ai/alpha/
├── skeptic_agent.py       # SkepticEvaluator — migrate _compute() to _run_typed()
└── skeptic_prompts.py     # SkepticResult stays here — becomes result_type
```

### Pattern 1: WorkerContext — frozen dep container

**What:** Carries per-run deps into `_run_typed()`. Passed to `LLMAdapter` so audit context is available inside `request()` without coupling to `BaseAIWorker`.

```python
# src/core/ai/worker_context.py
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.llm.chain import LLMProviderChain

@dataclass(frozen=True)
class WorkerContext:
    """Frozen dep container for _run_typed() calls.

    signal_context typed Any: Ring 0 cannot import Ring 1 SignalContext at runtime.
    Caller (BaseAIWorker._run_typed) passes the concrete SignalContext instance.
    """
    signal_context: Any                    # runtime: SignalContext
    llm_chain: "LLMProviderChain"
    db_pool: Any | None = None             # reserved for Phase 097 (Zep memory)
    memory_client: Any | None = None       # reserved for Phase 097 (Zep memory)
```

Ring boundary: `LLMProviderChain` is Ring 0 (`src/core/`), so the TYPE_CHECKING guard is only needed if `chain.py` imports something that imports Ring 1. In practice `LLMProviderChain` is Ring 0, so a direct import is fine — but use TYPE_CHECKING consistently with `base_agent.py` precedent.

### Pattern 2: LLMAdapter via FunctionModel

**What:** pydantic-ai `FunctionModel` accepts an async function `(messages, info) -> ModelResponse`. We construct one per `_run_typed()` call, capturing `worker_context`, `system`, and `max_tokens` via closure.

**Why FunctionModel over full Model subclass:** `FunctionModel` wraps a plain async function. No abstract method ceremony, no streaming to implement. The function signature `(list[ModelMessage], AgentInfo) -> ModelResponse` is all we need.

**Critical: how structured output flows through FunctionModel:**

pydantic-ai in `ToolOutput` mode (the default) registers the `result_type` as an output tool. The tool's JSON schema appears in `info.output_tools[0].parameters_json_schema`. The model is expected to respond with a `ToolCallPart` naming that tool. pydantic-ai then validates the tool args as the `result_type`.

Our bridge:
1. Extract JSON schema from `info.output_tools[0].parameters_json_schema`
2. Pass schema as `response_format` to `chain.generate()` (Ollama grammar-constrained)
3. Parse the raw JSON response string
4. Return `ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=raw_json_str, tool_call_id="0")])`
5. pydantic-ai validates the args dict against `result_type` via Pydantic

```python
# src/core/ai/llm_adapter.py
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

if TYPE_CHECKING:
    from src.core.ai.worker_context import WorkerContext


def make_llm_adapter(
    worker_context: "WorkerContext",
    system: str,
    max_tokens: int,
    timeout: float,
    audit_context: dict[str, Any],
) -> FunctionModel:
    """Construct a FunctionModel that routes through LLMProviderChain.

    The returned FunctionModel is single-use per _run_typed() call.
    audit_context is built by BaseAIWorker._build_audit_context() before this call.
    """
    chain = worker_context.llm_chain

    async def _request(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        # Extract the output tool schema (pydantic-ai ToolOutput mode)
        schema: dict[str, Any] | None = None
        tool_name = "final_result"
        if info.output_tools:
            tool = info.output_tools[0]
            tool_name = tool.name
            schema = tool.parameters_json_schema

        # Build prompt from last user message
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        prompt = ""
        for msg in reversed(messages):
            if isinstance(msg, ModelRequest):
                for part in msg.parts:
                    if isinstance(part, UserPromptPart):
                        prompt = part.content
                        break
            if prompt:
                break

        # Call chain with response_format if schema is available (Ollama grammar)
        response = await chain.generate(
            prompt=prompt,
            system=system,
            max_tokens=max_tokens,
            timeout=timeout,
            audit_context=audit_context,
            # response_format passes JSON schema to Ollama for grammar-constrained generation
            # chain.generate() signature must support this kwarg (see Open Questions)
        )

        if response is None:
            # Return empty text; pydantic-ai will retry or raise
            return ModelResponse(parts=[])

        # Wrap raw JSON as a ToolCallPart so pydantic-ai validates against result_type
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=tool_name,
                    args=response,           # raw JSON string from LLM
                    tool_call_id=str(uuid4()),
                )
            ]
        )

    return FunctionModel(_request)
```

### Pattern 3: `_run_typed()` on BaseAIWorker

**What:** Universal typed execution path. Constructs `WorkerContext`, builds `audit_context`, creates `LLMAdapter`, runs `Agent`, returns validated `result_type` instance.

```python
# In BaseAIWorker — additions only

from typing import ClassVar
from pydantic import BaseModel

class BaseAIWorker(BaseDaemon, ABC):
    result_type: ClassVar[type[BaseModel] | None] = None
    _default_max_tokens: ClassVar[int] = 2048

    async def _run_typed(
        self,
        context: "SignalContext",
        prompt: str,
        system: str,
        max_tokens: int | None = None,
    ) -> BaseModel:
        """Execute a typed LLM call, returning a validated result_type instance.

        Raises RuntimeError if result_type is not set on the subclass.
        Timeout derived from self._timeout_s (computed from latency_budget_ms).
        """
        if self.result_type is None:
            raise RuntimeError(
                f"{self.__class__.__name__}.result_type is None — "
                "set result_type: ClassVar = YourModel to use _run_typed()"
            )

        from pydantic_ai import Agent
        from src.core.ai.llm_adapter import make_llm_adapter
        from src.core.ai.worker_context import WorkerContext

        _max_tokens = max_tokens if max_tokens is not None else self._default_max_tokens
        call_id = str(uuid4())
        audit_context = self._build_audit_context(context, prompt, call_id)

        worker_ctx = WorkerContext(
            signal_context=context,
            llm_chain=self._llm,
        )
        adapter = make_llm_adapter(
            worker_context=worker_ctx,
            system=system,
            max_tokens=_max_tokens,
            timeout=self._timeout_s,
            audit_context=audit_context,
        )

        agent: Agent[None, BaseModel] = Agent(
            adapter,
            output_type=self.result_type,
            retries=1,  # 1 retry on validation failure; LLMProviderChain owns network retries
        )

        result = await agent.run(prompt)
        return result.output
```

### Pattern 4: SkepticEvaluator straight migration

**What:** Replace `_llm_generate_structured` call with `_run_typed`. Same transfer function. Same `SkepticResult`. New `agent_id = "skeptic"`.

```python
class SkepticEvaluator(Evaluator):
    result_type: ClassVar[type[BaseModel]] = SkepticResult
    agent_id = "skeptic"         # was "skeptic_v1" — version suffix removed per Phase 110/111
    prompt_version = ACTIVE_VERSION
    # ... other ClassVars unchanged ...

    async def _compute(self, context: SignalContext) -> AgentOutput:
        prompt = build_skeptic_prompt(context)

        # Straight replacement — _run_typed replaces _llm_generate_structured
        result: SkepticResult = await self._run_typed(  # type: ignore[assignment]
            context,
            prompt=prompt,
            system=_SYSTEM_MESSAGE,
            max_tokens=500,
        )

        failure_probability = result.failure_probability
        llm_confidence = result.confidence
        multiplier = (1.0 - failure_probability) * llm_confidence

        return self._build_multiplier_output(
            context=context,
            multiplier=multiplier,
            confidence=llm_confidence,
            payload={
                "failure_probability": failure_probability,
                "risk_factors": result.risk_factors,
                "reasoning": result.reasoning,
            },
            prompt_version=ACTIVE_VERSION,
        )
```

The `result is None` guard is eliminated — pydantic-ai raises `UnexpectedModelBehavior` on failure, which `BaseAIWorker.compute()` catches and converts to `_neutral()`.

### Anti-Patterns to Avoid

- **Calling `_llm.generate()` directly from LLMAdapter** — always route through `chain.generate()` which owns caching, rate limiting, budget, and audit publication.
- **Full Model subclass when FunctionModel suffices** — FunctionModel accepts a plain async function; full subclass requires implementing `request()` with correct `ModelResponse` construction, `name` property, streaming stubs. Don't pay that cost.
- **Parallel SkepticPydanticEvaluator** — explicitly prohibited by D-14. One class, straight replacement.
- **Importing SignalContext at runtime in Ring 0 files** — always TYPE_CHECKING only. `WorkerContext.signal_context` is typed `Any` for this reason.
- **Building `Agent` as a class-level singleton** — `Agent` embeds the `model` instance. Since `LLMAdapter` (FunctionModel) is constructed per-call with closured state, build `Agent` inside `_run_typed()`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema extraction from Pydantic model | `model.model_json_schema()` + manual | pydantic-ai `info.output_tools[0].parameters_json_schema` | pydantic-ai already builds the schema; reading it from `AgentInfo` is authoritative |
| Validation retry logic | Custom try/except + re-prompt loop | `Agent(retries=1)` | pydantic-ai calls the model again with the validation error as context |
| Parsing structured LLM response | `json.loads()` + error handling | pydantic-ai validates `ToolCallPart.args` against `result_type` | Zero parse failures when grammar-constrained; validation failures get one retry |
| Type-checking LLM output fields | Manual isinstance + range checks | Pydantic field validators on `SkepticResult` (already implemented) | `@field_validator` on `SkepticResult` fires automatically during pydantic-ai validation |

**Key insight:** The `LLMAdapter` bridge is the only novel code. Everything else — validation, retry, schema building — is pydantic-ai. All audit, caching, circuit breaking remains `LLMProviderChain`.

## Common Pitfalls

### Pitfall 1: `response_format` not threaded through `chain.generate()`

**What goes wrong:** JSON schema extracted from `info.output_tools` but dropped before reaching Ollama — model produces prose instead of JSON.

**Why it happens:** `LLMProviderChain.generate()` currently has no `response_format` parameter. The kwarg must be added and threaded through to `LiteLLMBackend.generate()` → `acompletion(response_format=...)`.

**How to avoid:** Phase 095 plan must include a task to add `response_format: dict | None = None` to `chain.generate()` and thread it to `acompletion`. This is a non-trivial change that must come before LLMAdapter can test structured output.

**Warning signs:** LLM returns prose that fails pydantic-ai validation; `UnexpectedModelBehavior` raised instead of a clean `SkepticResult`.

### Pitfall 2: pydantic-ai `output_type` rename from `result_type`

**What goes wrong:** Code using `result_type=` kwarg on `Agent()` gets a `TypeError: unexpected keyword argument`.

**Why it happens:** Breaking change in pydantic-ai 1.0 — `result_type` was renamed to `output_type`. The old name does not exist.

**How to avoid:** Use `output_type=` everywhere. The CONTEXT.md uses `result_type` as the `ClassVar` name on `BaseAIWorker` — that is the internal Python attribute name, NOT the pydantic-ai kwarg. These are different things.

### Pitfall 3: Building LLMAdapter as a singleton

**What goes wrong:** Audit context (`call_id`, `called_at`, `symbol`, `signal_id`) is baked into the FunctionModel closure at construction time. If the same FunctionModel is reused across calls, audit context is stale.

**Why it happens:** `make_llm_adapter()` captures `audit_context` via closure. The closure is frozen at construction time.

**How to avoid:** Construct a fresh `FunctionModel` inside `_run_typed()` on every call. `Agent` is also constructed per-call for the same reason.

**Performance impact:** negligible — `FunctionModel` and `Agent` construction is pure Python, no network.

### Pitfall 4: `ToolCallPart.args` must be a string, not a dict

**What goes wrong:** `TypeError` or `ValidationError` when pydantic-ai tries to validate the tool args.

**Why it happens:** pydantic-ai expects `ToolCallPart.args` to be a raw JSON string (or `ArgsDict`). Passing a Python dict directly may fail depending on the pydantic-ai version.

**How to avoid:** Return the raw JSON string from `chain.generate()` directly as `ToolCallPart(args=response, ...)` — do not `json.loads()` it before passing to `ToolCallPart`. pydantic-ai handles deserialization.

**Verification:** Check the pydantic-ai source for `ToolCallPart` in the version installed. `args: str | ArgsDict` — both are accepted but string is safer.

### Pitfall 5: `AgentRunResult.output` (not `.data` or `.result`)

**What goes wrong:** `AttributeError: 'AgentRunResult' object has no attribute 'data'`

**Why it happens:** pydantic-ai 1.0 renamed `FinalResult.data` → `.output`. Code using old API attribute fails.

**How to avoid:** Always `result.output`. This is verified in the 1.0 changelog.

### Pitfall 6: `agent_id = "skeptic_v1"` survives in shadow_registry

**What goes wrong:** Shadow registry has orphaned `"skeptic_v1"` row after rename to `"skeptic"`. Not a crash but causes confusion in analytics.

**Why it happens:** `shadow_registry_ensure()` is called at startup with `agent_id`. Renaming creates a new row; old row becomes inactive.

**How to avoid:** The CONTEXT.md explicitly acknowledges this: `"shadow_only=True, no production history, no migration needed — let it decay."` No action needed beyond the rename.

## Code Examples

### pydantic-ai Agent with output_type (verified from official docs)

```python
# Source: https://pydantic.dev/docs/ai/core-concepts/agent/
from pydantic import BaseModel
from pydantic_ai import Agent

class MyResult(BaseModel):
    value: float
    reasoning: str

agent = Agent(
    model,              # any Model instance or string
    output_type=MyResult,
    retries=1,
)

result = await agent.run("analyze this")
output: MyResult = result.output  # validated MyResult instance
```

### FunctionModel with AgentInfo (verified from official docs)

```python
# Source: https://pydantic.dev/docs/ai/api/models/function/
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

async def my_model_fn(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> ModelResponse:
    # info.output_tools: list[ToolDefinition] -- output schema is here
    # info.allow_text_output: bool
    # info.instructions: str | None
    return ModelResponse(parts=[TextPart("hello")])

model = FunctionModel(my_model_fn)
```

### Extracting output schema and returning a ToolCallPart

```python
# Pattern for structured output via custom FunctionModel
async def my_model_fn(messages, info: AgentInfo) -> ModelResponse:
    if info.output_tools:
        tool = info.output_tools[0]
        schema = tool.parameters_json_schema  # JSON schema of result_type
        tool_name = tool.name

        # ... call our backend with schema ...
        raw_json = await chain.generate(prompt, system, response_format=schema, ...)

        return ModelResponse(parts=[
            ToolCallPart(
                tool_name=tool_name,
                args=raw_json,          # raw JSON string
                tool_call_id="0",
            )
        ])
    # fallback text path (should not happen when output_type is set)
    return ModelResponse(parts=[TextPart("")])
```

### Dep injection with RunContext (verified from official docs)

```python
# Source: https://pydantic.dev/docs/ai/core-concepts/dependencies/
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext

@dataclass
class MyDeps:
    api_key: str

agent = Agent('openai:gpt-4o', deps_type=MyDeps)

@agent.tool
async def my_tool(ctx: RunContext[MyDeps]) -> str:
    return ctx.deps.api_key

result = await agent.run("query", deps=MyDeps(api_key="abc"))
```

Note: Phase 095 does NOT use `deps_type` — `WorkerContext` is passed via closure to the FunctionModel function, not via RunContext. This is simpler and avoids adding a `deps_type` to agents that don't need tool injection. Agents that need context in tools should use `deps_type` in future phases.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `result_type=` kwarg on Agent | `output_type=` | pydantic-ai 1.0 (Sep 2025) | Must use `output_type` |
| `result.data` on AgentRunResult | `result.output` | pydantic-ai 1.0 (Sep 2025) | Must use `.output` |
| `instructor.from_litellm()` structured calls | pydantic-ai `Agent` with custom Model | Phase 095 | Validation moves to framework; parse failures impossible with grammar constraints |
| Hand-rolled JSON parse + retry | `Agent(retries=1)` | Phase 095 | Framework owns the retry-with-error loop |
| `_llm_generate_structured()` | `_run_typed()` | Phase 095 | Typed return, no None guard, no manual parse_success tracking |

**Terminology map (CONTEXT.md ClassVar name vs pydantic-ai kwarg):**
- `BaseAIWorker.result_type` (ClassVar) — internal name for the type we store on the class
- `Agent(output_type=...)` — the pydantic-ai constructor kwarg (different name, same concept)
- `AgentRunResult.output` — how to read the validated result back

## Open Questions

1. **`response_format` parameter on `chain.generate()`**
   - What we know: `LLMProviderChain.generate()` does not currently accept `response_format`. The `LiteLLMBackend.generate()` calls `acompletion()` which does support `response_format` for Ollama grammar-constrained output.
   - What's unclear: Whether Phase 095 should add `response_format: dict | None = None` to `chain.generate()` and thread it through, or use a different approach (e.g., pass via `extra_kwargs`).
   - Recommendation: Add `response_format` parameter to `chain.generate()` and `litellm_backend.generate()`. Thread it as an extra kwarg to `acompletion`. This is the cleanest path and directly enables grammar-constrained generation. Mark as a plan task.

2. **`ToolCallPart.args` type contract in pydantic-ai 1.x**
   - What we know: Documentation says `args: str | ArgsDict`. Both are accepted.
   - What's unclear: Whether passing a raw JSON string vs `ArgsDict` affects validation behavior.
   - Recommendation: Pass raw JSON string (what `chain.generate()` returns). Test with a unit test using `FunctionModel` override to verify pydantic-ai correctly validates the string args.

3. **pydantic-ai `Agent` construction overhead**
   - What we know: `Agent` and `FunctionModel` are constructed per `_run_typed()` call (per D-07 audit context freshness requirement).
   - What's unclear: Whether there is measurable overhead from per-call construction (model object initialization, schema compilation).
   - Recommendation: Benchmark in unit test. If overhead is significant (>5ms), cache the `Agent` instance and pass audit context via the closure at call time rather than construction time.

4. **`chain.generate()` cache interaction**
   - What we know: `LLMProviderChain` has a 300s semantic cache. Structured calls currently bypass the cache (noted in `generate_structured` docstring: "cache is intentionally skipped for structured calls").
   - What's unclear: Whether `_run_typed()` calls should also bypass the cache.
   - Recommendation: Pass `cache_ttl=0` to `LLMProviderChain` construction in the LLMAdapter path, or disable cache explicitly. Structured outputs should not be cached — the same prompt with a fresh context may produce different valid JSON.

## Sources

### Primary (HIGH confidence)
- [pydantic-ai changelog](https://pydantic.dev/docs/ai/project/changelog/) — 1.0 release date, breaking changes confirmed (`result_type` → `output_type`, `.data` → `.output`)
- [pydantic-ai Agent API](https://pydantic.dev/docs/ai/core-concepts/agent/) — `output_type`, `deps_type`, `retries`, `agent.run()`, `AgentRunResult.output`
- [pydantic-ai Output docs](https://pydantic.dev/docs/ai/core-concepts/output/) — `ToolOutput`, `NativeOutput`, `PromptedOutput`, validation retries
- [pydantic-ai FunctionModel API](https://pydantic.dev/docs/ai/api/models/function/) — constructor, `AgentInfo.output_tools`, `FunctionDef` signature
- [pydantic-ai Dependencies](https://pydantic.dev/docs/ai/core-concepts/dependencies/) — `deps_type`, `RunContext`, `agent.run(deps=...)`
- [pydantic-ai Model abstract class](https://pydantic.dev/docs/ai/api/models/base/) — `request()` signature, `ModelRequestParameters`, `ModelResponse`
- Internal: `src/core/ai/base_agent.py` — `_build_audit_context()`, `_llm_generate_structured()` pattern
- Internal: `src/core/llm/chain.py` — `generate()` and `generate_structured()` signatures
- Internal: `src/intelligence/ai/alpha/skeptic_agent.py` — migration target
- Internal: `src/intelligence/ai/alpha/skeptic_prompts.py` — `SkepticResult` (becomes `result_type`)

### Secondary (MEDIUM confidence)
- [pydantic-ai models overview](https://pydantic.dev/docs/ai/models/overview/) — confirms FunctionModel is the right approach for custom backends
- [pydantic-ai Output API](https://pydantic.dev/docs/ai/api/pydantic-ai/output/) — `ToolOutput`, `NativeOutput`, `PromptedOutput` constructors

### Tertiary (LOW confidence)
- PyPI search result confirming v1.104.0 as of 2026-05-29 — version number only, not verified against official release notes

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — official docs confirm 1.0 stable API, current version verified on PyPI
- Architecture (FunctionModel bridge): HIGH — FunctionModel API verified from official docs; ToolCallPart pattern inferred from AgentInfo.output_tools description (MEDIUM for ToolCallPart specifics)
- Pitfalls: HIGH — `result_type` → `output_type` rename and `.data` → `.output` rename confirmed from changelog
- `response_format` threading: MEDIUM — acompletion supports it (LiteLLM docs), but `chain.generate()` change is a plan task

**Research date:** 2026-05-31
**Valid until:** 2026-06-30 (pydantic-ai 1.x is stable; no breaking changes until v2)
