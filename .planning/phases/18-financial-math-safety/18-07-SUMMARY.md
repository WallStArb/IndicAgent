---
phase: 18-financial-math-safety
plan: 07
subsystem: intelligence
tags: [asyncio, locking, concurrency, indicator-service, plugin-state]

# Dependency graph
requires:
  - phase: 18-financial-math-safety
    provides: lock infrastructure (_i1_plugin_states_locks, _get_state_lock) already wired in __init__
provides:
  - Per-key asyncio.Lock() acquired on every I1 plugin state read and write
  - _update_plugin_state async helper with lock protection
  - _save_plugin_state async helper with lock protection
  - _run_i1_plugins converted to async (lock-protected state access)
affects: [indicator_service, I1 plugin execution, concurrent bar processing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "async with self._get_state_lock(key) wraps both read (setdefault) and write ([key]=) operations"
    - "Two-helper pattern: _update_plugin_state returns state before compute, _save_plugin_state writes back after"

key-files:
  created: []
  modified:
    - services/indicator_service.py
    - tests/unit/service_tests/test_indicator_service.py

key-decisions:
  - "Two separate async helpers (_update_plugin_state, _save_plugin_state) instead of a single context-manager — cleaner than a nested async with spanning a sync compute_full() call"
  - "Tests updated with run_until_complete/_AsyncMock — sync test callers were broken by the async conversion (Rule 1 auto-fix)"

patterns-established:
  - "Per-key lock pattern: _get_state_lock(key) → async with → state access. Same pattern applies to any future plugin state in market_analysis_service if concurrency is needed."

requirements-completed: [API-06]

# Metrics
duration: 10min
completed: 2026-03-08
---

# Phase 18 Plan 07: Activate Per-Key Asyncio Locks for I1 Plugin State Summary

**Orphaned lock infrastructure activated: _update_plugin_state and _save_plugin_state async helpers wrap every I1 plugin state read/write with per-key asyncio.Lock()**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-03-08T16:35:15Z
- **Completed:** 2026-03-08T16:45:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Locks dict and _get_state_lock helper existed but were never acquired — gap now closed
- _update_plugin_state acquires per-key lock before `setdefault` (read), returns state to caller
- _save_plugin_state acquires per-key lock before state write-back
- _run_i1_plugins converted from sync to async: awaits both helpers around p.compute_full()
- Call site in _process_single_bar updated to `await _run_i1_plugins`
- All 12 indicator service unit tests pass; no regressions in full suite (1304 passing)

## Task Commits

1. **Task 1: Create async helpers and wrap state access with per-key lock** - `59cbea4` (feat)

## Files Created/Modified
- `services/indicator_service.py` - Added _update_plugin_state, _save_plugin_state; converted _run_i1_plugins to async; updated call site
- `tests/unit/service_tests/test_indicator_service.py` - Updated sync calls to run_until_complete and patch to AsyncMock

## Decisions Made
- Two separate async helpers chosen over a single context manager spanning compute_full() — a sync function cannot yield inside an async with block, so the lock must be acquired and released around the state access, not around compute itself.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated tests to handle async _run_i1_plugins**
- **Found during:** Task 1
- **Issue:** Three tests called `svc._run_i1_plugins(frames, ...)` synchronously; one patched with `return_value` instead of `AsyncMock`. After the sync→async conversion, all four broke.
- **Fix:** Wrapped direct calls with `asyncio.get_event_loop().run_until_complete(...)` and changed patch to `new=AsyncMock(return_value=...)`
- **Files modified:** tests/unit/service_tests/test_indicator_service.py
- **Verification:** All 12 indicator service tests pass
- **Committed in:** 59cbea4 (part of task commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary consequence of async conversion. No scope creep.

## Issues Encountered
None beyond the test auto-fix above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- I1 indicator service is now fully concurrency-safe for plugin state access
- Locks are acquired on every read and write — no orphaned infrastructure remains
- Ready for phase 18 gap closure completion

---
*Phase: 18-financial-math-safety*
*Completed: 2026-03-08*
