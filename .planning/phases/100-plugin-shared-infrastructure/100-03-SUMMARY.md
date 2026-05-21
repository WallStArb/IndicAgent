---
phase: 100-plugin-shared-infrastructure
plan: "03"
subsystem: intelligence-plugins
tags: [bug-fix, incremental-state, plugin-protocol, rsi, cmf, market-profile, session-levels, bocpd]
dependency_graph:
  requires: [100-01]
  provides: [all-5-high-bugs-fixed, incremental-state-protocol-correct]
  affects: [src/intelligence/pipeline/executor.py, all incremental plugins]
tech_stack:
  added: []
  patterns: [state-parameter-protocol, compute-full-seeds-state, compute-next-returns-state]
key_files:
  created: []
  modified:
    - src/intelligence/features/i1_indicators/rsi.py
    - src/intelligence/features/i1_indicators/cmf.py
    - src/intelligence/features/i3_structure/market_profile.py
    - src/intelligence/features/i3_structure/session_levels.py
    - src/intelligence/features/smc_context/bocpd_changepoint.py
    - tests/unit/intelligence/indicators/test_rsi_characterization.py
decisions:
  - "BOCPD was already correct - both compute_full and compute_next already returned _state; no change needed"
  - "RSI characterization tests updated to use state= parameter API (old tests tested the broken self._state pattern)"
metrics:
  duration_minutes: 15
  completed_date: "2026-05-21"
  tasks_completed: 3
  files_modified: 6
---

# Phase 100 Plan 03: Bug Fix -- 5 HIGH Plugin State Bugs Summary

Fixed all 5 HIGH-severity incremental state bugs: RSI and CMF now use state parameter and return _state; MarketProfile and SessionLevels now return _state in compute_next; BOCPD was already correct.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix RSI plugin - self._state -> state param, add _state return | 3b458c2a (pre-crash) | rsi.py |
| 2 | Fix CMF plugin - self._state -> state param, add _state return | fe8f2540 (pre-crash) | cmf.py |
| 3 | Fix MarketProfile, SessionLevels, BOCPD - add missing _state returns | 27331278 | market_profile.py, session_levels.py, test_rsi_characterization.py |

## What Was Fixed

### Task 1 and 2 (RSI and CMF) - completed before session crash, merged to main

Both RSI and CMF plugins had identical bugs:
- `compute_next` read from `self._state` (violated PERF-03, ignored state parameter)
- `compute_next` never returned `_state` (incremental mode silently broken)
- `compute_full` wrote to `self._state` instead of local variable

Fixes: replaced all `self._state` reads with `state` parameter, added `out["_state"] = state` before return, refactored `_seed_state` to return a dict, used `wilders_update` from shared mixins.

### Task 3 (MarketProfile, SessionLevels, BOCPD)

- **MarketProfile**: `compute_next` returned `self._build_output(...)` result without `_state`. Fixed by capturing return value in `out` and adding `out["_state"] = state`.
- **SessionLevels**: `compute_next` returned `result` without `_state`. Fixed by adding `result["_state"] = state` before return.
- **BOCPD**: Already correct. Both `compute_full` (returns `"_state": dict(self._state)`) and `compute_next` (returns `"_state": state`) were already returning _state. No changes needed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_rsi_characterization.py to use state= parameter API**
- **Found during:** Task 3 final verification run (tests/unit/ full suite)
- **Issue:** `test_rsi_characterization.py` set `p._state` directly and called `compute_next` without `state=` parameter. Since RSI was fixed in plan Tasks 1-2 to use the state parameter, these tests now correctly fail (they were testing the broken behavior).
- **Fix:** Updated all 3 tests to pass state via `state=` kwarg and thread returned `_state` through consecutive calls.
- **Files modified:** `tests/unit/intelligence/indicators/test_rsi_characterization.py`
- **Commit:** 27331278

## Verification Results

```
tests/unit/intelligence/test_plugin_incremental.py: 27 passed (0.62s)
tests/unit/intelligence/indicators/test_rsi_characterization.py: 3 passed
Full unit suite: 3572 passed, 8 failed (all 8 pre-existing, unrelated failures)
```

Pre-existing failures are in `test_service_contract_resolution.py`, `test_output_queue.py`, and `test_i2_plugins.py` - none related to plugin state fixes.

## Self-Check: PASSED

- [x] `src/intelligence/features/i3_structure/market_profile.py` exists and contains `out["_state"] = state`
- [x] `src/intelligence/features/i3_structure/session_levels.py` exists and contains `result["_state"] = state`
- [x] `src/intelligence/features/smc_context/bocpd_changepoint.py` unchanged (already correct)
- [x] Commit 27331278 exists in git log
- [x] 27 incremental plugin tests pass
