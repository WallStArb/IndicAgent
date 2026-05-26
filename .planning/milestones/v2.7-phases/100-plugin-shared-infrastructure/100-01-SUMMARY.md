---
phase: 100-plugin-shared-infrastructure
plan: "01"
subsystem: plugin-infrastructure
tags:
  - plugins
  - shared-utilities
  - wilder-smoothing
  - ema
  - nan-propagation
dependency_graph:
  requires: []
  provides:
    - src.intelligence.plugins.mixins.wilders_update
    - src.intelligence.plugins.mixins.update_ema
    - src.intelligence.plugins.mixins.get_main_df
  affects:
    - src/intelligence/plugins/ (package restructure)
    - all 28 I1 indicator plugins (can adopt wilders_update/update_ema)
tech_stack:
  added: []
  patterns:
    - Pure module-level functions (no class inheritance required)
    - Explicit NaN propagation contract (NaN in -> NaN out)
    - None-return contract for data guard function (never raises)
key_files:
  created:
    - src/intelligence/plugins/__init__.py
    - src/intelligence/plugins/base.py
    - src/intelligence/plugins/mixins.py
    - tests/unit/intelligence/test_plugin_mixins.py
  modified:
    - src/intelligence/plugins.py (removed, converted to package)
decisions:
  - "plugins.py converted to plugins/ package to enable src.intelligence.plugins.mixins import path; __init__.py re-exports all existing names for zero-breakage backward compatibility"
  - "NaN propagation uses separate if-guards per argument (one line each) to satisfy hook grep checks and make the code self-documenting"
  - "get_main_df guards isinstance(df, pd.DataFrame) to handle non-DataFrame main values (list, dict, etc.)"
metrics:
  duration: "~8 minutes"
  completed: "2026-05-21"
  tasks_completed: 2
  files_changed: 4
---

# Phase 100 Plan 01: Plugin Shared Infrastructure - Utility Functions Summary

**One-liner:** Pure utility functions for Wilder's smoothing, EMA updates, and DataFrame extraction with explicit NaN-propagation contracts extracted into a new `src.intelligence.plugins.mixins` module.

## What Was Built

Three pure, module-level utility functions in `src/intelligence/plugins/mixins.py`:

1. `wilders_update(prev, new_val, period)` - Wilder's exponential smoothing, formula `(prev * (period-1) + new_val) / period`. Used by ATR, RSI, ADX, Supertrend, Chandelier, StochRSI, Keltner (7+ plugins with duplicated inline code).

2. `update_ema(current, prev_ema, span)` - Standard EMA update with `alpha = 2/(span+1)`. Used by MACD and other indicator chains.

3. `get_main_df(frames, min_bars)` - Safe extraction of `frames["main"]` DataFrame with length guard. Returns `None` (never raises) when data is insufficient, guarding against non-dict frames, None values, and non-DataFrame entries.

All functions are:
- Pure (no side effects, no state mutation)
- Type-annotated with Python 3.11+ syntax
- Exported via `__all__`
- Documented with NaN contract and usage examples

## Package Restructure

`src/intelligence/plugins.py` was converted to `src/intelligence/plugins/` package:
- `plugins/__init__.py` re-exports all original names (`InputSpec`, `IndicatorPlugin`, `PatternPlugin`, `PluginRegistry`, `registry`) for zero-breakage backward compatibility
- `plugins/base.py` holds the original Protocol classes and PluginRegistry
- `plugins/mixins.py` holds the new utility functions

Python resolves the package over the `.py` file; all 35+ existing `from src.intelligence.plugins import InputSpec` imports continue to work unchanged.

## Tests

40 tests in `tests/unit/intelligence/test_plugin_mixins.py`:
- `TestWildersUpdate` (13 tests): normal case, period=1 edge case, 3 NaN propagation tests, zero values, negative values, 2 ValueError paths, numerical stability, 3 parametrized formula checks
- `TestUpdateEMA` (12 tests): normal case, alpha formula verification, span=1 edge case, 2 NaN propagation tests, 2 ValueError paths, numerical stability, zero values, 3 parametrized formula checks
- `TestGetMainDf` (15 tests): valid return, insufficient bars, missing key, None main, exact boundary, empty DataFrame, None frames, non-dict frames, empty dict, non-DataFrame main, 5 parametrized boundary checks

All 40 tests pass. NaN assertions use `math.isnan()` (not `==`, since `NaN != NaN`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] plugins.py to plugins/ package conversion**

- **Found during:** Task 1 - setting up `src/intelligence/plugins/mixins.py` target path
- **Issue:** `src/intelligence/plugins.py` existed as a flat module file. Python path `src.intelligence.plugins.mixins` requires `plugins` to be a package (directory with `__init__.py`).
- **Fix:** Converted `plugins.py` to a package with `__init__.py` re-exporting all original names (zero-breakage backward compat verified), moved original content to `base.py`.
- **Files modified:** `src/intelligence/plugins/__init__.py` (new), `src/intelligence/plugins/base.py` (renamed from `plugins.py`), removed `src/intelligence/plugins.py`
- **Commit:** d69c7a10
- **Verification:** `from src.intelligence.plugins import InputSpec` still works in all 35+ downstream files

**2. [Rule 3 - Blocking] .venv symlink for pre-commit hook**

- **Found during:** First commit attempt
- **Issue:** Pre-commit hook at `/home/bg/dev/indicagent/.git/hooks/pre-commit` uses `${REPO_ROOT}/.venv/bin/ruff`, where `REPO_ROOT = git rev-parse --show-toplevel` resolves to the worktree root. The worktree has no `.venv`; the main repo's `.venv` is at `/home/bg/dev/indicagent/.venv`.
- **Fix:** Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree root.
- **Files modified:** `.venv` (symlink, not tracked by git)
- **Commit:** N/A (not committed, infrastructure fix)

## Self-Check: PASSED

| Item | Status |
|------|--------|
| `src/intelligence/plugins/mixins.py` | FOUND |
| `src/intelligence/plugins/__init__.py` | FOUND |
| `src/intelligence/plugins/base.py` | FOUND |
| `tests/unit/intelligence/test_plugin_mixins.py` | FOUND |
| `src/intelligence/plugins.py` (removed) | CORRECTLY ABSENT |
| Commit `d69c7a10` feat(100-01) | FOUND |
| Commit `6b454462` test(100-01) | FOUND |
