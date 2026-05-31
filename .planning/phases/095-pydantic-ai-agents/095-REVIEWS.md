---
phase: 095
reviewers: [codex]
reviewed_at: 2026-05-31T05:30:00Z
plans_reviewed:
  - 095-01-PLAN.md
  - 095-02-PLAN.md
  - 095-03-PLAN.md
  - 095-04-PLAN.md
  - 095-05-PLAN.md
---

# Cross-AI Plan Review — Phase 095

## Codex Review

**Summary**

Overall, the phase plan is directionally strong and mostly aligned with the architecture decisions: `WorkerContext` keeps Ring 0 generic, `LLMAdapter` preserves the existing provider chain, `_run_typed()` is opt-in, and `SkepticEvaluator` is migrated without a parallel feature-gated path. The main risks are around exact Ring 0/Ring 1 placement, pydantic-ai model protocol details, and audit-context completeness. The pydantic-ai API assumptions are broadly correct: current docs use `Agent(..., output_type=...)` and `result.output`, not `result_type` / `result.data`.

---

### PLAN 01: WorkerContext + Dependency

**Strengths**

- Frozen dataclass is the right choice for a dependency container.
- `signal_context: Any` preserves the Ring 0 boundary.
- Tests explicitly cover immutability and runtime import isolation.
- Dependency pin `pydantic-ai>=1.0,<2` matches the phase intent.

**Concerns**

- **MEDIUM:** `llm_chain: LLMProviderChain` may still create a Ring violation if `LLMProviderChain` lives outside Ring 0 or imports domain code at import time.
- **LOW:** "Importing WorkerContext does NOT import Ring 1 SignalContext" is good, but the test should also guard against accidental `src.intelligence` imports broadly.
- **LOW:** `requirements.txt` pin alone may not be enough if the repo also has lock files, `pyproject.toml`, Docker images, or CI dependency manifests.

**Suggestions**

- Use `from __future__ import annotations`.
- Put `LLMProviderChain` behind `TYPE_CHECKING` if its import is even slightly risky.
- Add a test that snapshots `sys.modules` before/after importing `src.core.ai.worker_context` and asserts no `src.intelligence` modules appear.
- Check all dependency entry points, not only `requirements.txt`.

**Risk Assessment: LOW**

This is a clean, narrow plan. Main risk is dependency metadata drift or an accidental Ring 1 import through `LLMProviderChain`.

---

### PLAN 02: LLMAdapter

**Strengths**

- Correctly keeps routing through `LLMProviderChain.generate()`, preserving circuit breaking, failover, rate limiting, and audit behavior.
- Thin bridge design is appropriate; pydantic-ai should own validation/retry behavior.
- Testing happy path, response structure, and error propagation is the right core coverage.
- Extracting schema from `model_request_parameters.output_tools[0]` matches the structured-output path.

**Concerns**

- **HIGH:** "Implements pydantic-ai Model protocol" may be underspecified. pydantic-ai model interfaces can require more than `request()` depending on whether you subclass/use `FunctionModel` or implement the protocol directly.
- **HIGH:** Audit context completeness is under-tested. Core rules require `call_id`, `symbol`, `signal_id`, `regime`, `agent_id`, and `prompt_version`; Plan 02 only generally says audit injection.
- **MEDIUM:** Prompt extraction from `messages` is not specified. The adapter must robustly handle `ModelRequest` parts, system/instructions, retries, and prior tool returns.
- **MEDIUM:** `output_tools[0]` assumption should fail clearly if absent. It is valid for typed output, but the adapter should raise a useful error instead of an index error.
- **MEDIUM:** `ToolCallPart(args=response_text)` may be fragile if pydantic-ai expects parsed args or accepts JSON strings depending on version. The integration test in Plan 03 is essential.
- **LOW:** Timeout and max token passthrough should verify exact keyword names expected by the existing `LLMProviderChain.generate()`.

**Suggestions**

- Prefer using pydantic-ai's official custom model/function model extension point if available, rather than hand-implementing a partial protocol.
- Add tests for:
  - missing `output_tools`
  - malformed/non-JSON provider response
  - retry path receives a second request and preserves audit context
  - full audit context forwarded exactly
