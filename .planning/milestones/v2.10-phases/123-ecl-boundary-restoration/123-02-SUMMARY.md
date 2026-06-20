---
phase: "123"
plan: "02"
subsystem: intelligence/trading
tags: [factor_scores, context_features, ecl, i7, signal_schema, wave-b]
dependency_graph:
  requires: ["123-01"]
  provides: ["factor_scores on all I7 setup plugins", "context_features canonical field on all I7 setup plugins"]
  affects: ["signal_events.factor_scores", "signal_events.context_features", "APR weight regression training"]
tech_stack:
  added: []
  patterns:
    - "factor_scores audit dict: pre-composite [0,1] named floats before compose_confidence()"
    - "context_features = features_snapshot: canonical ECL annotation field, same value"
    - "delegation pattern: microstructure_utils.detect_spike_signal() covers ofi_spike + cvd_spike"
key_files:
  created: []
  modified:
    - src/intelligence/trading/trend_following.py
    - src/intelligence/trading/delta_exhaustion.py
    - src/intelligence/trading/microstructure_utils.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/failed_breakout.py
    - src/intelligence/trading/candlestick_pattern_setup.py
    - src/intelligence/trading/session_extremes_setup.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/lvn_breakout.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/vwap_deviation.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/second_leg_continuation.py
    - src/intelligence/trading/vcp.py
    - src/intelligence/trading/dual_divergence.py
    - src/intelligence/trading/mean_reversion.py
    - src/intelligence/trading/supply_demand_setup.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/mtf_alignment.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/fvg_fill.py
    - src/intelligence/trading/pattern_completion.py
    - src/intelligence/trading/divergence_stack.py
    - src/intelligence/trading/regime_transition.py
    - src/intelligence/trading/gap_analysis_setup.py
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/anchored_vwap_reversion.py
    - src/intelligence/trading/poc_rejection.py
    - src/intelligence/trading/hvn_rejection.py
    - src/intelligence/trading/cvd_divergence.py
    - src/intelligence/trading/ofi_continuation.py
    - src/intelligence/trading/cross_asset_divergence.py
    - tests/unit/intelligence/test_i7_extrinsic_contract.py
decisions:
  - "Aggregators (SignalAggregator, RegimeAggregator) are confirmed out of scope: they do not fire setup signals; factor_scores is a per-detection-event field."
  - "ofi_spike and cvd_spike delegate entirely to microstructure_utils.detect_spike_signal(); adding factor_scores there covers both plugins without duplication."
  - "divergence_stack always-log path (base_output) does not receive factor_scores; factor_scores is placed only inside the signal-fire branch to avoid polluting the no-signal return."
  - "supply_demand_setup uses additive confidence; factor_scores captures component contributions (freshness, strength, act123, zone_alignment) rather than factor weights."
  - "choch_reversal and fvg_fill use non-standard confidence formulas; each captures only the single most-significant driving factor."
  - "dual_score in cvd_divergence is gradient-exempt (categorical gate); excluded from factor_scores per APR convention."
  - "Pre-existing lint warnings in gap_analysis_setup, squeeze_expansion, aggregator, lifecycle_tracker etc. are out of scope and deferred."
metrics:
  duration: "resumed from prior session; total wall time > 120 min across two sessions"
  completed: "2026-06-14"
  tasks_completed: 3
  files_modified: 36
---

# Phase 123 Plan 02: Factor Scores + Context Features on All I7 Plugins Summary

Wave B of ECL boundary restoration: all 35 I7 setup plugins now emit `factor_scores` (pre-composite audit dict for APR weight regression) and `context_features` (canonical alias of `features_snapshot` for 3-table signal architecture).

## What Was Built

### Task 1 - factor_scores on 16 Phase-119 plugins (commit 5d1b9bba)

The 16 plugins updated in Plan 01 already had `ctx`/`context_features` from the Wave A pass. This task added the `factor_scores` audit dict to each, placed before the `compose_confidence()` call:

- `microstructure_utils.detect_spike_signal()` - 3 factors (ofi_spike_score, cvd_spike_score, volume_score) - covers ofi_spike + cvd_spike via delegation
- `trend_following.py` - 3 factors (trend_conf_score, trend_strength_score, swing_pattern_score)
- `delta_exhaustion.py` - 4 factors (cvd_z_score, price_fail_score, hmm_mean_reversion_score, persistence_score)
- `ofi_divergence.py` - 4 factors
- `failed_breakout.py` - 4 factors
- `candlestick_pattern_setup.py` - 4 factors
- `session_extremes_setup.py` - 4 factors
- `liquidity_hunt.py` - 4 factors
- `lvn_breakout.py` - 4 factors
- `vwap_reclaim.py` - 4 factors
- `vwap_deviation.py` - 3 factors
- `momentum_breakout.py` - 3 factors
- `orb15.py` - 4 factors
- `orb30.py` - 4 factors
- `second_leg_continuation.py` - 4 factors
- `vcp.py` - 4 factors
- `dual_divergence.py` - 4 factors

