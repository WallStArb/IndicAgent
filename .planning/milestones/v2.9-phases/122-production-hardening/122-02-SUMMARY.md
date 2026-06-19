---
phase: 122-production-hardening
plan: "02"
subsystem: historical-pipeline
tags: [i2-tier, tier-isolation, pipeline-symmetry, test-coverage]
dependency_graph:
  requires: [122-01]
  provides: [run_analysis_pipeline-2-tuple, tiered-dict-construction, precomputed-features-i2]
  affects: [122-03, 122-04, feature_replay]
tech_stack:
  added: []
  patterns: [tiered-dict-construction, tier-isolation]
key_files:
  modified:
    - production/scripts/run_historical_pipeline.py
    - tests/unit/scripts/test_run_historical_pipeline.py
decisions:
  - "D-04: run_analysis_pipeline returns (flat, tiered) 2-tuple; tier_label captured from tier_sequence loop"
  - "D-05: _build_intelligence_event uses tiered dict; _pick helper deleted; direct tiered.get() construction matches live pipeline"
  - "D-09: _load_precomputed_features SELECT includes i2 and market_context; row unpacking is 10-element"
metrics:
  duration: "~5 minutes"
  completed: "2026-06-12"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 2
---

# Phase 122 Plan 02: Historical Pipeline Tier Isolation Summary

Historical pipeline tier isolation: run_analysis_pipeline returns a (flat, tiered) 2-tuple, _build_intelligence_event switches to direct tiered.get() construction matching the live pipeline, and _load_precomputed_features adds i2 and market_context to its SELECT.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | run_analysis_pipeline returns (flat, tiered) 2-tuple | 2ff7785a | production/scripts/run_historical_pipeline.py |
| 2 | _load_precomputed_features adds i2 and market_context to SELECT | bac004d6 | production/scripts/run_historical_pipeline.py |
| 3 | Update historical pipeline tests for 2-tuple return and tiered call signature | 634ae46a | tests/unit/scripts/test_run_historical_pipeline.py |

## What Was Built

**Task 1:** `run_analysis_pipeline` now returns `tuple[dict[str, Any], dict[str, dict[str, Any]]]`. The tier_sequence loop variable changed from `_` to `tier_label`, and `tiered.setdefault(tier_key_lower, {}).update(out)` accumulates per-tier outputs alongside the existing flat `intelligence` dict. `_build_intelligence_event` signature changed to `tiered: dict[str, dict]`; the `_pick` inner helper was deleted entirely; construction now uses `I2Events(**tiered.get("i2", {}))`, `I3Structure(**tiered.get("i3", {}))`, etc. - identical to the live pipeline path. Both call sites updated.

**Task 2:** `_load_precomputed_features` SELECT extended to include `i2, market_context` after `cross_timeframe_context`. Row unpacking extended from 8 to 10 elements. The merge loop now iterates over 8 tier columns including `i2_col` and `mkt_col`. After migration 124 adds the `i2` column, `--use-precomputed-features` will have complete I2 composite outputs available for I7 plugins.

**Task 3:** Tests updated to match new API. `test_returns_dict` renamed to `test_returns_2_tuple` with tuple assertions. New `test_i2_tier_does_not_contain_macd_fields` verifies tier separation. `TestBuildIntelligenceEvent` tests pass tiered dicts as 3rd argument. `_make_event` in `TestEventToSyncParams` includes `i2=I2Events()`. 55 tests pass; 5 pre-existing failures unrelated to this plan (CIS fields, replay_worker - present before these changes).

## Deviations from Plan

None - plan executed exactly as written.

## Test Results

```
55 passed, 5 failed (pre-existing, unrelated to this plan)
Pre-existing failures: test_insert_signals_sync_writes_cis_fields,
  test_replay_worker_calls_replay_symbol_and_returns_tuple,
  test_replay_worker_closes_connection_on_failure,
  TestCISColumnsInSQL::test_insert_sync_sql_column_placeholder_balance,
  TestCISColumnsInSQL::test_insert_signals_sync_params_include_cis_nulls
```

## Self-Check: PASSED

- [x] production/scripts/run_historical_pipeline.py modified with 2-tuple return, tiered construction, _load_precomputed_features 10-element unpacking
- [x] tests/unit/scripts/test_run_historical_pipeline.py updated with new tests passing
- [x] Commit 2ff7785a exists (Task 1)
- [x] Commit bac004d6 exists (Task 2)
- [x] Commit 634ae46a exists (Task 3)
- [x] grep for `_pick(` in run_historical_pipeline.py returns zero matches
- [x] tiered["i2"] present and excludes MACD fields (verified by test and manual check)
