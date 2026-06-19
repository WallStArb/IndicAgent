---
phase: 117-patterncompletion-fix-data-pipeline-validation
plan: "01"
subsystem: feature_writer
tags: [bug-fix, data-integrity, persistence, regression-test]
dependency_graph:
  requires: []
  provides: [VAL-01]
  affects: [intelligence_features.pattern_detections, intelligence_features.regime_features, intelligence_features.confluence_scores]
tech_stack:
  added: []
  patterns: [positional-tuple-insert, sentinel-value-regression-test]
key_files:
  modified:
    - services/feature_writer.py
  created:
    - tests/unit/services/test_feature_writer_column_mapping.py
decisions:
  - "Used distinct I5/I3/I4-exclusive sentinel field names (dt_db_confidence, swing_high, garch_sigma) as regression anchors — these fields cannot appear across tier boundaries given extra='forbid' on all three models"
  - "Added cross-contamination test as a fourth assertion layer to catch future schema migrations that might add shared field names"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-08"
  tasks_completed: 2
  files_changed: 2
---

# Phase 117 Plan 01: Feature Writer Column Mapping Fix Summary

**One-liner:** 3-line arg swap correcting i3/i4/i5 positional mismatch in `_record_to_insert_params` — I5Patterns now writes to `pattern_detections`, I3Structure to `regime_features`, I4Context to `confluence_scores`.

## What Was Done

### Task 1: Fix tier-to-column mapping in _record_to_insert_params

The `_record_to_insert_params` function in `services/feature_writer.py` had a 3-way positional argument swap at tuple positions $10/$11/$12. The SQL column order is:

```
$10 = pattern_detections
$11 = regime_features
$12 = confluence_scores
```

But the code passed:
- `event.i3` (I3Structure: swing highs, S/R levels, trend structure) to `pattern_detections`
- `event.i4` (I4Context: GARCH, Kalman, AVWAP, VP) to `regime_features`
- `event.i5` (I5Patterns: dt_db, head-shoulders, triangles) to `confluence_scores`

The fix reorders the three lines so each tier's data reaches its semantically correct column. The tuple length (32), SQL statement, and all other positions ($1-$9, $13-$32) are unchanged.

**Commit:** `291baa02`

### Task 2: Regression test pinning the mapping

Created `tests/unit/services/test_feature_writer_column_mapping.py` with 5 tests:
- `test_column_mapping_i5_lands_in_pattern_detections` - params[9] contains I5 sentinel `dt_db_confidence=0.777`
- `test_column_mapping_i3_lands_in_regime_features` - params[10] contains I3 sentinel `swing_high=99.0`
- `test_column_mapping_i4_lands_in_confluence_scores` - params[11] contains I4 sentinel `garch_sigma=0.0042`
- `test_column_mapping_no_crosscontamination` - I5 key absent from params[10] and params[11]
- `test_record_to_insert_params_returns_32_element_tuple` - tuple length invariant

All 5 tests pass. Tests would fail if the $10/$11/$12 args are swapped back.

**Commit:** `abdf4a1b`

## Verification Results

```
.venv/bin/pytest tests/unit/services/test_feature_writer_column_mapping.py -q
5 passed in 0.52s

.venv/bin/ruff check services/feature_writer.py
All checks passed!

.venv/bin/ruff check tests/unit/services/test_feature_writer_column_mapping.py
All checks passed!
```

## Impact

- `intelligence_features.pattern_detections` now receives I5Patterns data (dt_db_confidence, hs_confidence, tri_confidence, squeeze fields, divergence scores)
- `intelligence_features.regime_features` now receives I3Structure data (swing_high, nearest_resistance, trend structure, session levels, fibonacci zones)
- `intelligence_features.confluence_scores` now receives I4Context data (GARCH, Kalman, AVWAP, volume profile, session context, VIX regime)
- In-process signal generation was never affected (reads `frames["i5"]` directly from pipeline memory, not from DB)
- All downstream analytics on `pattern_detections` (Wave 2 FeatureParityAuditor) are now unblocked

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `services/feature_writer.py` modified: confirmed (291baa02)
- `tests/unit/services/test_feature_writer_column_mapping.py` created: confirmed (abdf4a1b)
- Both commits exist in git log
- 5 tests pass
