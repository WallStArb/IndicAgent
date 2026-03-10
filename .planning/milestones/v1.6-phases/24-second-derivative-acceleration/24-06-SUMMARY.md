---
phase: 24-second-derivative-acceleration
plan: "06"
subsystem: intelligence/indicators
tags: [hma, plugin-registration, tier-i1, gap-closure]
dependency_graph:
  requires: [24-01, 24-02, 24-03, 24-04, 24-05]
  provides: [hma_20 live in features dict, hma_slope/hma_accel non-zero, AccelerationRegime 4-vote active]
  affects: [market_analysis_service I1 pipeline, AccelerationRegime I2, ExhaustionScore I2]
tech_stack:
  added: []
  patterns: [plugin-registration, tier-list-as-source-of-truth]
key_files:
  created: []
  modified:
    - src/intelligence/register_plugins.py
    - src/intelligence/indicators/hma.py
    - tests/unit/intelligence/test_plugin_registry.py
    - tests/unit/intelligence/test_i7_registration.py
decisions:
  - "HMAPlugin registered as 25th I1 indicator — gap was silently zeroing hma_slope and hma_accel"
  - "pandas import removed from hma.py — only numpy was ever used"
metrics:
  duration: "~10 min"
  completed: "2026-03-10"
  tasks_completed: 2
  files_modified: 4
---

# Phase 24 Plan 06: Register HMAPlugin in TIER_I1 Summary

**One-liner:** Wired HMAPlugin into TIER_I1 and register_plugins.py so hma_20 flows live each bar, enabling hma_slope and hma_accel to carry real values in AccelerationRegime's 4-vote count.

## What Was Built

HMAPlugin was fully implemented and tested in phase 24-02 but was never registered. This gap closure plan makes three surgical additions to register_plugins.py:

1. Import `from .indicators.hma import plugin as hma_plugin` (alphabetical, after hv_plugin)
2. `registry.register_indicator(hma_plugin)` in `register_all_plugins()`
3. `hma_plugin.name` appended to `TIER_I1` list (24 → 25 entries)

Additionally removed the unused `import pandas as pd` from hma.py that would have caused a ruff F401 warning.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register HMAPlugin in TIER_I1 | 02896dc | src/intelligence/register_plugins.py |
| 2 | Remove pandas import; fix count test | e5480bc | src/intelligence/indicators/hma.py, tests/unit/intelligence/test_plugin_registry.py |

## Verification

- `len(TIER_I1) == 25` and `'HMA' in TIER_I1` — confirmed
- `test_tier_i1_has_25_plugins` passes
- Full unit suite: 1482 passed, 0 failed
- `ruff check` on touched files: all checks passed

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_total_plugin_count expected 95, needed 96**
- **Found during:** Task 2 verification (full unit suite run)
- **Issue:** `tests/unit/intelligence/test_i7_registration.py::test_total_plugin_count` asserted total == 95 (24 indicators + 71 patterns). Adding HMAPlugin brought indicators to 25, making the correct total 96.
- **Fix:** Updated assertion from 95 to 96 and updated docstring comment
- **Files modified:** tests/unit/intelligence/test_i7_registration.py
- **Commit:** 2e39a94

## Self-Check: PASSED

All modified files exist. All task commits verified in git log.