- Make audit construction either fully explicit in `_run_typed()` or carefully duck-typed in Ring 0 without importing Ring 1.
- Give the adapter a stable `model_name`/profile if pydantic-ai requires one for telemetry or request metadata.

**Risk Assessment: MEDIUM-HIGH**

This is the most protocol-sensitive piece. The plan is conceptually right, but success depends on matching pydantic-ai's current `Model`/`FunctionModel` contract exactly.

---

### PLAN 03: Agent Integration Test

**Strengths**

- Excellent risk reducer for pydantic-ai API correctness.
- Directly validates `output_type=` and `result.output`.
- Proves the adapter is accepted by a real `Agent`, not only unit mocks.
- Catches the most likely breakage around `ToolCallPart` shape.

**Concerns**

- **MEDIUM:** Marked parallel with Plan 02, but it depends on `LLMAdapter` existing. This can only run in parallel if Plan 02 first lands a minimal adapter skeleton/interface.
- **MEDIUM:** "agent instantiated per-call not once at class level" cannot really be proven by an adapter integration test alone; that belongs in Plan 04 tests.
- **LOW:** The test should pin behavior without being too coupled to pydantic-ai internals like exact tool names.

**Suggestions**

- Move "Agent instantiated per-call" assertion to `_run_typed()` tests.
- Keep this test focused on real round trip: mock chain returns JSON, pydantic-ai validates into `SomeModel`, `result.output` is that model.
- Add one negative integration test where mock chain returns invalid JSON and pydantic-ai retries or raises the expected validation/retry error.
- Assert `output_tools` is present inside the fake chain/adapter call, but avoid depending on the exact output tool name unless needed.

**Risk Assessment: MEDIUM**

Very valuable test plan, but dependency ordering should be clarified.

---

### PLAN 04: `_run_typed()` on BaseAIWorker

**Strengths**

- Correct opt-in via `result_type: ClassVar[type[BaseModel] | None] = None`.
- Runtime error on missing `result_type` is the right failure mode.
- Per-call `Agent` construction is correct for fresh audit context.
- Timeout source is explicitly constrained to `self._timeout_s`.
- Tracing span is a good fit for execution observability.

**Concerns**

- **HIGH:** File path says `src/core/ai/base_agent.py`, but project rules state `BaseAIWorker` is Ring 1 domain under `src/intelligence/`. If `BaseAIWorker` really lives in Ring 0, adding `SignalContext`, `BaseModel` result semantics, and agent domain behavior there may violate the architecture.
- **HIGH:** `_run_typed(context: SignalContext, ...)` in Ring 0 would violate the Ring 0 "no domain vocab" rule unless `SignalContext` is TYPE_CHECKING-only and annotations are postponed.
- **HIGH:** Audit context test only mentions `agent_id`; it must cover `call_id`, `symbol`, `signal_id`, `regime`, `agent_id`, and `prompt_version`.
- **MEDIUM:** `WorkerContext` fields include `db_pool` and `memory_client`, but Plan 04 does not say how they are sourced from the worker instance.
- **MEDIUM:** System prompt handling is split: `_run_typed()` receives `system`, adapter receives `system`, but pydantic-ai `Agent` also has instructions/system concepts. The plan should define one canonical path to avoid duplicate or missing system instructions.
- **MEDIUM:** `_default_max_tokens` fallback should be explicitly tested when `max_tokens is None`.
- **LOW:** Lazy imports are good, but should not hide import errors in tests.

**Suggestions**

- Reconcile the file path before implementation. If `BaseAIWorker` is Ring 1, put `_run_typed()` there and import Ring 0 adapter/context downward.
- Build audit context in `BaseAIWorker`, where domain context is legal, then pass a plain dict into the Ring 0 adapter.
- Add tests for complete audit context, default max tokens, explicit max tokens, timeout passthrough, and per-call `Agent` construction.
- Ensure `_run_typed()` calls `Agent(adapter, output_type=self.result_type, retries=1)` and returns `result.output`.
- Add a regression test that unmigrated agents still use `_llm_generate()` / existing paths unchanged.

