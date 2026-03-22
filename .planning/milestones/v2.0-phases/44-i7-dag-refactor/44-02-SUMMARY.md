---
phase: 44-i7-dag-refactor
plan: "02"
subsystem: intelligence/trading
tags: [i7-plugins, refactor, dag, utilities, i2-composites]
dependency_graph:
  requires: [44-01]
  provides: [44-03, 44-04]
  affects: [src/intelligence/trading/*.py, src/intelligence/composites/*.py]
tech_stack:
  added: []
  patterns:
    - "get_atr() replaces inline ATR fallback across 28 I7 plugins"
    - "compose_confidence() standardises [0.10, 0.95] confidence range"
    - "no_signal() replaces _no_signal() staticmethod on every plugin"
    - "composites/common.py is now a re-export shim; utils/common.py is source of truth"
key_files:
  modified:
    - src/intelligence/trading/trend_following.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/mtf_alignment.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/vwap_deviation.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/supply_demand_setup.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/regime_transition.py
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/candlestick_pattern_setup.py
    - src/intelligence/trading/session_extremes_setup.py
    - src/intelligence/trading/failed_breakout.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/second_leg_continuation.py
    - src/intelligence/trading/vcp.py
    - src/intelligence/trading/anchored_vwap_reversion.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/poc_rejection.py
    - src/intelligence/trading/hvn_rejection.py
    - src/intelligence/trading/lvn_breakout.py
    - src/intelligence/composites/common.py
    - src/intelligence/composites/exhaustion_score.py
    - src/intelligence/composites/derivative_oscillator.py
    - src/intelligence/composites/rsi_events.py
    - src/intelligence/composites/stochastic_events.py
    - src/intelligence/composites/acceleration_regime.py
    - src/intelligence/composites/ma_composites.py
    - src/intelligence/composites/volume_events.py
    - src/intelligence/composites/momentum_accel.py
    - src/intelligence/composites/macd_events.py
    - src/intelligence/composites/adx_events.py
    - tests/unit/intelligence/test_cis_plugins.py
    - tests/unit/intelligence/test_gap_analysis_setup.py
    - tests/unit/intelligence/test_plugin_registry.py
    - tests/unit/intelligence/trading/test_candlestick_pattern_setup.py
decisions:
  - "VWAP/POC/HVN/LVN/AnchoredVWAP plugins intentionally retain round(min(1.0,max(0.0,...))) — [0,1] confidence range, not replaced with compose_confidence()"
  - "session_extremes_setup.py retains return {} for insufficient data to preserve test expectations"
  - "composites/common.py kept as backward-compat re-export shim — no callers removed until Phase 04"
metrics:
  duration_minutes: 90
  completed_date: "2026-03-20"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 42
---

# Phase 44 Plan 02: I7 Plugin Utility Wiring + I2 Composite Migration Summary

Wire all 28 non-microstructure I7 plugins to shared utilities (get_atr, compose_confidence, no_signal, extract_ohlcv) and migrate all 10 I2 composite plugins to import from utils/common, converting composites/common.py into a re-export shim.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Wire 28 I7 plugins to shared utilities | 86f53b0 | 31 files |
| 2 | Migrate I2 composites to utils/common | eaec11c | 11 files |

## What Was Built

### Task 1: I7 Plugin Utility Wiring

Applied 5 mechanical transformations across all 28 non-microstructure I7 plugins:

1. **`_no_signal()` → `no_signal()`**: Removed the per-plugin `@staticmethod def _no_signal()` method from every plugin; replaced all `self._no_signal()` calls with the imported `no_signal()` function from `plugin_utils`.

2. **Inline ATR fallback → `get_atr()`**: Removed `np.mean(high[-14:] - low[-14:])` inline fallback patterns. All ATR reads now route through `atr_utils.get_atr(features)` which returns `None` if `atr_14` is missing or invalid.

3. **Confidence clamping → `compose_confidence()`**: Replaced `round(min(0.95, max(0.10, raw)), 4)` with `compose_confidence(raw)` for the 15 standard-range plugins. Five plugins (AnchoredVWAPReversion, VWAPReclaim, POCRejection, HVNRejection, LVNBreakout) intentionally use `round(min(1.0, max(0.0, ...)))` — their [0,1] range is by design and was preserved.

4. **OHLCV extraction → `extract_ohlcv()`**: Applied to the plugins that used OHLCV arrays only for ATR computation; plugins that legitimately process high/low/close data for bar-range calculations (e.g. VCP, ORB15, ORB30) retain their array access.

5. **`numpy` import removal**: Removed `import numpy as np` from plugins that only used it for the inline ATR fallback (and had no other numpy usage).

Microstructure exclusions (per constraint D-31): ofi_continuation, ofi_divergence, ofi_spike, cvd_divergence, cvd_spike, delta_exhaustion, dual_divergence, cross_asset_divergence — these retain their own patterns.

### Task 2: I2 Composite Import Migration

Updated all 10 I2 composite plugins to import from `..utils.common` instead of the tier-local `.common`:

- exhaustion_score, derivative_oscillator, rsi_events, stochastic_events, acceleration_regime, ma_composites, volume_events, momentum_accel, macd_events, adx_events

Converted `composites/common.py` into a re-export shim that forwards to `utils/common.py`. The shim is kept for backward compatibility; no callers are removed until Plan 04 decides to delete it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test assertions assumed `{}` for insufficient-data paths**
- **Found during:** Task 1 (gap_analysis_setup.py, candlestick_pattern_setup.py)
- **Issue:** After applying `extract_ohlcv()`, insufficient data returns `no_signal()` dict `{"signal_type": "none", "direction": 0, "confidence": 0.0}` instead of `{}`. Two tests asserted `result == {}`.
- **Fix:** Updated tests to assert `result["signal_type"] == "none"` and `result["direction"] == 0`
- **Files modified:** `tests/unit/intelligence/test_gap_analysis_setup.py`, `tests/unit/intelligence/trading/test_candlestick_pattern_setup.py`
- **Commit:** 86f53b0

**2. [Rule 1 - Bug] PatternCompletion / RegimeTransition tests missing atr_14 in fixtures**
- **Found during:** Task 1
- **Issue:** After removing inline ATR fallback, these plugins now call `get_atr(features)` which returns `None` if `atr_14` is absent, causing `no_signal()` to fire in tests that expected a signal.
- **Fix:** Added `"atr_14": 10.0` to 8 test features dicts in `test_cis_plugins.py`
- **Files modified:** `tests/unit/intelligence/test_cis_plugins.py`
- **Commit:** 86f53b0

**3. [Rule 1 - Bug] Plugin registry test expected 35 plugins, TIER_I7 has 36**
- **Found during:** Task 1 verification
- **Issue:** `test_tier_i7_has_35_plugins` was stale — CrossAssetDivergence had been added to TIER_I7 in a prior session, making the total 36.
- **Fix:** Updated test name and assertion to `== 36`
- **Files modified:** `tests/unit/intelligence/test_plugin_registry.py`
- **Commit:** 86f53b0

## Known Stubs

None — all transformations are mechanical rewires with no stub values.

## Test Results

Final: **1570 passed, 3 failed** (pre-existing failures unrelated to this plan):
- `test_setup_performance_updater.py::test_compute_setup_performance_30day_window` — sample_size returns 55 vs expected 30
- `test_weight_updater.py::test_cluster_training_100_signals`
- `test_weight_updater.py::test_global_model_trained_when_enough_signals`

All 3 failures confirmed pre-existing via `git stash && pytest && git stash pop` before Plan 02 work began.

## Self-Check: PASSED
