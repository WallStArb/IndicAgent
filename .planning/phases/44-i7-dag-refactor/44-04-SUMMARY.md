---
phase: 44-i7-dag-refactor
plan: "04"
subsystem: intelligence/trading
tags: [microstructure, signal-schema, type-contracts, validation, prometheus]
dependency_graph:
  requires: [44-02, 44-03]
  provides: [DAG-01, DAG-02, DAG-03, DAG-04]
  affects: [signal_generator_service, ofi_plugins, cvd_plugins, delta_exhaustion, dual_divergence, cross_asset_divergence]
tech_stack:
  added: []
  patterns: [make_signal factory, validate_signal gate, frame_trade for stops/targets, compose_confidence, plugin_utils.no_signal]
key_files:
  created: []
  modified:
    - src/intelligence/trading/ofi_spike.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/ofi_continuation.py
    - src/intelligence/trading/cvd_spike.py
    - src/intelligence/trading/cvd_divergence.py
    - src/intelligence/trading/delta_exhaustion.py
    - src/intelligence/trading/dual_divergence.py
    - src/intelligence/trading/cross_asset_divergence.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/trading/test_ofi_plugins.py
    - tests/unit/intelligence/trading/test_cvd_plugins.py
    - tests/unit/intelligence/trading/test_dual_divergence.py
    - tests/unit/intelligence/test_cross_asset_divergence.py
decisions:
  - "make_signal() called in _run_setup_plugins() after passing symbol/timeframe/timestamp via extended signature"
  - "SIGNAL_VALIDATION_FAILURES uses raw prometheus_client.Counter with labels (project helper doesn't support labels)"
  - "cross_asset_divergence supporting_factors converted from dict to list[str] to match signal.v1 contract"
  - "delta_exhaustion ATR fallback from df removed — now requires atr_14 in features (degrade gracefully via get_atr)"
metrics:
  duration: "681s"
  completed: "2026-03-21"
  tasks_completed: 2
  files_modified: 13
---

# Phase 44 Plan 04: Microstructure Type Contracts + Signal Validation Summary

Fix type contract violations in all 8 microstructure I7 plugins and wire `make_signal()` as the single signal construction factory in `signal_generator_service`, with `validate_signal()` enforcement on every signal pre-aggregation.

## What Was Built

**Task 1 — Fix type contracts in all 8 microstructure plugins:**

All 7 OFI/CVD/delta/dual plugins had `stop_loss: None`, `targets: None`, `regime_context: dict` in their signal output. Cross-asset had non-standard field names (`entry`/`stop`/`target_1/2/full` instead of `entry_price`/`stop_loss`/`targets`) and `supporting_factors` as a dict.

Applied the same utility adoptions from Plan 02 to all 8 plugins:
- `frame_trade()` for stops and targets — `stop_loss = float(tf.stop)`, `targets = [t.price for t in tf.targets]`
- `get_atr()` from `atr_utils` — required guard before `frame_trade()` call
- `compose_confidence()` from `confidence_utils` — replaces inline `min/max` clamping
- `no_signal()` from `plugin_utils` — replaces `_no_signal()` static method
- `signal_type_for_direction()` from `plugin_utils` — replaces inline ternary

All 8 plugins now return:
- `stop_loss: float` (not None)
- `targets: list[float]` (non-empty)
- `regime_context: str` (`f"hmm_{hmm_regime}"` or `"any"`)

**Task 2 — Wire make_signal() factory + validate_signal() enforcement:**

`_run_setup_plugins()` signature extended with `symbol`, `timeframe`, `timestamp`, `ttl_bars` parameters. The signal construction path now:
1. Calls `make_signal()` for every firing plugin (D-29) — single construction point
2. On `KeyError`/`TypeError`: logs ERROR + increments `SIGNAL_VALIDATION_FAILURES` counter + continues
3. Calls `validate_signal()` on every constructed signal (D-30)
4. On validation failure: logs ERROR with full signal dict + increments counter + drops signal (never reaches aggregator, D-18)

`SIGNAL_VALIDATION_FAILURES` is a `prometheus_client.Counter` with `plugin` label (not the project helper `counter()` which doesn't support labels).

TTL is now injected at construction time (passed to `make_signal()`) instead of mutated post-construction.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 9dc48cf | Fix type contracts in all 8 microstructure plugins |
| 2 | fa0f53f | Wire make_signal() factory + validate_signal() enforcement |

## Test Coverage

- `test_ofi_plugins.py`: Updated with `atr_14` in features + type contract assertions (stop_loss float, targets list[float], regime_context str)
- `test_cvd_plugins.py`: Same updates
- `test_dual_divergence.py`: Updated with `atr_14`, type assertions, replaced `_no_signal` static method test
- `test_cross_asset_divergence.py`: Updated to match standardized field names (`entry_price`/`stop_loss`/`targets`/`list[str] supporting_factors`)

All 1570 intelligence unit tests pass. The 3 pre-existing failures (`test_compute_setup_performance_30day_window`, `test_cluster_training_100_signals`, `test_global_model_trained`) are unrelated to this plan and were failing before execution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] cross_asset_divergence supporting_factors was dict (not list[str])**
- **Found during:** Task 1 review
- **Issue:** `supporting_factors` returned as `dict[str, Any]` instead of `list[str]` — incompatible with validate_signal() and signal.v1 schema
- **Fix:** Converted to `list[str]` with `f"key=value"` format strings
- **Files modified:** `src/intelligence/trading/cross_asset_divergence.py`
- **Test updates:** `tests/unit/intelligence/test_cross_asset_divergence.py` updated to assert list format

**2. [Rule 1 - Bug] cross_asset_divergence output field names non-standard**
- **Found during:** Task 1 review
- **Issue:** Plugin returned `entry`/`stop`/`target_1/2/full` instead of standard `entry_price`/`stop_loss`/`targets` — incompatible with make_signal()
- **Fix:** Standardized to `entry_price`/`stop_loss`/`targets` (list[float]) + added `regime_context: str`
- **Files modified:** `src/intelligence/trading/cross_asset_divergence.py`, `outputs` frozenset updated
- **Commit:** 9dc48cf

**3. [Rule 1 - Bug] cross_asset_divergence missing atr <= 0 guard**
- **Found during:** Task 1 review of atr handling
- **Issue:** Original code passed `atr=0.0` to `frame_trade()` which would produce nonsensical stops
- **Fix:** Added `if atr <= 0: return no_signal()` guard before `frame_trade()` call
- **Files modified:** `src/intelligence/trading/cross_asset_divergence.py`

**4. [Rule 1 - Bug] delta_exhaustion ATR fallback from df OHLCV removed**
- **Found during:** Task 1 — delta_exhaustion previously computed ATR from `high[-14:] - low[-14:]` when `atr_14` missing
- **Issue:** Plan D-05/D-06/D-07 specifies ATR is computed once in I1 — plugins must not recompute. Old fallback bypassed the `get_atr()` contract.
- **Fix:** Replaced fallback computation with `get_atr()` → `no_signal()` if None (degrade gracefully per D-07)
- **Impact:** Test `test_no_signal_when_atr_missing` required assertion update (df OHLCV fallback no longer works)

## Known Stubs

None. All type contracts are now enforced. `stop_loss`, `targets`, and `regime_context` are real computed values in all 8 plugins.

## Self-Check: PASSED

- src/intelligence/trading/ofi_spike.py: FOUND
- src/intelligence/trading/cross_asset_divergence.py: FOUND
- .planning/phases/44-i7-dag-refactor/44-04-SUMMARY.md: FOUND
- Commit 9dc48cf: FOUND
- Commit fa0f53f: FOUND