**Risk Assessment: HIGH**

The behavior is right, but placement could break the Ring architecture. This should be resolved before coding.

---

### PLAN 05: SkepticEvaluator Migration

**Strengths**

- Direct migration avoids a split implementation and feature-gate complexity.
- `agent_id = "skeptic"` cleanup is explicit.
- Transfer function preservation is called out clearly.
- Neutral-on-failure behavior is important and covered.
- Mocking `_run_typed()` for transfer-function tests keeps tests focused.

**Concerns**

- **HIGH:** Renaming `agent_id` from `skeptic_v1` to `skeptic` may affect persisted metrics, dashboards, alerting, feature-store consumers, or historical joins.
- **MEDIUM:** `services/alpha_swarm.py` mapping is mentioned, but other references to `"skeptic_v1"` should be searched globally.
- **MEDIUM:** The system message should include the raw JSON instruction noted in research, especially for `gemma4:e4b`.
- **MEDIUM:** Neutral-on-failure depends on the existing `compute()` wrapper. Tests should confirm `_run_typed()` exceptions are caught at the right layer.
- **LOW:** "No parallel class / no feature gate" is good, but remove dead imports/config/tests too.

**Suggestions**

- Run a repo-wide search for `skeptic_v1`, `ENABLE_PYDANTIC_SKEPTIC`, `SkepticPydanticEvaluator`, and `SkepticComputeAgentV2`.
- Add a migration note or compatibility consideration for downstream consumers of `agent_id`.
- Assert `SkepticResult` fields map exactly to the previous structured output fields.
- Include a test that `_compute()` passes `max_tokens=500` and the expected `_SYSTEM_MESSAGE`.
- Put `OUTPUT ONLY RAW JSON.` or equivalent at the start of the system prompt if local model behavior requires it.

**Risk Assessment: MEDIUM**

Implementation is straightforward after Plan 04, but the `agent_id` rename has integration and observability risk.

---

## Consensus Summary

Only one external reviewer (Codex) was run; `-gemini` excluded Gemini and self is Claude Code (claude skipped for independence).

### Agreed Strengths

- pydantic-ai API assumptions are correct: `output_type=` and `result.output` are right for 1.x
- Thin-bridge LLMAdapter design preserves circuit breaking / audit trail
- Per-call Agent construction (not class-level) is correctly identified as critical
- `_run_typed` RuntimeError on misconfiguration is loud failure — correct
- SkepticEvaluator direct migration (no parallel class, no feature gate) is right

### Top Concerns (Priority Order)

1. **HIGH — Ring boundary for `BaseAIWorker` placement** — Plans 04 tasks reference `src/core/ai/base_agent.py` but CONTEXT.md says BaseAIWorker is Ring 1 (`src/intelligence/`). `_run_typed` takes `context: SignalContext` which is domain vocab — this is legal in Ring 1, illegal in Ring 0. Verify the actual file path before coding.
2. **HIGH — pydantic-ai Model protocol completeness** — LLMAdapter must implement the full FunctionModel contract, not just `request()`. `output_tools[0]` access needs a guard, and `ToolCallPart(args=...)` JSON string vs parsed object must be verified by Plan 03.
3. **HIGH — `agent_id` rename observability blast radius** — `skeptic_v1` → `skeptic` may break OTel metrics, Grafana dashboards, `llm_calls` historical joins, and `shadow_registry`. Search repo-wide before Plan 05 lands.
4. **HIGH — Audit context completeness in tests** — Plan 04 test spec only checks `agent_id` but the audit invariant requires `call_id`, `symbol`, `signal_id`, `regime`, `agent_id`, and `prompt_version` all present.
5. **MEDIUM — System prompt canonical path** — `_run_typed()` passes `system=`, adapter passes it to chain, but pydantic-ai `Agent` also has an `instructions=` parameter. Confirm only one path delivers the system message or they interoperate correctly.

### Divergent Views

N/A — single reviewer.
