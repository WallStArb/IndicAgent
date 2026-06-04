---
phase: 095-pydantic-ai-agents
plan: 03
subsystem: ai
tags: [pydantic-ai, llm, FunctionModel, audit, structured-output, ring0]

# Dependency graph
requires:
  - phase: 095-01
    provides: WorkerContext frozen dataclass with llm_chain field
  - phase: 095-02
    provides: response_format parameter threaded through LLMProviderChain.generate()

provides:
  - make_llm_adapter() FunctionModel factory bridging pydantic-ai to LLMProviderChain
  - _extract_json() prose-strip fallback for gemma4 preambles
  - 13 unit tests covering all bridge behaviors

affects:
  - 095-04
  - 095-05
  - src/core/ai/_run_typed (plan 05 will call make_llm_adapter per invocation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-physical-request call_id minting (copy audit base + fresh uuid4 per _request invocation)
    - Empty output_tools guard pattern (RuntimeError with descriptive message, not silent default)
    - Prose-strip JSON fallback (_extract_json first { to last })
    - FunctionModel single-use per _run_typed call (not a shared singleton)
    - System prompt always from caller closure, never from message parts

key-files:
  created:
    - src/core/ai/llm_adapter.py
    - tests/unit/core/test_core_ai_llm_adapter.py
  modified: []

key-decisions:
  - "Per-request call_id policy: each _request() invocation mints a fresh uuid4 so pydantic-ai validation retries produce distinct llm_calls rows, never duplicate audit rows"
  - "Empty output_tools raises RuntimeError immediately rather than silently defaulting a schema - fail-fast is safer than producing unvalidated output"
  - "system prompt is always the caller-provided closure string, never extracted from SystemPromptPart message parts - prevents message history contamination"
  - "args is passed as raw string to ToolCallPart, never json.loads-ed - pydantic-ai owns validation"

patterns-established:
  - "LLMAdapter pattern: FunctionModel closure captures chain + audit_base + system; per-request stamps fresh call_id"
  - "_extract_json(text): find first { and last } - return substring if start < end, else return text unchanged"

requirements-completed:
  - AGENT-EXEC-01

# Metrics
duration: 15min
completed: 2026-05-31
---

# Phase 095 Plan 03: LLMAdapter FunctionModel Bridge Summary

**pydantic-ai FunctionModel bridge routing structured-output requests through LLMProviderChain with per-physical-request call_id audit, schema-as-response_format, and prose-strip fallback**

## Performance

- **Duration:** 15 min
- **Started:** 2026-05-31T13:00:00Z
- **Completed:** 2026-05-31T13:12:19Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Implemented `make_llm_adapter()` factory (Ring 0) returning a pydantic-ai `FunctionModel` that intercepts structured-output requests, extracts the result_type JSON schema from `output_tools[0]`, and routes through `LLMProviderChain.generate()` with schema as `response_format`
- Implemented retry-audit policy: each `_request()` invocation copies the audit base and stamps fresh `call_id` + `called_at` so pydantic-ai validation retries produce distinct `llm_calls` rows
- Implemented `_extract_json()` prose-strip fallback for gemma4 preambles; added fail-fast RuntimeError guard for empty `output_tools`; raw JSON string wrapped in `ToolCallPart` (not json.loads-ed)
- 13 passing unit tests covering all bridge behaviors including retry call_id uniqueness, system isolation, None path, and prose-fallback

## Task Commits

1. **Task 1: Implement make_llm_adapter() FunctionModel factory** - `b44a10e9` (feat)
2. **Task 2: Unit tests for the LLMAdapter bridge** - `3c43832b` (test)

## Files Created/Modified

- `src/core/ai/llm_adapter.py` - make_llm_adapter() FunctionModel factory, _extract_json() helper; 167 lines
- `tests/unit/core/test_core_ai_llm_adapter.py` - 13 unit tests for all bridge behaviors; 251 lines

## Decisions Made

- Per-request call_id policy chosen over per-_run_typed call_id: a pydantic-ai validation retry re-enters `_request()`, so stamping call_id per physical chain call ensures every `llm_calls` row maps 1:1 to a real model call with no duplicate primary keys.
- `args` passed as raw string to `ToolCallPart` (never json.loads-ed): pydantic-ai owns output validation; the bridge must not pre-parse and risk double-handling or type coercion.
- `system` always from the closure, never from `SystemPromptPart` parts in the message history: message history may contain agent conversation context; the authoritative system prompt must come from the caller.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook could not find ruff/black because the worktree's REPO_ROOT (`agent-a88913d4897ba1d9f/`) does not contain a `.venv/`. Resolved by creating a symlink from the worktree root to the main repo's `.venv/`. This is a one-time worktree setup issue, not a code problem.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `make_llm_adapter()` is ready for Plan 04 (AgentProtocol) and Plan 05 (`_run_typed()` integration)
- Plan 05 will call `make_llm_adapter(worker_context, system, max_tokens, timeout, audit_base)` per `_run_typed()` invocation and pass the result to `pydantic_ai.Agent(model=adapter).run()`
- No blockers

---
*Phase: 095-pydantic-ai-agents*
*Completed: 2026-05-31*
