---
phase: 116-sr-consensus
plan: "01"
subsystem: intelligence/i3-structure
tags:
  - support-resistance
  - atr-proportional
  - clustering
  - pivot-detection
  - volume-weighted

dependency_graph:
  requires:
    - src/intelligence/trading/atr_utils.py (get_atr)
    - src/intelligence/utils (find_peaks, find_troughs)
  provides:
    - ATR-proportional SR clustering for five I7 stop/target anchor plugins
    - Sparse output semantics (absent keys when no real pivot)
  affects:
    - All I7 plugins consuming nearest_resistance / nearest_support

tech_stack:
  added: []
  patterns:
    - Sparse dict output (absent key = no data; do not use None sentinel)
    - TF-proportional lookback table (_LOOKBACK_BY_TF)
    - ATR-proportional cluster radius from i1 sub-dict

key_files:
  modified:
    - src/intelligence/features/i3_structure/support_resistance.py
    - tests/unit/intelligence/test_sr_shared_peaks.py

decisions:
  - "Cluster radius is ATR-proportional (atr_14 * 0.5), not fixed percentage — eliminates merging distinct ES pivots at 0.5% (37pts on ES@7400)"
  - "Synthetic fallback (price*0.98 / price*1.02) removed; phantom levels polluted stop/target anchors for five I7 plugins"
  - "age_bars relative to TF-proportional window (post-slice n_bars), not the full incoming frame"
  - "Volume-weighted strength with 2x cap: len(members) * mean(min(2.0, vol/mean_vol)); degrades to count-only when volume unavailable"

metrics:
  duration_minutes: 8
  completed_date: "2026-06-05"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 116 Plan 01: SR Plugin Hardening Summary

ATR-proportional clustering with TF-proportional lookback, volume-weighted pivot strength, and killed synthetic fallback in `struct_SupportResistance` (I3).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | ATR clustering + TF lookback + vol-weighted strength + kill synthetic fallback | fb99c249 | support_resistance.py |
| 2 | Update tests: deterministic fixtures, no-pivot case, sparse output semantics | 1c59897b | test_sr_shared_peaks.py |

## What Changed

### support_resistance.py

- `cluster_pct: float = 0.005` dataclass field removed; replaced with `cluster_atr_mult: float = 0.5`
- `_LOOKBACK_BY_TF` module-level constant: `{"1m": 60, "5m": 60, "15m": 80, "1h": 120, "4h": 120, "1d": 60}`; fallback 120 for unknown TF
- `df.iloc[-lookback:]` applied in `compute_full` before array extraction; `n_bars = len(df)` set post-slice so age is window-relative
- `get_atr(frames.get("i1") or {})` reads ATR from i1 sub-dict; fallback to `current_price * 0.005` only when i1 absent (malformed frame)
- Volume extracted from df with guard; `mean_volume` computed before clustering
- `_cluster_levels` signature extended with `atr_14, volume, mean_volume`; cluster radius = `atr_14 * cluster_atr_mult` when ATR available
- `_finalize_cluster` computes volume-weighted strength: `len(members) * mean(min(2.0, vol_ratio))`; degrades to count-only when `volume is None`
- Synthetic fallbacks removed: `nearest_r` and `nearest_s` are `None` when no real pivot exists
- Return block builds sparse `result` dict: `sr_level_count` always present; all other keys absent when no real pivot

### test_sr_shared_peaks.py

- Replaced random-walk `_make_ohlcv` with deterministic `_make_ohlcv_with_pivots` (explicit pivot placement at known bar indices)
- Added `_make_frames` helper that injects `"i1"` and `"timeframe"` keys to exercise the new ATR/lookback path
- Updated `test_outputs_all_expected_keys`: asserts `sr_level_count` present; all other keys guarded by `if key in result`
- Updated `test_resistance_above_price` and `test_support_below_price`: conditional assertions
- Added `test_no_synthetic_fallback`: confirms both keys absent and no phantom `price*0.98` / `price*1.02` values
- Added `test_sparse_output_semantics`: confirms `nearest_resistance` key is absent (not None) when only support pivot in window
- Added `test_age_bars_relative_to_sliced_window`: pivot outside 60-bar slice yields absent support; pivot inside slice yields age_bars <= 60

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_make_ohlcv_with_pivots` crashed for n < 91 (test_short_data_returns_empty)**
- Found during: Task 2
- Issue: Unconditional bar-80 and bar-10 assignments in the fixture helper raised `IndexError` when called with `n=20`
- Fix: Guarded pivot injection with `if n >= 91` (resistance) and `if n >= 21` (support)
- Files modified: tests/unit/intelligence/test_sr_shared_peaks.py
- Commit: 1c59897b (included in Task 2 commit)

**2. [Rule 1 - Bug] `test_sparse_output_semantics` pivot outside TF slice**
- Found during: Task 2
- Issue: Support pivot placed at bar 10 of 120-bar array was outside the 60-bar TF slice (bars 60-119); `find_troughs` never detected it; `nearest_support` absent when test expected present
- Fix: Moved pivot to bar 70 (within the last-60 slice) by centering the local low window around bars 65-75
- Files modified: tests/unit/intelligence/test_sr_shared_peaks.py
- Commit: 1c59897b (included in Task 2 commit)

## Verification

```
pytest tests/unit/intelligence/test_sr_shared_peaks.py -q
7 passed in 0.28s

ruff check src/intelligence/features/i3_structure/support_resistance.py
All checks passed!

grep "current_price \* 0.98\|current_price \* 1.02\|cluster_pct" support_resistance.py
(no matches)
```

## Self-Check: PASSED

- [x] `src/intelligence/features/i3_structure/support_resistance.py` exists and contains `cluster_atr_mult`, `_LOOKBACK_BY_TF`, `get_atr`
- [x] `tests/unit/intelligence/test_sr_shared_peaks.py` exists and contains `test_no_synthetic_fallback`, `test_sparse_output_semantics`, `test_age_bars_relative_to_sliced_window`
- [x] Commit fb99c249 exists (Task 1)
- [x] Commit 1c59897b exists (Task 2)
- [x] All 7 tests pass
- [x] No synthetic phantom values in plugin code
