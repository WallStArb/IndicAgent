---
phase: 18-financial-math-safety
plan: "06"
subsystem: market_analysis_service
tags: [concurrency, asyncio, plugin-state, locking]
dependency_graph:
  requires: []
  provides: [async-safe-plugin-state-access]
  affects: [market_analysis_service, plugin-state-isolation]
tech_stack:
  added: []
  patterns: [per-key-asyncio-lock, async-nested-function]
key_files:
  created: []
  modified:
    - services/market_analysis_service.py
    - tests/unit/service_tests/test_market_analysis_service.py
key_decisions:
  - "_run_tier converted to async nested function to enable async with lock inside synchronous-style pipeline flow"
  - "Lock wraps both state read (setdefault) and write-back (_state reassignment) as atomic unit"
metrics:
  duration_seconds: 170
  completed_date: "2026-03-08"
  tasks_completed: 2
  files_modified: 2
---

# Phase 18 Plan 06: Plugin State Async Lock Activation Summary

**One-liner:** Activated orphaned per-key asyncio.Lock() infrastructure by converting `_run_tier` and `_run_analysis_pipeline` to async, wrapping state read/write atomically with `async with self._get_state_lock(state_key)`.

## What Was Built

Lock infrastructure (`_plugin_states_locks` dict and `_get_state_lock()` helper) existed since Phase 18 but was never acquired — state access at lines 212-214 was unprotected despite the locks being created. The execution path was synchronous, making `async with` impossible.

Fix: converted both `_run_tier` (nested function) and `_run_analysis_pipeline` (method) to `async def`, then wrapped the plugin state read/write block with `async with self._get_state_lock(state_key):`. Updated all 6 call sites within the pipeline (I2/I3/I4/I5/SMC/I6 tiers) and the outer `await self._run_analysis_pipeline(...)` call in `_calculate_intelligence`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1+2 | Convert _run_tier + _run_analysis_pipeline to async, add lock wrapping | b4ad4dd | services/market_analysis_service.py, tests/unit/service_tests/test_market_analysis_service.py |

## Verification

```
$ grep -n "async with.*_get_state_lock\|async def _run_tier\|async def _run_analysis_pipeline\|await _run_tier\|await.*_run_analysis_pipeline" services/market_analysis_service.py
194:    async def _run_analysis_pipeline(
206:        async def _run_tier(plugins: list[str], tier: str, results: dict[str, Any]) -> None:
212:                    async with self._get_state_lock(state_key):
233:        await _run_tier(TIER_I2, "I2", i2_results)
237:        await _run_tier(TIER_I3, "I3", i3_results)
241:        await _run_tier(TIER_I4, "I4", i4_results)
245:        await _run_tier(TIER_I5, "I5", i5_results)
249:        await _run_tier(TIER_SMC, "SMC", smc_results)
256:        await _run_tier(TIER_I6, "I6", i6_results)
316:        tiered = await self._run_analysis_pipeline(symbol, timeframe, frames)
```

**Tests:** 1308 passing (test count unchanged; 6 tests converted to async)
**Ruff:** E501 only (pre-existing, non-blocking)

## Deviations from Plan

### Auto-fixed Issues

**1. [Auto-fix] Updated 6 test methods to async/await (tests must use async def for async helpers)**
- **Found during:** Task 1 verification
- **Issue:** Tests calling `svc._run_analysis_pipeline(...)` synchronously produced "coroutine was never awaited" warnings and test failures after the function became async
- **Fix:** Added `@pytest.mark.asyncio` and `async def` to 6 test methods; updated all `svc._run_analysis_pipeline(...)` calls to `await`; converted inner helper `run()` in `test_state_accumulates_across_bars_same_symbol` to `async def`
- **Files modified:** `tests/unit/service_tests/test_market_analysis_service.py`
- **Commit:** b4ad4dd (included in same commit)

## Self-Check: PASSED

- services/market_analysis_service.py: FOUND
- tests/unit/service_tests/test_market_analysis_service.py: FOUND
- commit b4ad4dd: FOUND
