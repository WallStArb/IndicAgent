---
phase: 122-production-hardening
plan: "04"
subsystem: feature-persistence
tags: [i2-persistence, feature-writer, historical-pipeline, insert-params]
dependency_graph:
  requires: [122-03]
  provides: [i2-column-live-writes, i2-column-historical-writes]
  affects: [intelligence_features, feature_writer, run_historical_pipeline]
tech_stack:
  added: []
  patterns: [split-i2-from-market-context, 33-element-insert-tuple, 14-element-sync-tuple]
key_files:
  created: []
  modified:
    - services/feature_writer.py
    - production/scripts/run_historical_pipeline.py
    - tests/unit/scripts/test_run_historical_pipeline.py
decisions:
  - "i2_data separated from market_ctx; market_ctx now holds only cross_asset_snapshot data"
  - "_build_intelligence_event in historical pipeline now constructs I2Events via _pick helper"
metrics:
  duration_minutes: 10
  completed_date: "2026-06-12"
  tasks_completed: 3
  files_modified: 3
---

# Phase 122 Plan 04: i2 Column Write Path (Live + Historical) Summary

**One-liner:** Both write paths now INSERT i2 as a dedicated JSONB column — feature_writer 33-element tuple, historical sync 14-element tuple — completing the column boundary established by migration 124.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Split i2 from market_context in feature_writer | 44c4807c | services/feature_writer.py |
| 2 | Add i2 to historical _INSERT_FEATURE_SYNC_SQL | 6abf9e26 | production/scripts/run_historical_pipeline.py |
| 3 | Update _event_to_sync_params test to 14-tuple | 90241d47 | tests/unit/scripts/test_run_historical_pipeline.py |

## What Changed

**services/feature_writer.py**
- `_INSERT_FEATURE_SQL`: added `i2` column after `cross_timeframe_context`, before `trading_signals`; added `$15::jsonb` placeholder; all subsequent positions shifted to `$16`-`$33`
- `_record_to_insert_params`: docstring updated to "33-element tuple"; `i2_data = event.i2.model_dump(exclude_none=True)` constructed separately; `market_ctx = cross_asset_snapshot or {}` (i2 fields no longer merged in); `i2_data` inserted at position `$15` (index 14)

**production/scripts/run_historical_pipeline.py**
- `_INSERT_FEATURE_SYNC_SQL`: added `i2` as 14th column
- `_INSERT_FEATURE_SYNC_TEMPLATE`: added 8th `%s::jsonb` placeholder (14 total: 6 plain + 8 jsonb)
- `_event_to_sync_params`: docstring updated to "14-element tuple"; appended `json.dumps(event.i2.model_dump(exclude_none=True))` as element 14
- `_build_intelligence_event`: imports `I2Events`; constructs `i2=I2Events(**_pick(I2Events, intelligence))`
- `_insert_features_sync`: docstring updated to "14-element tuples"

**tests/unit/scripts/test_run_historical_pipeline.py**
- `TestEventToSyncParams._make_event`: adds `I2Events` import and `i2=I2Events()` to event construction
- `test_returns_13_tuple` renamed to `test_returns_14_tuple`; assertion updated to `== 14`

## Verification

```
TestEventToSyncParams::test_returns_14_tuple         PASSED
TestEventToSyncParams::test_first_element_is_datetime PASSED
TestEventToSyncParams::test_jsonb_columns_are_strings PASSED
```

- `_INSERT_FEATURE_SQL` highest `$N` = `$33` (verified programmatically)
- `_INSERT_FEATURE_SYNC_TEMPLATE` `%s` count = 14 (verified programmatically)
- No stray `== 13` assertions for sync params tuple

## Deviations from Plan

**1. [Rule 2 - Missing functionality] Added I2Events to _build_intelligence_event**
- **Found during:** Task 2
- **Issue:** `_build_intelligence_event` constructed `IntelligenceEvent` without `i2=` field; `_event_to_sync_params` would then call `event.i2.model_dump()` on a default-constructed `I2Events` (fine), but the historical replay pipeline would never populate i2 from actual plugin outputs
- **Fix:** Added `I2Events` import and `i2=I2Events(**_pick(I2Events, intelligence))` to `_build_intelligence_event`
- **Files modified:** production/scripts/run_historical_pipeline.py
- **Commit:** 6abf9e26

## Pre-existing Test Failures (Out of Scope)

The following failures existed before this plan and are unrelated:
- `TestCISColumnsInSQL::test_insert_sync_sql_column_placeholder_balance` - regex fails on `_INSERT_SYNC_SQL` (signal_ledger, not features)
- `TestCISColumnsInSQL::test_insert_signals_sync_params_include_cis_nulls` - MagicMock encoding issue
- `test_replay_worker_*` - pre-existing mock failures
- 47 total pre-existing failures in `tests/unit/` (signal_replay_auditor, config, intelligence tests)

## Rollout Sequence

1. Apply migration 124 (Plan 03) - i2 column must exist
2. Deploy feature_writer (this plan Task 1) - live writes use i2 column
3. Restart intelligence_pipeline (Plan 01) - I2Events strict validation
4. Historical pipeline (Plans 02 + 04) - available for next replay run

## Self-Check: PASSED

- `services/feature_writer.py` exists and modified
- `production/scripts/run_historical_pipeline.py` exists and modified
- `tests/unit/scripts/test_run_historical_pipeline.py` exists and modified
- Commits 44c4807c, 6abf9e26, 90241d47 all present in git log
