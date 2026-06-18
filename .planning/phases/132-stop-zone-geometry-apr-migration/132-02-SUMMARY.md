---
phase: 132-stop-zone-geometry-apr-migration
plan: 02
subsystem: trade_framer APR migration
tags: [apr, trade_framer, migration, config_service, regression_test]
dependency_graph:
  requires: [132-01]
  provides: [trade_framer APR keys in config_state, APR-backed stop/zone/target geometry, replay config wiring]
  affects: [intelligence_pipeline prewarm, run_historical_pipeline replay, signal stop placement]
tech_stack:
  added: []
  patterns: [_cfg() module-level utility pattern, ConfigService cache-only warm-up for sync paths]
key_files:
  created:
    - production/migrations/145_phase132_trade_framer_apr.sql
    - tests/unit/intelligence/test_trade_framer_apr_regression.py
  modified:
    - src/intelligence/trading/trade_framer.py
    - src/intelligence/trading/plugin_utils.py
    - services/intelligence_pipeline.py
    - production/scripts/run_historical_pipeline.py
    - tests/unit/intelligence/test_trade_framer.py
decisions:
  - "migration numbered 145 (not 144): migration 144 already existed for signal_events_integrity_index"
  - "ADAPTIVE_BUFFER_HARD_CAP retained as module-level variable: internal _adaptive_buffer() usage deferred to Plan 03; APR key seeded in migration 145"
  - "plugin_utils.py ATR_STOP_FALLBACK_MULTIPLIER replaced with literal 2.0: defensive zone-correction utility, not a tunable behavioral parameter"
  - "ConfigService warm-up for replay uses cache-only mode (database_url='', no asyncpg pool): populates _cache directly from psycopg2 query; get_sync() reads only from cache"
  - "Strict mock ConfigService raises ValueError on unknown APR keys: catches typos at test time rather than silently returning hardcoded fallbacks"
metrics:
  duration_minutes: 16
  tasks_completed: 4
  files_changed: 7
  completed_date: "2026-06-17"
---

# Phase 132 Plan 02: Trade Framer Module-Level APR Migration Summary

**One-liner:** Migrated 19 hardcoded ATR multipliers in trade_framer.py to APR via migration 145 with zero behavioral change at seed values, wired ConfigService into the replay path, and proved regression safety with a strict-mock test suite.

## What Was Done

### Task 1: Migration 145 + _THRESHOLD_KEYS registration

Created `production/migrations/145_phase132_trade_framer_apr.sql` seeding all 19 module-level APR keys into `config_schema`, `config_state`, and `config_history`. Note: the plan referenced migration 144, but that number was already in use (`144_signal_events_integrity_index.sql` for backfill integrity indexes added during Phase 131 execution). Migration 145 was the correct next number.

All 19 seed values equal the current hardcoded values, ensuring zero behavioral change at deployment. Added all 19 keys to `_THRESHOLD_KEYS` in `services/intelligence_pipeline.py` for prewarm cache population at startup.

**Verified:** `SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'feature.trade_framer.%' OR config_key='threshold.trade_framer.min_rr_t1'` returns 19.

### Task 2: Replace module-level constants with _cfg() calls

Replaced every usage site of the 19 migrated constants in `trade_framer.py` with `_cfg("feature.trade_framer.<key>", <seed_value>)` calls (31 `_cfg()` calls total — constants are used in multiple places).

Retained as intentionally NOT migrated:
- `EPSILON_TOLERANCE`: numerical stability constant
- `ATR_EMERGENCY_FALLBACK_PCT`: defensive fallback
- `ATR_TARGET_MAX_MULTIPLIER` + `ATR_TARGET_MAX_MULTIPLIER_BY_TF` dict: dict structure deferred

`ADAPTIVE_BUFFER_HARD_CAP` is seeded in migration 145 but its internal usage inside `_adaptive_buffer()` is preserved until Plan 03 rewires the adaptive buffer body. The module-level variable is retained with an explicit comment noting it's a Plan 03 placeholder.

**Deviation - Rule 1 (Bug fix):** `plugin_utils.py::validate_stop_against_zone()` had a lazy import of `ATR_STOP_FALLBACK_MULTIPLIER` from `trade_framer`. Since that constant was removed, the import was updated to use the literal `2.0` with an APR comment. The existing test file `test_trade_framer.py` also imported `MIN_RR_T1` which was removed; fixed by defining it locally in the test.

**Verified:** 105 existing trade_framer unit tests pass; import clean; ruff/black clean.

