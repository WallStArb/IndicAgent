---
phase: 14-feedback-loop
plan: 02
subsystem: intelligence
tags: [feedback-loop, setup-performance, tdd, weight-updater, redis, timescaledb, numpy]

# Dependency graph
requires:
  - phase: 14-feedback-loop/14-01
    provides: TDD RED test files for FEED-01/FEED-02 (test_setup_performance_updater.py)
  - phase: 12-signal-integrity
    provides: signal_ledger with pnl_r + resolved_at + setup_plugin + outcome columns
provides:
  - Migration 021: setup_performance table DDL with FEED-02 promotion gate documentation
  - compute_setup_performance(): FEED-01 + FEED-02 — per-setup stats with n>=30 gate
  - run_setup_performance_update(): DB query + setup_performance upsert + Redis write
  - stream_keys.setup_performance_weights_cache(): {env_prefix}setup_performance:weights
  - weight_updater __main__: unified nightly job (CIS weights + setup performance)
affects:
  - 14-03-PLAN (aggregator perf_multiplier + signal generator Redis weight refresh)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sharpe rank → perf_multiplier: sorted ascending (worst=0, best=n-1); multiplier=0.5+(rank/n); single setup → 1.0"
    - "Rolling window filter in Python layer (not SQL) enables unit tests without DB"
    - "env_prefix required with no default on run_setup_performance_update() — prevents silent unqualified-key writes"
    - "Nightly job pattern: same asyncio event loop, shared db_manager, redis_client isolated with try/finally aclose"

key-files:
  created:
    - production/migrations/021_setup_performance_table.sql
    - src/intelligence/setup_performance_updater.py
  modified:
    - src/core/stream_keys.py
    - src/intelligence/weight_updater.py

key-decisions:
  - "Rolling 30-day window filtered in Python layer (not SQL WHERE clause) so unit tests can pass resolved_at datetime objects without mocking DB"
  - "Sharpe rank = 0 for worst performer, rank = n-1 for best; perf_multiplier = 0.5 + (rank/n) yields [0.5, 1.5) range"
  - "std(ddof=1) with fallback to 0.0 sharpe_ratio when std=0 (all same pnl_r) — avoids division by zero for constant-return setups"
  - "Lazy imports inside __main__ block for redis.asyncio, prefix, run_setup_performance_update — keeps importable module top-level imports unchanged"

patterns-established:
  - "Perf multiplier range: [0.5, 1.5) — best Sharpe approaches 1.5, worst gets 0.5, neutral (missing) = 1.0"
  - "FEED-02 gate = MIN_SAMPLE_SIZE = 30 — constant at module level"

requirements-completed: [FEED-01, FEED-02]

# Metrics
duration: 2min
completed: 2026-03-06
---

# Phase 14 Plan 02: Setup Performance Updater Summary

**setup_performance table + compute_setup_performance() with FEED-02 n>=30 gate + Sharpe-rank perf_multiplier + nightly weight_updater extension — 11 RED tests turned GREEN**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-03-06T22:01:42Z
- **Completed:** 2026-03-06T22:03:34Z
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- Implemented `compute_setup_performance()` with 30-day rolling window, null pnl_r exclusion, FEED-02 n>=30 gate, and correct win_rate/sharpe_ratio formulas — all 11 RED tests turned GREEN
- Created `run_setup_performance_update()` with explicit env_prefix requirement, DB upsert, and Redis write via `setup_performance_weights_cache()` key
- Extended `weight_updater.__main__` to run both CIS weight update and setup performance update in one nightly pass using the same event loop and db_manager

## Task Commits

1. **Task 1: Migration 021 + stream_keys helper** - `6df9f87` (feat)
2. **Task 2: setup_performance_updater.py GREEN** - `b3a0d97` (feat)
3. **Task 3: weight_updater __main__ extension** - `a8ae941` (feat)

## Files Created/Modified

- `production/migrations/021_setup_performance_table.sql` - setup_performance DDL with FEED-02 gate comment
- `src/intelligence/setup_performance_updater.py` - compute_setup_performance, _compute_perf_multipliers, run_setup_performance_update
- `src/core/stream_keys.py` - setup_performance_weights_cache() helper function added after llm_scores_cache
- `src/intelligence/weight_updater.py` - __main__ block extended with redis setup + run_setup_performance_update call

## Decisions Made

- Rolling 30-day window is filtered in the Python layer (not SQL WHERE clause) to enable unit tests to pass `resolved_at` datetime objects without mocking the DB
- Sharpe rank ascending (worst=0, best=n-1) yields `perf_multiplier = 0.5 + (rank/n)` in range [0.5, ~1.5) — best performers get the highest multiplier
- `std(ddof=1)` with explicit fallback: `sharpe_ratio = 0.0` when std=0 prevents ZeroDivisionError for constant-return setups
- Lazy imports inside `__main__` block for redis.asyncio/prefix/run_setup_performance_update — keeps module-level imports clean for importable use

## Deviations from Plan

None — plan executed exactly as written. Ruff auto-fixed import block ordering in weight_updater.py (stdlib before third-party), which is normal pre-commit hygiene.

## Issues Encountered

None.

## Next Phase Readiness

- Plan 03: Add `perf_weights` kwarg to `_build_all_ranked()` + `aggregate()`, add `_load_perf_weights()` to `SignalGeneratorService` — test_aggregator_perf.py and test_signal_generator_perf_weights.py turn GREEN (FEED-03 complete)
- setup_performance table not yet applied to production DB (migration 021 must be run manually when ready)

---
*Phase: 14-feedback-loop*
*Completed: 2026-03-06*
