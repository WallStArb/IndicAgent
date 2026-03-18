---
phase: 35-calibration-tod-multiplier-cis-kalman-filter
plan: 01
subsystem: intelligence/ml
tags: [calibration, isotonic-regression, signal-ledger, weight-updater, ml]
dependency-graph:
  requires: [31-01, 32-01]
  provides: [confidence_calibration table, run_calibration_update(), 58-element LedgerEntry]
  affects: [weight_updater.py, signal_ledger.py, signal_generator_service]
tech-stack:
  added: [sklearn.isotonic.IsotonicRegression, src/intelligence/ml/ package]
  patterns: [independent-failure-domain, isotonic-regression-calibration, ECE-metric]
key-files:
  created:
    - production/migrations/038_calibration_fields.sql
    - src/intelligence/ml/__init__.py
    - src/intelligence/ml/confidence_calibrator.py
    - tests/unit/intelligence/test_confidence_calibrator.py
    - tests/unit/intelligence/ml/__init__.py
  modified:
    - src/intelligence/trading/signal_ledger.py
    - src/intelligence/weight_updater.py
    - tests/unit/intelligence/test_signal_ledger.py
    - tests/unit/test_trade_framer.py
decisions:
  - "run_calibration_update() wrapped in belt-and-suspenders try/except inside weight_updater even though the function already isolates internally — defense-in-depth, never blocks weight update"
  - "Stale curve deletion uses composite string comparison (plugin_name || '::' || timeframe != ALL(trained_pairs)) — avoids asyncpg row type limitations with tuple IN queries"
  - "calibrated_confidence NULL semantics: NULL means N<100 or no curve trained — never a passthrough of raw confidence — ML pipeline uses IS NOT NULL to filter calibrated rows"
metrics:
  duration: "10 minutes"
  completed: "2026-03-17"
  tasks_completed: 3
  files_modified: 8
  files_created: 5
---

# Phase 35 Plan 01: DB Foundation + Confidence Calibration Module Summary

**One-liner:** DB migration adds confidence_calibration table and 4 signal_ledger columns; isotonic regression calibrator with N>=100 gate wired into weight_updater 30-min timer.

## Tasks Completed

| Task | Description | Commit | Status |
|------|-------------|--------|--------|
| 1 | DB migration 038 + LedgerEntry 58-field extension | 21bcd6a | Done |
| 2 | confidence_calibrator.py module (6 tests) | 67aa010 | Done |
| 3 | Wire calibrator into weight_updater.py | b71ca52 | Done |

## What Was Built

### Migration 038 (`production/migrations/038_calibration_fields.sql`)
- `confidence_calibration` table: `plugin_name TEXT, timeframe TEXT, breakpoints DOUBLE PRECISION[], values DOUBLE PRECISION[], ece DOUBLE PRECISION, sample_size INT, updated_at TIMESTAMPTZ` — PRIMARY KEY (plugin_name, timeframe)
- 4 new nullable columns on `signal_ledger`: `raw_cis_score`, `filtered_cis_score`, `calibrated_confidence`, `regime_type_at_fire`
- Full COMMENT documentation on all new columns

### LedgerEntry Extension (`src/intelligence/trading/signal_ledger.py`)
- 4 new Phase 35 fields added after `shadow_outcome` (all default None)
- `to_insert_params()` extended from 54 to 58 elements: `$55=raw_cis_score, $56=filtered_cis_score, $57=calibrated_confidence, $58=regime_type_at_fire`
- `_INSERT_SQL` updated with all four new column names and `$55-$58` placeholders

### Calibration Module (`src/intelligence/ml/confidence_calibrator.py`)
- `run_calibration_update(db_manager)`: queries last 50,000 resolved non-shadow signals, groups by `(setup_plugin, timeframe)`, gates at N>=100
- `_fit_curve()`: fits `IsotonicRegression(out_of_bounds="clip")`, extracts `X_thresholds_`/`y_thresholds_` as breakpoints/values lists
- `_compute_ece()`: 10 equal-width bins, `sum(bin_weight * |frac_win - mean_conf|)`
- Upserts via `ON CONFLICT (plugin_name, timeframe) DO UPDATE`
- Deletes stale rows for groups that dropped below N=100 (or clears entire table if no curves trained)
- Full exception isolation via `try/except Exception` — never propagates to caller

### Weight Updater Integration (`src/intelligence/weight_updater.py`)
- Import added: `from .ml.confidence_calibrator import run_calibration_update`
- Call added at end of `run_weight_update()` (before `return global_result`), with outer try/except guard
- CAL-02: calibration update runs on every 30-min timer tick, always after weight update

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale 54-element tuple assertions across test files**
- **Found during:** Task 3 verification (full suite run)
- **Issue:** `tests/unit/test_trade_framer.py` had 3 tests asserting 54-element tuple; my extension to 58 broke them
- **Fix:** Updated assertions to 58; renamed test functions; added Phase 35 column assertions to `test_insert_sql_has_58_columns`
- **Files modified:** `tests/unit/test_trade_framer.py`
- **Commit:** c53c4e8

## Deferred Issues

Pre-existing failures (present before Phase 35, confirmed via `git stash` verification):
- `tests/unit/api/test_signals_route.py::TestGetSignals::test_get_signals_base_symbol_resolved` — ESH6 vs ESM6 contract roll (Phase 38 derive_roll_chain)
- `tests/unit/config/test_settings.py::TestHelperFunctions::test_get_active_contracts` — Phase 38 settings refactor
- `tests/unit/service_tests/test_ai_narrative_service.py` (11 tests) — pre-existing
- `tests/unit/service_tests/test_signal_generator_service.py` (3 tests) — pre-existing
- `tests/unit/test_historical_backfill.py` (2 tests) — pre-existing
- Full list in `.planning/phases/35-calibration-tod-multiplier-cis-kalman-filter/deferred-items.md`

## Verification Results

```
migration OK: production/migrations/038_calibration_fields.sql has regime_type_at_fire ✓
LedgerEntry OK: raw_cis_score + regime_type_at_fire fields present ✓
calibrator: run_calibration_update, IsotonicRegression, _MIN_SAMPLE_SIZE, 2x DELETE FROM ✓
weight_updater: import + call + logger.error (3 grep matches) ✓
full suite (new tests): 71 signal_ledger+calibrator tests pass ✓
```

## Self-Check: PASSED

- `production/migrations/038_calibration_fields.sql` — FOUND
- `src/intelligence/ml/confidence_calibrator.py` — FOUND
- `src/intelligence/ml/__init__.py` — FOUND
- `tests/unit/intelligence/test_confidence_calibrator.py` — FOUND
- Task commits: 21bcd6a (Task 1), 67aa010 (Task 2), b71ca52 (Task 3), c53c4e8 (test fix) — all FOUND in git log
