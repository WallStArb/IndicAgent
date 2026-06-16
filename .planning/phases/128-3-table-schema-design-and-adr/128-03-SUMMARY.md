---
phase: 128-3-table-schema-design-and-adr
plan: "03"
subsystem: intelligence/trading
tags: [dead-code-removal, confidence-utils, deprecation]
dependency_graph:
  requires: []
  provides: [confidence_utils_cleaned]
  affects: [feature_builder]
tech_stack:
  added: []
  patterns: [dead-code-deletion]
key_files:
  modified:
    - src/intelligence/trading/confidence_utils.py
    - src/intelligence/CLAUDE.md
  deleted:
    - tests/unit/intelligence/trading/test_capture_signal_features.py
decisions:
  - "Deleted test file for deleted function (4740 tests still pass)"
  - "comment-only references in signal_processor.py and feature_builder.py left intact (not call sites)"
metrics:
  duration_minutes: 5
  tasks_completed: 1
  tasks_total: 1
  files_changed: 3
  completed_date: "2026-06-16"
---

# Phase 128 Plan 03: Delete capture_signal_features() Summary

**One-liner:** Deleted deprecated `capture_signal_features()` (101 lines) from `confidence_utils.py` after pre-flight audit confirmed zero live callers; updated CLAUDE.md reference and deleted orphaned test file.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Pre-flight audit and delete capture_signal_features() | 408197ba | confidence_utils.py, CLAUDE.md, test_capture_signal_features.py (deleted) |

## What Was Done

### Pre-flight Audit

```
grep -rn "capture_signal_features(" src/ --include="*.py"
```

Results:
- `src/intelligence/trading/confidence_utils.py:174` - function definition (deleted)
- `src/intelligence/trading/confidence_utils.py:10` - module docstring reference (deleted)
- `src/intelligence/pipeline/signal_processor.py:85` - comment only: "No plugin may call capture_signal_features()" - left intact
- `src/intelligence/ml/feature_builder.py:34` - comment only: "25 keys verbatim from confidence_utils.py capture_signal_features()" - left intact

Zero live callers confirmed. Safe to delete.

`SHADOW_FEATURE_KEYS` in `feature_builder.py` confirmed as a standalone constant tuple (not a call).

### Changes Made

1. **`src/intelligence/trading/confidence_utils.py`** - Deleted:
   - Module docstring paragraph describing `capture_signal_features()` (lines 10-20 before edit)
   - The full `capture_signal_features()` function definition (101 lines)
   - Preserved: all remaining exports (`compose_confidence`, `CONF_CEIL`, `MIN_REGIME_WEIGHT`, `MIN_CTF_SCORE`, `ConfluenceWeightProfile`, `FAMILY_PROFILES`, `_nullable_float`, `rel_volume_score`, `_validate_weights_sum`, `clamp01`, `set_config_service`, `get_min_regime_weight`, `get_min_ctf_score`)
   - `Any` import retained (still used by `_config_service: Any | None`, `set_config_service`, `rel_volume_score`)

2. **`src/intelligence/CLAUDE.md`** - Updated the shared utilities table row for `confidence_utils.py`:
   - Removed `capture_signal_features()` from Key exports column
   - Removed shadow dict description sentence

3. **`tests/unit/intelligence/trading/test_capture_signal_features.py`** - Deleted (tested the now-deleted function; 267 lines, 14 test functions)

### Verification

```
grep "def capture_signal_features" src/intelligence/trading/confidence_utils.py
# -> no output (CORRECT: function deleted)

python -c "from src.intelligence.trading.confidence_utils import compose_confidence, CONF_CEIL, MIN_REGIME_WEIGHT, MIN_CTF_SCORE; print('imports OK')"
# -> imports OK

pytest tests/unit/ -q
# -> 4740 passed, 37 skipped
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Deleted orphaned test file for deleted function**
- **Found during:** Task 1, verification step
- **Issue:** `tests/unit/intelligence/trading/test_capture_signal_features.py` imported `capture_signal_features` from `confidence_utils.py` - pytest collection would fail immediately after function deletion
- **Fix:** Deleted the test file (14 test functions, all testing the now-deleted function)
- **Files modified:** `tests/unit/intelligence/trading/test_capture_signal_features.py` (deleted)
- **Commit:** 408197ba

## Self-Check: PASSED

- confidence_utils.py exists: FOUND
- CLAUDE.md exists: FOUND
- test_capture_signal_features.py deleted: CONFIRMED
- commit 408197ba exists: CONFIRMED
