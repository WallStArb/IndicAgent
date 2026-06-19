---
phase: 122-production-hardening
plan: "05"
subsystem: data-layer
tags: [column-rename, migration, api, zone-engine, atr]
dependency_graph:
  requires: [122-03, 122-04]
  provides: [intelligence_features-canonical-column-names, zone-engine-atr-floor]
  affects: [feature_writer, run_historical_pipeline, api-routes, zone_engine]
tech_stack:
  added: []
  patterns: [column-rename-migration, test-mock-update]
key_files:
  created:
    - production/migrations/125_rename_intelligence_features_columns.sql
  modified:
    - services/feature_writer.py
    - production/scripts/run_historical_pipeline.py
    - src/api/routes/signals.py
    - src/api/routes/features.py
    - src/api/routes/narrative.py
    - src/intelligence/trading/zone_engine.py
    - tests/unit/api/test_features_route.py
    - tests/unit/api/test_signals_route.py
    - tests/unit/api/test_narrative_route.py
decisions:
  - "Removed unused get_atr import from zone_engine after replacing sole call site with get_atr_with_floor"
  - "Updated test mock rows in 3 API test files to use new column names (Rule 1 auto-fix)"
metrics:
  duration_minutes: 15
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 9
  completed_date: "2026-06-12"
---

# Phase 122 Plan 05: Column Rename + Zone Engine ATR Floor Summary

Migration 125 renames 4 legacy intelligence_features columns to canonical tier names (i1/i3/i4/i5), and zone_engine.collect_candidates replaces an instrument-agnostic ATR fallback with get_atr_with_floor.

## What Was Built

**Migration 125 (Track 2):** SQL migration renaming 4 columns in `intelligence_features`:
- `technical_indicators` -> `i1`
- `pattern_detections` -> `i5`
- `regime_features` -> `i3`
- `confluence_scores` -> `i4`

Column names now match tier designations exactly. `smc` and `cross_timeframe_context` (I6) were already correctly named.

**Write path updates:** Both `feature_writer._INSERT_FEATURE_SQL` and `run_historical_pipeline._INSERT_FEATURE_SYNC_SQL`/`_event_to_sync_params`/`_load_precomputed_features` updated to use new column names throughout.

**API route updates (3 routes):**
- `signals.py`: `_build_signal_row` features dict, `feat_query` SELECT, JOIN query SELECT
- `features.py`: Both export and paginated SELECT queries; tier mapping loop row key references
- `narrative.py`: `_build_signal_context` `row.get()` calls; `_SIGNAL_QUERY` column list

**Zone engine ATR floor (Track 4):** `collect_candidates` at line 231 replaced:
- Before: `atr = get_atr(features) or 0.5` (hardcoded 0.5 is wrong for NQ tick=0.25, VX tick=0.05)
- After: `symbol = features.get("symbol", ""); atr = get_atr_with_floor(features, symbol)` with `if atr is None: return []` guard

Unused `get_atr` import replaced with `get_atr_with_floor`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migration 125 + write path column rename | 7333b334 | migration SQL, feature_writer.py, run_historical_pipeline.py |
| 2 | API routes + zone_engine ATR floor | d231a9de | signals.py, features.py, narrative.py, zone_engine.py, 3 test files |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test mock rows to use new column names**
- **Found during:** Task 2 — unit tests failed with `KeyError: 'i1'` after route update
- **Issue:** Three API test files (`test_features_route.py`, `test_signals_route.py`, `test_narrative_route.py`) had mock row dicts using old column names (`technical_indicators`, `pattern_detections`, etc.)
- **Fix:** Updated `make_mock_row`, `_features_row`, and `_signal_row` helpers to use `i1`/`i3`/`i4`/`i5` keys
- **Files modified:** `tests/unit/api/test_features_route.py`, `tests/unit/api/test_signals_route.py`, `tests/unit/api/test_narrative_route.py`
- **Commit:** d231a9de

## Test Results

- 4614 passed (up from 4610 before Task 2 - 4 newly fixed API tests)
- 43 pre-existing failures (all present before these changes; out of scope)
- 34 skipped, 366 warnings

## Self-Check: PASSED

All 7 key files found. Both task commits verified (7333b334, d231a9de). Zero old column name references in modified files. Migration has exactly 4 RENAME COLUMN statements. Tests: 4614 passed (4 newly fixed).
