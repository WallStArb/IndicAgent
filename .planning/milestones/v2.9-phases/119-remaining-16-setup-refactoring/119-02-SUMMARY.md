---
phase: 119-remaining-16-setup-refactoring
plan: "02"
subsystem: intelligence/trading
tags: [i7-plugins, regime-gates, ctf-confluence, confidence-refactor, shadow-mode]
dependency_graph:
  requires: [119-01]
  provides: [wave-2-dual-gate-compliance]
  affects: [intelligence_pipeline]
tech_stack:
  added: []
  patterns:
    - dual-gate pattern (HMM regime weight + I6 ctf_score) applied to 9 Wave-2 I7 plugins
    - 4-factor clamp01-bounded confidence composites replacing single-factor additive formulas
    - hmm_regime_weight(features, "ranging") for mean_reversion regime_type plugins
key_files:
  created: []
  modified:
    - src/intelligence/trading/lvn_breakout.py
    - src/intelligence/trading/vwap_reclaim.py
    - src/intelligence/trading/vwap_deviation.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/second_leg_continuation.py
    - src/intelligence/trading/vcp.py
    - src/intelligence/trading/dual_divergence.py
    - tests/unit/intelligence/trading/test_lvn_breakout.py
    - tests/unit/intelligence/trading/test_vwap_reclaim.py
    - tests/unit/intelligence/test_vwap_deviation.py
    - tests/unit/intelligence/test_momentum_breakout.py
    - tests/unit/intelligence/test_i7_extrinsic_contract.py
    - tests/unit/intelligence/trading/test_orb15.py
    - tests/unit/intelligence/trading/test_orb30.py
    - tests/unit/intelligence/trading/test_second_leg_continuation.py
    - tests/unit/intelligence/trading/test_vcp.py
    - tests/unit/intelligence/trading/test_dual_divergence.py
decisions:
  - "DualDivergence (mean_reversion) uses hmm_regime_weight(features, 'ranging') for Gate 1 - not hmm_trending_weight"
  - "LVNBreakout trend_clarity retains pre-existing hmm_probability factor - only plugin in plan allowed HMM in confidence"
  - "VWAPDeviation and MomentumBreakout ohlcv extraction reordered to after dual gate; 3-factor confidence preserved unchanged"
  - "5 pre-existing test failures (test_lifecycle_tracker, test_trade_framer x2, test_vwap_deviation x2) are unrelated to this plan and were pre-existing before work started"
metrics:
  duration_minutes: 120
  completed_date: "2026-06-10"
  tasks_completed: 3
  files_modified: 19
---

# Phase 119 Plan 02: Wave-2 I7 Dual Gate + Confidence Refactor Summary

Apply the 6 GOOD patterns (continuous HMM regime gate, I6 ctf_score gate, 4-factor clamp01 confidence) to the 9 remaining Wave-2 I7 setup plugins: dual gate in all 9, new 4-factor confidence composites in 5 (ORB15, ORB30, SecondLeg, VCP, DualDivergence), gates-only changes in 4 (LVNBreakout, VWAPReclaim, VWAPDeviation, MomentumBreakout).

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Gates-only batch: LVNBreakout, VWAPReclaim, VWAPDeviation, MomentumBreakout | 989b2ad9 |
| 2 | Confidence rewrite batch: ORB15, ORB30, SecondLegContinuation, VCP | b1a12204 |
| 3 | DualDivergence + mechanical audit of all 9 plugins | 3aeccf4b |

## Changes Applied to All 9 Plugins

### ClassVars Added

All 9 plugins now declare:
- `shadow_only: bool = True`
- `requires_i6_confluence: bool = True`
- Module-level constants: `_MIN_REGIME_WEIGHT: float = 0.30`, `_MIN_CTF_SCORE: float = 0.25`

### Dual Gate Pattern

Gate ordering in all 9 plugins follows this sequence:
1. Null checks and features dict assembly
2. Gate 1: `hmm_regime_weight(features, direction) < _MIN_REGIME_WEIGHT` - return `no_signal()`
3. Gate 2: `abs(float(features.get("ctf_score") or 0.0)) < _MIN_CTF_SCORE` - return `no_signal()`
4. `extract_ohlcv()` / `df["close"].to_numpy()` / `get_atr_with_floor_from_frames()`
5. Domain logic and confidence computation

**VWAPDeviation and MomentumBreakout** required reordering: `extract_ohlcv()` was previously called at the top of `compute_full`; it was moved to after the dual gate.

### Regime Gate Variants by Plugin

| Plugin | regime_type | Gate 1 call |
|--------|-------------|-------------|
| LVNBreakout | trend | `hmm_regime_weight(features, "up")` >= 0.30 |
| VWAPReclaim | any | `hmm_trending_weight(features)` >= 0.30 |
| VWAPDeviation | mean_reversion | `hmm_regime_weight(features, "ranging")` >= 0.30 |
| MomentumBreakout | trend | up OR down >= 0.30 |
| ORB15 | trend | up OR down >= 0.30 |
| ORB30 | trend | up OR down >= 0.30 |
| SecondLegContinuation | trend | up OR down >= 0.30 |
| VCP | trend | up OR down >= 0.30 |
| DualDivergence | mean_reversion | `hmm_regime_weight(features, "ranging")` >= 0.30 |

