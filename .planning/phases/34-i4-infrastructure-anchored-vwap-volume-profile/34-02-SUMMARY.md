---
phase: 34
plan: 02
subsystem: intelligence/context
tags: [volume-profile, i4-context, migration, poc, value-area, hvn-lvn]
dependency_graph:
  requires: [34-01]
  provides: [ctx_VolumeProfile in TIER_I4 with 18 output fields]
  affects: [I4Context schema, TIER_I4, TIER_I5, downstream I7 plugins in Plan 03]
tech_stack:
  added: []
  patterns: [dual-track session/rolling histogram, 70% cumulative volume rule, directional node detection]
key_files:
  created:
    - src/intelligence/context/volume_profile.py
    - tests/unit/intelligence/context/test_volume_profile.py
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/register_plugins.py
    - tests/unit/intelligence/test_i5_new_plugins.py
  deleted:
    - src/intelligence/patterns/volume_profile.py
decisions:
  - "Plugin lookback set to 390 bars (full session on 1m) to support session-reset track"
  - "Rolling window is 480 bars (8h on 1m) — continuous rolling regardless of session"
  - "in_lvn and nearest_hvn_dist_atr preserved unchanged for I7 plugin backward compat"
  - "Session track falls back to full df when before 09:30 ET or no timestamps"
metrics:
  duration_seconds: 376
  tasks_completed: 1
  tasks_total: 1
  files_created: 2
  files_modified: 3
  files_deleted: 1
  completed_date: "2026-03-17"
---

# Phase 34 Plan 02: VolumeProfile I4 Migration Summary

VolumeProfile plugin migrated from I5/patterns/ to I4/context/ with dual-track session+rolling computation, POC/VAH/VAL via 70% cumulative volume rule, and directional HVN/LVN fields. 18 total output fields (4 legacy preserved + 14 new).

## What Was Built

### ctx_VolumeProfile Plugin (`src/intelligence/context/volume_profile.py`)

**Session track** (resets at 09:30 ET each day):
- Filters df to bars since NY open using `_extract_ts` / `_et_from_utc` from session_context
- Computes volume-weighted histogram over session bars
- POC/VAH/VAL via 70% cumulative volume rule
- Directional HVN: `nearest_hvn_above`, `nearest_hvn_below`
- Directional LVN: `nearest_lvn_above`, `nearest_lvn_below`
- Value area context: `price_in_value_area`, `va_width_atr`, `distance_to_vah_atr`, `distance_to_val_atr`

**Rolling track** (last min(480, N) bars):
- Continuous 480-bar window regardless of session boundaries
- Outputs: `poc_price_rolling`, `vah_rolling`, `val_rolling`

**Legacy fields (backward compat)**:
- `nearest_hvn_level` — nearest HVN regardless of direction
- `nearest_hvn_dist_atr` — distance to nearest HVN in ATR units
- `nearest_lvn_level` — nearest LVN regardless of direction
- `in_lvn` — 1.0 if current bucket is a low-volume node, 0.0 otherwise

### Schema Changes (`src/intelligence/schemas.py`)

- **I4Context**: +18 VP fields (now 93 total, was 75)
- **I5Patterns**: -4 VP fields removed (now 75 total, was 79)

### Registry Changes (`src/intelligence/register_plugins.py`)

- Import updated: `.patterns.volume_profile` → `.context.volume_profile`
- `validate_schema_coverage()`: VP plugin moved from I5 check to I4 check
- `TIER_I4`: +`ctx_VolumeProfile` (now 11 plugins)
- `TIER_I5`: -`patt_VolumeProfile` (now 15 plugins)

## Tests

- 24 new tests in `tests/unit/intelligence/context/test_volume_profile.py` — all pass
- 10 existing registry/I5 tests updated — all pass
- 1250 unit tests pass total (excluding 1 pre-existing unrelated failure in test_setup_performance_updater)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated import paths in test_i5_new_plugins.py**
- **Found during:** Task 1 verification
- **Issue:** `test_i5_new_plugins.py` still imported `src.intelligence.patterns.volume_profile` (deleted file) and checked for `patt_VolumeProfile` in TIER_I5 with count=16
- **Fix:** Updated 3 imports to `context.volume_profile`, removed `patt_VolumeProfile` from membership check set, updated count assertion from 16 to 15, added new `test_volume_profile_in_tier_i4` test
- **Files modified:** `tests/unit/intelligence/test_i5_new_plugins.py`
- **Commit:** 4f1798f

### Out-of-scope Pre-existing Failure

`test_setup_performance_updater.py::TestWindowAndNullHandling::test_compute_setup_performance_30day_window` was already failing before this plan (confirmed by git stash verification). Unrelated to VP migration.

## Self-Check: PASSED

- src/intelligence/context/volume_profile.py: FOUND
- tests/unit/intelligence/context/test_volume_profile.py: FOUND
- src/intelligence/patterns/volume_profile.py: CONFIRMED DELETED
- Commit e20e391 (RED test): FOUND
- Commit 4f1798f (GREEN implementation): FOUND
- 1250 unit tests pass