### Task 3: Wire ConfigService into run_historical_pipeline.py

Added `_warm_config_service(conn)` function that:
1. Constructs `ConfigService(database_url="")` in cache-only mode (no asyncpg pool)
2. Loads all config_state rows via a single psycopg2 query
3. Populates `cfg._cache` directly from the query results
4. Calls `set_config_service()` on trade_framer, zone_engine, aggregator, confidence_utils, and volume_profile_utils
5. Prints `"Replay config service wired (N keys)"` confirmation

Wired into both execution paths:
- Single-worker path: after `register_all_plugins()` and before `_load_perf_weights()`
- Parallel `_replay_worker()` path: before `_load_calibration_curves()`

**Verified:** `python run_historical_pipeline.py --replay-only --days 2 --symbols QQQ --workers 1` prints "Replay config service wired (208 keys from config_state)" and completes with 97 signals and exit code 0.

### Task 4: Regression test

Created `tests/unit/intelligence/test_trade_framer_apr_regression.py` with 27 tests across 6 test classes:

- `TestStopLongSeedEqualsHardcoded`: 9 tests covering all stop priority paths (demand zone, sweep, OB bottom, FVG low, swing low, EMA-21, S/R, ATR fallback, min_stop floor)
- `TestStopShortSeedEqualsHardcoded`: 3 tests for short direction stop paths
- `TestAdaptiveBufferSeedValues`: 4 tests verifying piecewise math at vol_ratio 0.70/1.0/1.50 and GARCH shock path
- `TestVPProximitySeedEqualsHardcoded`: 2 tests for VP regime activation gate
- `TestStopBasisClassificationSeedEqualsHardcoded`: 2 tests for structure_snap vs garch_adaptive classification
- `TestFrameTradeSeedEqualsHardcoded`: 5 end-to-end tests covering ATR fallback long/short, demand zone structural path, sweep zone path, and RR gate
- `TestStrictMockCatchesTypos`: 2 tests proving the strict mock design is sound

Key design: the `_StrictMockConfigService` raises `ValueError` on any key not in `_APR_SEEDS`, catching key-string typos at test time rather than silently falling back to hardcoded defaults.

**Verified:** 27/27 tests pass; full unit suite 4792 passed, 37 skipped.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration numbered 145 instead of 144**
- **Found during:** Task 1
- **Issue:** Migration 144 already existed (`144_signal_events_integrity_index.sql`) from Phase 131 execution. The plan said to use 144 based on research that listed 143 as the last migration.
- **Fix:** Used 145 as the migration number. All file references updated accordingly.
- **Files modified:** `production/migrations/145_phase132_trade_framer_apr.sql`
- **Commit:** 66570075

**2. [Rule 1 - Bug] plugin_utils.py imported removed constant ATR_STOP_FALLBACK_MULTIPLIER**
- **Found during:** Task 2 (test run revealed ImportError)
- **Issue:** `validate_stop_against_zone()` in `plugin_utils.py` had a lazy import `from .trade_framer import ATR_STOP_FALLBACK_MULTIPLIER, EPSILON_TOLERANCE`. Removing `ATR_STOP_FALLBACK_MULTIPLIER` from trade_framer broke this import.
- **Fix:** Replaced the import with the literal `2.0` (the seed value) with an APR comment. EPSILON_TOLERANCE import retained.
- **Files modified:** `src/intelligence/trading/plugin_utils.py`
- **Commit:** 34660610

**3. [Rule 1 - Bug] test_trade_framer.py imported removed MIN_RR_T1**
- **Found during:** Task 2 (pre-existing import in test file)
- **Issue:** `test_trade_framer.py` imported `MIN_RR_T1` from `trade_framer` which was removed.
- **Fix:** Removed from import list; defined `MIN_RR_T1 = 1.5` locally in the test file with a comment.
- **Files modified:** `tests/unit/intelligence/test_trade_framer.py`
- **Commit:** 34660610

## Self-Check: PASSED

- FOUND: `production/migrations/145_phase132_trade_framer_apr.sql`
- FOUND: `tests/unit/intelligence/test_trade_framer_apr_regression.py`
- FOUND: commit 66570075 (task 1)
- FOUND: commit 34660610 (task 2)
- FOUND: commit 03fbf19c (task 3)
- FOUND: commit 9542d26c (task 4)
- DB: 19 keys in config_state at correct seed values
- Tests: 4792 passed, 37 skipped (full unit suite)
