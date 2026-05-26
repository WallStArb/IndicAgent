---
phase: 093-mathematical-correctness-audit
plan: "01"
subsystem: test-infrastructure
tags:
  - testing
  - correctness
  - pandas-ta
  - fixtures
dependency_graph:
  requires: []
  provides:
    - tests/unit/intelligence/correctness/ (package)
    - assert_close_to_reference helper
    - synthetic OHLCV fixtures
  affects:
    - 093-02-PLAN.md (uses fixtures + helper)
    - 093-03-PLAN.md (uses fixtures + helper)
tech_stack:
  added:
    - pandas-ta>=0.3.14b0 (reference implementation for indicator validation)
  patterns:
    - session-scoped pytest fixtures for deterministic OHLCV data
    - assert helper with warmup_bars parameter for indicator-specific seeding trim
key_files:
  created:
    - tests/unit/intelligence/correctness/__init__.py
    - tests/unit/intelligence/correctness/README.md
    - tests/unit/intelligence/correctness/conftest.py
  modified:
    - requirements.txt
decisions:
  - pandas-ta installed alongside numba 0.61.2 and numpy 2.2.6 (forced downgrade from 0.65.0/2.4.2); all 1783 existing unit tests continue to pass
  - atol default = 1e-6; recursive indicators (MACD, ADX) may use 1e-4 override at call site
  - directional agreement excludes both NaN diffs AND zero diffs from the mask (explicit sign(diff()) semantics)
  - six fixtures cover: trending, ranging, gap, zero-volume, single-bar, flat (convergence)
metrics:
  duration: "~4 minutes"
  completed: "2026-05-21"
  tasks_completed: 2
  files_created: 4
  files_modified: 1
---

# Phase 093 Plan 01: Test Infrastructure for Mathematical Correctness Audit Summary

**One-liner:** pandas-ta reference library installed plus correctness test package with six deterministic OHLCV fixtures and an `assert_close_to_reference` helper enforcing atol=1e-6 and 99.9% directional agreement.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Install pandas-ta and scaffold correctness package | ab5d262c | requirements.txt, correctness/__init__.py, correctness/README.md |
| 2 | Author shared conftest.py with OHLCV fixtures and reference helper | f8d55b21 | correctness/conftest.py |

## What Was Built

### correctness/ Package

`tests/unit/intelligence/correctness/` is now a collectable pytest package. It contains:

- `__init__.py` - Python package marker
- `README.md` - tolerance contract (1e-6 default, 99.9% directional), per-indicator warmup_bars policy (ATR=28, RSI=14, MACD=35, ADX=28, VWAP=0), file layout
- `conftest.py` - shared fixtures and helper functions

### Six Deterministic Fixtures (session-scoped)

| Fixture | Bars | Seed | Purpose |
|---------|------|------|---------|
| `synthetic_ohlcv_trending` | 500 | 42 | Upward drift series for trend indicators |
| `synthetic_ohlcv_ranging` | 500 | 43 | Sine-wave mean-reverting series |
| `synthetic_ohlcv_gap` | 200 | 44 | 5% gap up at bar 100 for discontinuity handling |
| `synthetic_ohlcv_zero_volume` | 100 | 45 | All-zero volume for VWAP/OFI division guard |
| `synthetic_ohlcv_single_bar` | 1 | n/a | Boundary: minimum viable data |
| `synthetic_ohlcv_flat` | 500 | n/a | Constant price for GARCH convergence tests |

All fixtures enforce OHLC validity via `_clamp_ohlcv` (high >= max(open,close), low <= min(open,close)).

### assert_close_to_reference Helper

Signature: `assert_close_to_reference(ours, reference, *, atol=1e-6, directional_min=0.999, warmup_bars=0, name="")`

Key design decisions:
- warmup_bars trims leading bars before comparison to handle seeding differences
- Directional agreement uses explicit `sign(ours.diff()) == sign(ref.diff())` with NaN AND zero diffs excluded
- Fails with diagnostic message: `{name}: max_err={:.2e} (atol={atol}), directional_agreement={:.4f} (min={directional_min})`

### frames_from_ohlcv Helper

Returns `{"main": df}` to wrap a DataFrame in the plugin frames protocol for use with `plugin.compute_full(frames)`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] numpy/numba downgrade from pandas-ta dependency resolution**
- **Found during:** Task 1 (pip install)
- **Issue:** pandas-ta 0.4.71b0 requires numba<=0.62, which conflicts with requirements.txt specifying numba==0.65.0 and numpy>=2.4.0. uv resolved by downgrading numba (0.65.0 -> 0.61.2) and numpy (2.4.2 -> 2.2.6).
- **Fix:** Verified all 1783 existing unit tests still pass after downgrade before proceeding. Recorded in decisions section.
- **Files modified:** none (venv change only)

## Self-Check

### Checking created files exist
- `tests/unit/intelligence/correctness/__init__.py`: FOUND
- `tests/unit/intelligence/correctness/README.md`: FOUND
- `tests/unit/intelligence/correctness/conftest.py`: FOUND

### Checking commits exist
- ab5d262c (Task 1): FOUND
- f8d55b21 (Task 2): FOUND

### Checking verification criteria
- pandas-ta importable: PASSED
- pytest collect on correctness/: no tests collected (expected), no errors
- def count in conftest.py: 10 (>= 8 required)
- warmup_bars occurrences in conftest.py: 7 (>= 2 required)

## Self-Check: PASSED
