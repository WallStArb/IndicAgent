---
phase: 20-circuit-breaker-integration
plan: 02
subsystem: intelligence
tags: [circuit-breaker, llm-providers, retry, backoff, resilience]

# Dependency graph
requires:
  - phase: 20-01
    provides: retry_utils.py with exponential backoff and jitter
provides:
  - LLM providers (ZAI, OpenRouter, Anthropic, Ollama) wrapped with PluginCircuitBreaker
  - Module-level _llm_circuit_breaker tracking failure/success state per provider_id
  - _call_llm_with_circuit_breaker() helper: sync call_fn + retry_with_backoff + CB tracking
  - 19 unit tests covering all 4 providers and LLMChain fallthrough behavior
affects:
  - 20-03 (next plan in phase — likely plugin-level circuit breaker integration)
  - ai_narrative_service (consumes LLMChain with these providers)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CB helper accepts sync call_fn, wraps in async _run() lambda for fresh coroutine per retry attempt"
    - "Module-level circuit breaker shared across all LLM provider instances (per provider_id key)"
    - "Remove per-provider try/except; unify failure handling in _call_llm_with_circuit_breaker"

key-files:
  created:
    - tests/unit/intelligence/test_llm_providers.py
  modified:
    - src/intelligence/llm_providers.py

key-decisions:
  - "_call_llm_with_circuit_breaker accepts sync call_fn (not a pre-built coroutine) — each retry gets a fresh to_thread(_call) invocation, preventing coroutine reuse errors"
  - "Module-level _llm_circuit_breaker (not per-instance) — all providers share one CB, keyed by provider_id string, enabling cross-instance failure tracking"
  - "Circuit breaker manually increments success_count/failure_count rather than using execute_with_fallback — LLM chain fallthrough is the fallback, not a CB fallback function"

patterns-established:
  - "CB helper pattern: wrap sync blocking fn → async _run lambda → retry_with_backoff → CB state update"
  - "Per-provider_id CB state: provider_id (e.g., 'zai:glm-5') as the key in plugin_states defaultdict"

requirements-completed: [CB-03]

# Metrics
duration: 4min
completed: 2026-03-09
---

# Phase 20 Plan 02: LLM Provider Circuit Breaker Integration Summary

**All four LLM providers (ZAI, OpenRouter, Anthropic, Ollama) wrapped with PluginCircuitBreaker via shared module-level instance and _call_llm_with_circuit_breaker helper with retry_with_backoff**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-09T00:32:55Z
- **Completed:** 2026-03-09T00:36:06Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `_llm_circuit_breaker` module-level PluginCircuitBreaker with 5-min recovery, 3-failure threshold
- Implemented `_call_llm_with_circuit_breaker(provider_id, call_fn)` helper that wraps sync call_fn with exponential backoff retry and CB state tracking
- Updated all 4 LLM providers (ZAI, OpenRouter, Anthropic, Ollama) to use the helper — removes per-provider try/except boilerplate
- Created 19 unit tests covering: CB helper success/failure/none-return, all 4 provider generate() happy/error paths, LLMChain fallthrough behavior

## Task Commits

1. **Task 1: Add imports and circuit breaker instance** - `f7041b5` (feat)
2. **Task 2: Update all LLM providers to use circuit breaker** - `f5b5e4d` (feat)

## Files Created/Modified
- `src/intelligence/llm_providers.py` - Added CB imports, _llm_circuit_breaker instance, _call_llm_with_circuit_breaker helper; updated all 4 providers
- `tests/unit/intelligence/test_llm_providers.py` - 19 tests created

## Decisions Made
- `_call_llm_with_circuit_breaker` takes a sync `call_fn` (not `to_thread(call_fn)`) — the helper wraps it in `async def _run()` so each retry attempt creates a fresh coroutine via `to_thread(call_fn)`, avoiding coroutine reuse errors
- Module-level `_llm_circuit_breaker` shared across all provider instances — failure history persists across chain iterations and service restarts
- Circuit breaker state updated manually (success_count/failure_count) rather than using `execute_with_fallback` — the LLMChain's sequential provider iteration is the fallback mechanism; no separate CB fallback function needed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] retry_with_backoff receives callable not coroutine**
- **Found during:** Task 1 (design review before coding)
- **Issue:** Plan specified `call_coro=to_thread(_call)` passed to `_call_llm_with_circuit_breaker`, but `retry_with_backoff` does `await coro_fn(*args)` — calling a coroutine object fails
- **Fix:** Helper accepts `call_fn` (sync callable), wraps in `async def _run()` that calls `to_thread(call_fn)` — each retry invokes the function fresh
- **Files modified:** src/intelligence/llm_providers.py
- **Verification:** Tests pass including retry-on-failure scenarios
- **Committed in:** f7041b5 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential fix — plan's proposed API was broken. Corrected before writing code, no functionality lost.

## Issues Encountered
None beyond the coroutine/callable distinction caught during design review.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LLM providers fully protected; circuit breaker state trackable via `_llm_circuit_breaker.plugin_states`
- Ready for 20-03 which likely extends circuit breaker to I1 or other plugin tiers

## Self-Check: PASSED

- src/intelligence/llm_providers.py: FOUND
- tests/unit/intelligence/test_llm_providers.py: FOUND
- 20-02-SUMMARY.md: FOUND
- Task commit f7041b5: FOUND
- Task commit f5b5e4d: FOUND

---
*Phase: 20-circuit-breaker-integration*
*Completed: 2026-03-09*