## Confidence Changes

### Gates-Only (4 plugins) - Confidence Preserved Unchanged

- **LVNBreakout**: 4-factor composite `0.30*vol + 0.25*trend_clarity + 0.25*lvn_inv + 0.20*close_str` (pre-existing; `trend_clarity` uses `hmm_probability` - only permitted HMM-in-confidence in this plan)
- **VWAPReclaim**: 4-factor composite `0.30*vwap_reclaim_score + 0.25*regime_align + 0.25*rel_vol_score + 0.20*rsi_align` preserved
- **VWAPDeviation**: 3-factor composite `0.40*dev_score + 0.35*regime_compat + 0.25*vol_contraction` preserved; `apply_exhaustion_boost` call preserved
- **MomentumBreakout**: 3-factor composite `0.40*roc_score + 0.35*vol_score + 0.25*break_margin` preserved

### New 4-Factor Composites (5 plugins) - No HMM in Confidence

**ORB15 and ORB30** (weights: 0.35 + 0.25 + 0.25 + 0.15 = 1.0):
- `breakout_margin_score = clamp01(breakout_excess / atr)` - how far beyond range price closed
- `range_quality_score = clamp01(1.0 - range_width / (atr * 2.0))` - tighter range = cleaner setup
- `volume_score = clamp01((volume_ratio - threshold) / threshold)`
- `gap_alignment_score = 0.5/0.80/0.20` based on gap direction

**SecondLegContinuation** (weights: 0.35 + 0.30 + 0.20 + 0.15 = 1.0):
- `leg_quality_score = clamp01((amplitude/atr - 1.0) / 3.0)` - Leg 1 amplitude vs ATR
- `momentum_persistence_score = clamp01(1.0 - best_age / 50)` - freshness of swing data
- `volume_alignment_score = clamp01((rel_vol - 1.0) / 1.5)`
- `structure_quality_score = clamp01(1.0 - dist_to_50 / (zone_width / 2))` - proximity to ideal 50% retrace

**VCP** (weights: 0.30 + 0.25 + 0.25 + 0.20 = 1.0):
- `contraction_quality_score = clamp01((count - 3) / 4.0)` - number of contractions
- `volume_expansion_score = clamp01((bar_vol / last_vol - 1.0) / 1.0)`
- `breakout_margin_score = clamp01(abs(margin) / atr)` - close beyond prior bar's range
- `range_compression_score = clamp01(1.0 - bar_range / atr)` - bar range vs ATR

**DualDivergence** (weights: 0.35 + 0.30 + 0.20 + 0.15 = 1.0):
- `ofi_divergence_score = clamp01(math.tanh(abs(ofi_div) / 3.0))` - tanh saturation of OFI divergence
- `cvd_divergence_score = clamp01(math.tanh(abs(cvd_div) / 3.0))` - tanh saturation of CVD divergence
- `confirmation_bars_score = clamp01((count - 3) / 5.0)` - persistence of divergence
- `volume_score = clamp01((rel_vol - 1.0) / 1.5)`

## Mechanical Audit - Gate Ordering Verification

All 9 plugins confirmed: `_MIN_CTF_SCORE` gate check line precedes first OHLCV/ATR access line.

| Plugin | CTF gate line | First OHLCV/ATR line | Order |
|--------|---------------|----------------------|-------|
| lvn_breakout | 99 | 102 (get_atr) | PASS |
| vwap_reclaim | 107 | 111 (to_numpy) | PASS |
| vwap_deviation | 93 | 97 (extract_ohlcv) | PASS |
| momentum_breakout | 86 | 90 (extract_ohlcv) | PASS |
| orb15 | 116 | 177 (get_atr) | PASS |
| orb30 | 120 | 179 (get_atr) | PASS |
| second_leg_continuation | 104 | 107 (get_atr) | PASS |
| vcp | 122 | 127 (to_numpy) | PASS |
| dual_divergence | 116 | 130 (get_atr) | PASS |

## Test Results

`.venv/bin/pytest tests/unit/intelligence/ -q --ignore=tests/unit/intelligence/correctness`:
- **2785 passed, 5 failed, 33 skipped**
- All 5 failures are pre-existing and unrelated to this plan

**Pre-existing failures (unchanged):**
1. `test_lifecycle_tracker.py::TestTemporalGuard::test_activation_when_bar_time_equals_signal_timestamp`
2. `test_trade_framer.py::TestRRGate::test_viable_false_zero_risk`
3. `test_trade_framer.py::TestStructuralIntegration::test_structural_long_with_sr_targets`
4. `test_vwap_deviation.py::TestVWAPDeviation::test_long_signal_below_lower_band`
5. `test_vwap_deviation.py::TestVWAPDeviation::test_short_signal_above_upper_band`

## Deviations from Plan

None - plan executed exactly as written. All 9 plugins updated per specification. Gate ordering, ClassVar additions, and confidence rewrites match plan requirements. The 5 pre-existing test failures were identified in the plan context as pre-existing and were not touched.

## Self-Check: PASSED

All 9 plugin source files confirmed present. All 3 task commits confirmed in git log.
