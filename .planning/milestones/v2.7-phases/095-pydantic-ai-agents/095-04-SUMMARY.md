---
phase: 095-pydantic-ai-agents
plan: 04
subsystem: core-ai
tags: [base-agent, pydantic-ai, typed-output, unit-tests]
dependency_graph:
  requires: [095-03]
  provides: [_run_typed, result_type ClassVar, __init_subclass__ guard]
  affects: [src/core/ai/base_agent.py, all BaseAIWorker subclasses]
tech_stack:
  added: []
  patterns: [ClassVar typed output opt-in, lazy-import per-method, placeholder call_id pattern]
key_files:
  created: []
  modified:
    - src/core/ai/base_agent.py
    - tests/unit/core/test_core_ai_base_agent.py
decisions:
  - "call_id placeholder is empty string, not uuid4() - adapter mints per physical request to prevent retry duplicate audit rows"
  - "_run_typed lazy-imports pydantic_ai.Agent, make_llm_adapter, WorkerContext to avoid module-load cost and circular import chains"
  - "tracer span wraps only the Agent.run() call (after RuntimeError guard) matching _llm_generate_structured pattern"
metrics:
  duration_minutes: 4
  completed_date: "2026-05-31"
  tasks_completed: 2
  files_modified: 2
---

# Phase 095 Plan 04: _run_typed Universal Typed Execution Path Summary

**One-liner:** `_run_typed()` on `BaseAIWorker` with pydantic-ai 1.0 API, per-call adapter construction, timeout from `_timeout_s`, `max_tokens=None` resolution, and `__init_subclass__` guard catching bad `result_type` at class-definition time.

## What Was Built

Added four items to `BaseAIWorker` in `src/core/ai/base_agent.py`:

1. `result_type: ClassVar[type[BaseModel] | None] = None` - Universal typed-output opt-in. Subclasses set this to a pydantic BaseModel subclass to enable `_run_typed()`. Agents that never set it keep identical runtime behavior (AGENT-EXEC-05).

2. `_default_max_tokens: ClassVar[int] = 2048` - Conservative token ceiling used when `_run_typed()` caller passes `max_tokens=None`. Prevents `None` from reaching `chain.generate()` which requires an int (REVIEWS MEDIUM fix).

3. `__init_subclass__` guard - Validates `result_type` at class-definition time (not first call). Raises `TypeError` immediately when a subclass sets `result_type` to a non-BaseModel value (REVIEWS LOW item 10).

4. `async def _run_typed(context, prompt, system, max_tokens=None) -> BaseModel` - Constructs a single-use `WorkerContext + LLMAdapter` per call, runs `pydantic_ai.Agent(output_type=self.result_type, retries=1)`, returns `result.output`. Raises `RuntimeError` immediately when `result_type is None` (D-13). Timeout always derived from `self._timeout_s` (D-11). Audit context passed with `call_id=""` placeholder - adapter stamps fresh call_id per physical request so retries produce distinct `llm_calls` rows. Wrapped in `"agent.run_typed"` tracer span matching `_llm_generate_structured` pattern. `_llm_generate` and `_llm_generate_structured` are NOT modified.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Add ClassVars, __init_subclass__ guard, and _run_typed() | 6d7d17a5 | src/core/ai/base_agent.py (+98 lines) |
| 2 | Unit tests for _run_typed() and __init_subclass__ guard | b7955d33 | tests/unit/core/test_core_ai_base_agent.py (+197 lines) |

## Decisions Made

- **Placeholder call_id:** `_run_typed` passes `call_id=""` to `_build_audit_context`. The `LLMAdapter` (Plan 03) stamps a fresh `uuid4()` call_id per physical `chain.generate()` call, so pydantic-ai retries produce distinct `llm_calls` rows instead of duplicate call_ids. This is the correct call_id ownership split established in Plan 03.

- **Lazy imports inside `_run_typed`:** `from pydantic_ai import Agent`, `make_llm_adapter`, `WorkerContext` are imported inside the method body to avoid module-load cost (pydantic-ai is heavyweight) and prevent any potential circular import chains that could form if base_agent.py imported them at module level.

- **No span around RuntimeError guard:** The tracer span wraps only the `Agent.run()` call (placed after the RuntimeError guard). This mirrors `_llm_generate_structured` - failures before the LLM call are not LLM call failures.

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- `pytest tests/unit/core/test_core_ai_base_agent.py -q`: 13 passed (7 pre-existing + 6 new)
- `pytest tests/unit/ -q` (excluding pre-existing collection errors): 3976 passed, 31 skipped
- `ruff check src/core/ai/base_agent.py tests/unit/core/test_core_ai_base_agent.py`: clean
- `git diff 8738893b src/core/ai/base_agent.py` shows no deletions from `_llm_generate` or `_llm_generate_structured`

## Self-Check: PASSED

- `src/core/ai/base_agent.py` exists and contains `_run_typed`
- Commit `6d7d17a5` exists (Task 1: ClassVars + guard + _run_typed)
- Commit `b7955d33` exists (Task 2: unit tests)
- All 13 tests green, no regressions introduced