### Task 2 - factor_scores + context_features on 19 remaining I7 plugins (commit 367dfb0b)

The non-Phase-119 plugins needed both fields. `context_features` was added by refactoring each from inline `capture_signal_features()` calls to explicit `ctx` variables passed to both `features_snapshot=ctx` and `context_features=ctx`:

- `mean_reversion.py` - 4 factors (rsi_extreme_score, div_score, vol_stability, sr_prox)
- `supply_demand_setup.py` - 4 factors (freshness_score, strength_score, act123_confirmed, zone_alignment_score)
- `liquidity_sweep_reclaim.py` - 3 factors (sweep_depth_score, fvg_confirmed, ob_confirmed)
- `mtf_alignment.py` - 2 factors (ctf_score_raw, ctf_timeframes_aligned_score)
- `squeeze_expansion.py` - 3 factors (squeeze_bars_score, vol_expansion_score, momentum_score)
- `choch_reversal.py` - 1 factor (choch_strength)
- `fvg_fill.py` - 1 factor (magnetism)
- `pattern_completion.py` - 3 factors (pattern_score, strength_score, convergence_score)
- `divergence_stack.py` - 4 factors in signal branch only (base_score, purity_score, breadth_score, persistence_score)
- `regime_transition.py` - 3 factors (cp_probability_score, hmm_aligned_score, choch_detected_score)
- `gap_analysis_setup.py` - 4 factors (geo_score, vol_score, timing_score, type_score)
- `prev_day_level_test.py` - 2 factors (proximity_score, continuation_score)
- `anchored_vwap_reversion.py` - 3 factors (sigma_magnitude, hurst_quality, vol_stability)
- `poc_rejection.py` - 4 factors (proximity_score, reversal_score, vol_score, va_inverse)
- `hvn_rejection.py` - 4 factors (proximity_score, reversal_score, hvn_dist_score, vol_stability)
- `cvd_divergence.py` - 3 factors (div_mag_score, persistence_score, slope_score; dual_score excluded as categorical gate)
- `ofi_continuation.py` - 4 factors (magnitude_score, alignment_score, persistence_score, volume_score)
- `cross_asset_divergence.py` - 3 factors (spread_z_score, pairs_confirming_score, regime_prob_score)

### Task 3 - Contract tests for factor_scores + context_features (commit 86282dcf)

Two new parametrized test functions added to `tests/unit/intelligence/test_i7_extrinsic_contract.py`:

- `test_factor_scores_present_on_fired_signal` - asserts every fireable plugin emits `factor_scores` as a non-empty dict with float values in [0, 1]
- `test_context_features_present_on_fired_signal` - asserts every fireable plugin emits `context_features` as a non-empty dict equal to `features_snapshot`

Both tests parametrize over `_FIREABLE` (plugins with known-good firing scenarios). Plugins where the firing scenario returns `direction=0` are auto-skipped.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] trend_following.py Form 2 inline pattern needed ctx variable**
- Found during: Task 1
- Issue: `signal["features_snapshot"] = capture_signal_features(...)` was inline with no variable to reuse for `context_features`
- Fix: Refactored to explicit `ctx` variable assigned to both `features_snapshot` and `context_features`
- Files modified: `src/intelligence/trading/trend_following.py`
- Commit: 5d1b9bba

**2. [Rule 1 - Bug] E501 violations from factor_scores dict formatting**
- Found during: Tasks 1 and 2 (pre-commit hook blocked commit)
- Issue: Several plugins had lines exceeding 88 characters after adding factor_scores dicts
- Affected: `cvd_divergence.py` (docstring), `divergence_stack.py` (ctx call), `supply_demand_setup.py` (zone_alignment_score expression)
- Fix: Wrapped long lines; shortened docstring in cvd_divergence
- Commits: 367dfb0b (all three within Task 2 commit)

## Deferred Items

Pre-existing lint issues in unrelated files were logged but not fixed:
- `gap_analysis_setup.py`: F841 `entry_type` unused, E501 long comment
- `squeeze_expansion.py`: F841 `bb_upper`, `bb_lower`, `trend_regime` unused variables
- `aggregator.py`, `lifecycle_tracker.py`, `signal_schema.py`, `plugin_utils.py`, `volume_profile_utils.py`: various E501 issues

These are out of scope per deviation Rule 4 boundary (pre-existing, not caused by current task changes).

## Test Results

Unit test suite: 4668 passed, 43 failed, 36 skipped. All 43 failures are pre-existing and unrelated to I7 plugin changes (api route tests, lifecycle tracker, pipeline reset, signal replay auditor). No regressions introduced.

## Self-Check: PASSED

All 7 spot-checked files confirmed present on disk. All 3 task commits confirmed in git log (5d1b9bba, 367dfb0b, 86282dcf).
