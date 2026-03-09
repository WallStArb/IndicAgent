---
phase: 20-circuit-breaker-integration
plan: 01
subsystem: core
tags: [retry, backoff, jitter, resilience, circuit-breaker]

# Dependency graph
requires: []
provides:
  - exponential_backoff_with_jitter() function in src/core/retry_utils.py
  - retry_with_backoff() async wrapper in src/core/retry_utils.py
  - 15 unit tests covering all retry edge cases
affects:
  - 20-02 (llm_providers.py integration with retry_with_backoff)
  - 20-03 (ibkr.py integration with retry_with_backoff)
  - any future external API call sites

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exponential backoff with jitter: base_delay * 2^attempt, capped at max_delay, ±jitter_factor spread"
    - "retry_with_backoff(): re-raises final exception directly so callers see real error type"
    - "retry_on tuple: exceptions not in tuple propagate immediately without consuming retry budget"

key-files:
  created:
    - src/core/retry_utils.py
    - tests/unit/core/test_retry_utils.py
  modified: []

key-decisions:
  - "jitter_factor=0.5 default (±50%) — wide enough spread to prevent thundering herd on 3+ concurrent retries"
  - "Final attempt re-raises directly (not via last_exception capture) to preserve full exception traceback"
  - "retry_on=(Exception,) default catches all — caller opts in to narrow exception classes for precision"
  - "No retry_tracker callback — retry instrumentation delegated to circuit breaker state counts"

patterns-established:
  - "retry_with_backoff(): pass base_delay=0.0 in unit tests to skip asyncio.sleep (fast test pattern)"

requirements-completed:
  - CB-01
  - CB-02

# Metrics
duration: 2min
completed: 2026-03-09
---

# Phase 20 Plan 01: Retry Utils Summary

**Reusable async retry module with exponential backoff + jitter (base_delay * 2^attempt, ±50% spread) to prevent thundering herd on external API failures**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-09T00:29:38Z
- **Completed:** 2026-03-09T00:31:58Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `src/core/retry_utils.py` with two exported functions: `exponential_backoff_with_jitter()` and `retry_with_backoff()`
- `exponential_backoff_with_jitter()` computes base_delay * 2^attempt, caps at max_delay, applies ±jitter_factor spread
- `retry_with_backoff()` async wrapper retries on configurable exception types, re-raises last exception after max_attempts exhausted
- 15 unit tests covering all edge cases: delay growth, max cap, jitter variation, success path, retry count, exception propagation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create src/core/retry_utils.py module** - `a0f3008` (feat)
2. **Task 2: Add unit tests for retry_utils** - `8f5e629` (test)

## Files Created/Modified

- `src/core/retry_utils.py` — retry utilities module with `exponential_backoff_with_jitter` and `retry_with_backoff`
- `tests/unit/core/test_retry_utils.py` — 15 unit tests, all passing

## Decisions Made

- **jitter_factor=0.5 default** — ±50% spread gives enough variance that concurrent retriers don't collide even without zero-jitter determinism
- **Final attempt re-raises directly** — preserves exception traceback, not captured in `last_exception` variable
- **No retry_tracker callback** — retry instrumentation is handled by circuit breaker state (success_count, failure_count), not duplicated here

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `retry_with_backoff` is importable from `src.core.retry_utils` and ready for integration
- Next: 20-02 integrates `retry_with_backoff` into `llm_providers.py` generate() calls
- Next: 20-03 integrates into `ibkr.py` connection attempts

## Self-Check: PASSED

- `src/core/retry_utils.py` exists: FOUND
- `tests/unit/core/test_retry_utils.py` exists: FOUND
- Commit `a0f3008` (feat): FOUND
- Commit `8f5e629` (test): FOUND
- All 15 tests pass: CONFIRMED

---
*Phase: 20-circuit-breaker-integration*
*Completed: 2026-03-09*
