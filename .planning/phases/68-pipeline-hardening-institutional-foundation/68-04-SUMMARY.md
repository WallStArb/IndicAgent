---
phase: 68-pipeline-hardening-institutional-foundation
plan: "04"
subsystem: intelligence-pipeline
tags: [schema, symbol-segmentation, aggregates, fallback-hierarchy]
dependency_graph:
  requires: ["68-03"]
  provides: [symbol-keyed-aggregates]
  affects: [setup_performance, tod_multipliers, calibration_curves, llm_model_scores, signal_metrics, signal_metrics_ic]
tech_stack:
  added: [symbol-sentinel-pattern]
  patterns: [2-level-fallback-lookup, global-sentinel-star]
key_files:
  created:
    - production/migrations/064_symbol_keyed_aggregates.sql
  modified:
    - src/intelligence/pipeline/tod_adjuster.py
    - src/intelligence/pipeline/calibrator.py
    - src/intelligence/pipeline/ranker.py
    - src/intelligence/metrics/compute.py
    - services/intelligence_pipeline_agent.py
    - services/signal_metrics_compute_agent.py
    - services/signal_metrics_writer_agent.py
    - services/llm_writer_service.py
decisions:
  - "Use '*' as global sentinel (not NULL) for backward compatibility and SQL NOT NULL constraint"
  - "2-level fallback: symbol-specific first, then '*', then hardcoded prior/passthrough"
  - "All existing rows default to '*' via column DEFAULT — zero data migration needed"
  - "calibration_curves key fixed from (setup_plugin) to (setup_plugin, tf, symbol) — was storing string keys"
metrics:
  duration: 29m
  completed: "2026-04-13"
  tasks: 7
  tests_added: 30
  files_created: 1
  files_modified: 9
---

# Phase 68 Plan 04: Symbol-Keyed Aggregate Tables Summary

Symbol as first-class dimension on all six aggregate tables with 2-level fallback hierarchy so per-instrument multipliers, scores, and calibration curves degrade gracefully from cold start.

## What Was Done

### Task 1: Migration 064
Created `production/migrations/064_symbol_keyed_aggregates.sql` adding `symbol TEXT NOT NULL DEFAULT '*'` to all 6 tables and updating PKs to include symbol as trailing dimension. All existing rows automatically get `'*'`.

### Task 2: tod_adjuster + calibrator symbol params
Updated `apply_tod_adjustment` and `apply_calibration` to accept `symbol: str = "*"` parameter with 2-level DB lookup (symbol-specific then global `'*'`), falling back to session priors (TOD) or passthrough (calibration). Updated dict key types to 4-tuple and 3-tuple respectively. Fixed existing tests to use new key format, added 5 new tests each.

### Task 3: Pipeline agent load methods + call sites
Updated `_load_calibration_curves` to SELECT symbol, extract tf from curve_data JSONB, build `(setup_plugin, tf, symbol)` 3-tuple keys. Fixed pre-existing bug where calibration curves were stored as string keys instead of proper tuples. Updated `_load_tod_multipliers` to build `(regime_type, tf, hour_et, symbol)` 4-tuple keys. Updated both call sites to pass `symbol=symbol`. Added 8 tests.

### Task 4: setup_performance symbol write
Updated signal_metrics_writer_agent setup_performance INSERT to include `symbol` column with `'*'` default and `ON CONFLICT (setup_plugin, symbol)`. Added 2 tests.

### Task 5: llm_model_scores symbol write + recompute
Updated `_SELECT_OUTCOME_ROWS_SQL` to include symbol in SELECT/GROUP BY. Updated `_UPSERT_SCORE_SQL` to include symbol column and ON CONFLICT with symbol. Updated `_recompute_scores` to extract symbol from rows and pass as 5th parameter in upsert tuples, defaulting to `'*'` when NULL. Added 4 tests.

### Task 6: Signal metrics symbol segmentation
Updated `SignalMetricsResult` dataclass with `symbol` field. Updated `compute_signal_metrics` to extract symbol from rows and group by `(plugin, tf, regime_label, symbol)`. Updated compute agent to publish `symbol` in metrics_computed event. Updated writer agent for both `signal_metrics` and `signal_metrics_ic` INSERT with symbol. Updated `ranker.py` to accept `symbol` param with 2-level fallback. Updated `_load_perf_weights` to SELECT symbol and build `(setup_plugin, tf, symbol)` 3-tuples. Updated `rank_signals` call site to pass `symbol=symbol`. Added 12 new tests.

### Task 7: Full test suite + lint
2932 tests pass (39 pre-existing failures unrelated to changes). Ruff: 0 new errors. Black: applied to all modified source files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed existing test key format mismatch**
- **Found during:** Task 2
- **Issue:** Existing tests used 2/3-element tuple keys for calibrator/tod_adjuster, but functions now expect 3/4-element keys with symbol
- **Fix:** Updated all existing test keys to include `'*'` sentinel
- **Files modified:** test_tod_adjuster.py, test_calibrator.py, test_ranker.py
- **Commit:** afcf0b59

**2. [Rule 1 - Bug] Fixed calibration_curves string-key bug**
- **Found during:** Task 3
- **Issue:** `_load_calibration_curves` stored curves keyed by `setup_plugin` string only, not `(plugin, tf)` tuple as the calibrator expected
- **Fix:** Now builds `(setup_plugin, tf, symbol)` 3-tuple keys by extracting tf from curve_data JSONB
- **Files modified:** intelligence_pipeline_agent.py
- **Commit:** fc3db068

**3. [Rule 3 - Blocking] Added missing AsyncMock imports**
- **Found during:** Task 5
- **Issue:** New test methods in test_llm_writer_service.py used `AsyncMock` without importing it
- **Fix:** Added `from unittest.mock import AsyncMock, MagicMock` to each test method
- **Files modified:** test_llm_writer_service.py
- **Commit:** 78a6db28

## Test Results

| Suite | Total | Passed | Failed (pre-existing) |
|-------|-------|--------|-----------------------|
| Full unit tests | 2971 | 2932 | 39 |
| Modified file tests | 58 | 58 | 0 |

## Commits

| Hash | Description |
|------|-------------|
| 5bc5aace | chore(68-04): add migration 064 symbol-keyed aggregate tables |
| afcf0b59 | feat(68-04): add symbol param to tod_adjuster and calibrator with 2-level fallback |
| fc3db068 | feat(68-04): update pipeline agent load methods and call sites for symbol dimension |
| ce684bb0 | feat(68-04): add symbol column to setup_performance INSERT in metrics writer |
| 78a6db28 | feat(68-04): add symbol dimension to llm_model_scores SQL and recompute |
| 19a4400c | feat(68-04): symbol-keyed signal metrics segmentation |
| 3c15882c | style(68-04): fix ruff E501 and apply black formatting |

## Self-Check: PASSED

- All 1 created file verified on disk
- All 7 commits verified in git log
- SUMMARY.md verified at expected path
