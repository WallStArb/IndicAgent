---
phase: 119-remaining-16-setup-refactoring
plan: "01"
subsystem: intelligence
tags: [i7-plugins, hmm, confidence, shadow-mode, ctf-score, regime-gate]

# Dependency graph
requires:
  - phase: 118-remaining-16-setup-refactoring
    provides: baseline Wave-1 I7 plugins with initial Phase 118 changes
provides:
  - All 8 Wave-1 I7 plugins fully refactored with 6 GOOD patterns
  - dual gate (HMM regime + CTF score) before OHLCV access in all Wave-1 plugins
  - 4-factor intrinsic confidence composites in all Wave-1 plugins
  - shadow_only=True and requires_i6_confluence=True declared on all 8 plugins
affects: [119-02, 119-03, Plan-03-ctf-perturbation-contract]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual gate pattern: HMM regime weight gate + abs(ctf_score) gate BEFORE any OHLCV/ATR access"
    - "4-factor intrinsic confidence composite: 4 named clamp01-bounded factor vars, weights summing to 1.0, wrapped by compose_confidence()"
    - "Gate-first ordering: features assembly -> dual gate -> OHLCV/ATR -> domain logic -> frame_trade()"

key-files:
  created: []
  modified:
    - src/intelligence/trading/microstructure_utils.py
    - src/intelligence/trading/ofi_spike.py
    - src/intelligence/trading/cvd_spike.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/failed_breakout.py
    - src/intelligence/trading/candlestick_pattern_setup.py
    - src/intelligence/trading/session_extremes_setup.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/delta_exhaustion.py
    - src/intelligence/trading/trade_framer.py
    - tests/unit/intelligence/test_i6_hmm_confidence_wiring.py
    - tests/unit/intelligence/test_i7_extrinsic_contract.py
    - tests/unit/intelligence/trading/test_ofi_plugins.py
    - tests/unit/intelligence/trading/test_cvd_plugins.py
    - tests/unit/intelligence/test_ofi_divergence.py
    - tests/unit/intelligence/trading/test_failed_breakout.py
    - tests/unit/intelligence/trading/test_candlestick_pattern_setup.py
    - tests/unit/intelligence/trading/test_candlestick_tier1_setups.py
    - tests/unit/intelligence/trading/test_liquidity_hunt.py
    - tests/unit/intelligence/trading/test_session_extremes_setup.py

key-decisions:
  - "HMM/CTF as gates not confidence addends: below-threshold blocks signal outright; above-threshold only enters confidence as ctf_factor intrinsic component"
  - "volume_score sourced from features.get('rel_volume') not df['volume'] to preserve gate-before-OHLCV ordering invariant"
  - "FailedBreakout trend gate: block only if BOTH hmm_regime_weight(up) < 0.30 AND hmm_regime_weight(down) < 0.30 (bidirectional plugin)"
  - "DeltaExhaustion: exempt_exhaustion capture profile kept; apply_exhaustion_boost/guard NOT added (plan requirement)"
  - "trade_framer._resolve_entry: added session_extremes_* -> at_limit mapping (pre-existing docstring contract violation)"

patterns-established:
  - "Wave-1 dual gate ordering: features dict -> HMM gate -> CTF gate -> extract_ohlcv/get_atr_with_floor -> domain logic"
  - "Test gate semantics: gate-passing HMM+CTF values in fixture base_features; test below-threshold explicitly for gate blocking"
  - "_MIN_REGIME_WEIGHT = 0.30 and _MIN_CTF_SCORE = 0.25 as named module constants in each plugin file"

requirements-completed: [REFACTOR-06, REFACTOR-07]

# Metrics
duration: ~90min (continued from prior context)
completed: 2026-06-10
---

# Phase 119 Plan 01: Wave-1 I7 Plugin GOOD Patterns Summary

**8 Wave-1 I7 setup plugins refactored with dual HMM+CTF gate before OHLCV, 4-factor intrinsic confidence composites (weights sum 1.0), shadow_only=True, and requires_i6_confluence=True**

## Performance

- **Duration:** ~90 min (multi-session, continued from context boundary)
- **Completed:** 2026-06-10
- **Tasks:** 4
- **Files modified:** 20 (9 production, 11 test)

## Accomplishments

- All 8 Wave-1 plugins declare `shadow_only: bool = True` and `requires_i6_confluence: bool = True` as explicit ClassVars
- Dual gate (HMM regime weight + abs(ctf_score)) inserted BEFORE any `extract_ohlcv`, `get_atr_with_floor_from_frames`, `df["close"]`, or `df["volume"]` access in all 8 plugins and their shared helper
- 4-factor intrinsic confidence composites replace all previous additive/binary formulas; every composite uses named `clamp01`-bounded factor vars with weights summing exactly to 1.0, wrapped by `compose_confidence()`
- Consumer audit confirmed: `detect_spike_signal()` has exactly 2 call sites (ofi_spike.py, cvd_spike.py); refactoring was self-contained
- Pre-existing `trade_framer._resolve_entry` missing `session_extremes_*` -> `at_limit` mapping fixed (docstring contract violation)

## Gate-Ordering Audit Table

Per Task 4 requirement, gate-line vs first OHLCV/ATR line verified via `grep -n`:

| Plugin | File | Gate line (_MIN_CTF_SCORE) | First OHLCV/ATR line | Pass |
|--------|------|---------------------------|---------------------|------|
| detect_spike_signal | microstructure_utils.py | 78 | 81 (get_atr_with_floor) | PASS |
| OFISpike | ofi_spike.py | delegates to helper | N/A | PASS |
| CVDSpike | cvd_spike.py | delegates to helper | N/A | PASS |
| OFIDivergence | ofi_divergence.py | 129 | 132 (get_atr) | PASS |
| FailedBreakout | failed_breakout.py | 127 | 132 (df["close"]) | PASS |
| CandlestickPatternSetup | candlestick_pattern_setup.py | 143 | 147 (extract_ohlcv) | PASS |
| SessionExtremesSetup | session_extremes_setup.py | 98 | 103 (get_atr) | PASS |
| LiquidityHunt | liquidity_hunt.py | 83 | 100 (get_atr) | PASS |
| DeltaExhaustion | delta_exhaustion.py | 94 | 98 (get_atr) | PASS |

## 4-Factor Confidence Weights Per Plugin

| Plugin | Factor 1 (0.35-0.45) | Factor 2 (0.25-0.30) | Factor 3 (0.20) | Factor 4 (0.10-0.15) |
|--------|---------------------|---------------------|-----------------|---------------------|
| OFISpike/CVDSpike (shared) | z_score_score (0.45) | volume_score (0.25) | ctf_factor (0.20) | persistence_score (0.10) |
| OFIDivergence | magnitude_score (0.40) | alignment_score (0.25) | persistence_score (0.20) | volume_score (0.15) |
| FailedBreakout | break_magnitude_score (0.35) | rejection_strength_score (0.30) | volume_score (0.20) | structure_quality_score (0.15) |
| CandlestickPatternSetup | pattern_confidence_score (0.35) | body_ratio (0.25) | volume_confirmation (0.25) | zone_proximity (0.15) |
| SessionExtremesSetup | level_proximity (0.35) | rejection_strength (0.30) | session_timing_score (0.20) | volume_context (0.15) |
| LiquidityHunt | hunt_significance (0.35) | rejection_reclaim_strength (0.30) | volume_context (0.20) | structure_quality (0.15) |
| DeltaExhaustion | cvd_z_score (0.35) | price_fail_score (0.30) | hmm_mean_reversion_score (0.20) | ctf_score_factor (0.15) |

## Task Commits

1. **Task 1: Refactor detect_spike_signal + flip OFISpike/CVDSpike ClassVars** - `b3766a51` (feat)
2. **Task 2: Refactor OFIDivergence and FailedBreakout** - `47dc168c` (feat)
3. **Task 3: Refactor CandlestickPatternSetup, SessionExtremesSetup, LiquidityHunt, DeltaExhaustion** - `912b7f93` (feat)
4. **Task 4: Mechanical audit + spike-test rewrite + verification** - (no source changes; verification only)

## Files Created/Modified

- `src/intelligence/trading/microstructure_utils.py` - dual gate + 4-factor confidence replacing additive formula
- `src/intelligence/trading/ofi_spike.py` - shadow_only=True, requires_i6_confluence=True ClassVars
- `src/intelligence/trading/cvd_spike.py` - shadow_only=True, requires_i6_confluence=True ClassVars
- `src/intelligence/trading/ofi_divergence.py` - full refactor: ClassVars, dual gate, 4-factor confidence
- `src/intelligence/trading/failed_breakout.py` - full refactor: ClassVars, dual gate (bidirectional), 4-factor confidence
- `src/intelligence/trading/candlestick_pattern_setup.py` - full refactor: ClassVars, gate-before-OHLCV reorder, 4-factor
- `src/intelligence/trading/session_extremes_setup.py` - full refactor: ClassVars, gate-before-OHLCV, 4-factor
- `src/intelligence/trading/liquidity_hunt.py` - shadow_only added (already had i6=True), gate-before-OHLCV, 4-factor
- `src/intelligence/trading/delta_exhaustion.py` - full refactor: ClassVars, dual gate, 4-factor, exempt_exhaustion kept
- `src/intelligence/trading/trade_framer.py` - added session_extremes_* -> at_limit in _resolve_entry
- Multiple test files - added gate-passing HMM/CTF values to fixtures; rewrote additive assertions to gate-semantics

## Decisions Made

- HMM and CTF treated as binary gates (below threshold = no_signal) not confidence addends; `ctf_factor` appears in the 4-factor composite as an intrinsic signal quality factor, not as an extrinsic gate bypass
- `volume_score` sourced from `features.get("rel_volume")` (pre-assembled dict) rather than `df["volume"]` to maintain gate-before-OHLCV invariant
- FailedBreakout bidirectional gate: block only when BOTH `hmm_regime_weight(up) < 0.30` AND `hmm_regime_weight(down) < 0.30`; a directional signal is still allowed when one side meets threshold
- DeltaExhaustion `hmm_mean_reversion_score` factor uses regime alignment magnitude as intrinsic confidence quality, distinct from exhaustion boost/guard functions which are explicitly not called

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] trade_framer._resolve_entry missing session_extremes -> at_limit mapping**
- **Found during:** Task 3 (test_entry_type_is_at_limit was failing)
- **Issue:** Plugin docstring stated "Entry style: at_limit" but _resolve_entry had no session_extremes case, falling through to default at_close
- **Fix:** Added `if st.startswith("session_extreme"): return entry_price, "at_limit"` before the trend_/pullback handling
- **Files modified:** src/intelligence/trading/trade_framer.py
- **Verification:** `test_entry_type_is_at_limit` passes
- **Committed in:** 912b7f93 (Task 3 commit)

**2. [Rule 1 - Bug] Extrinsic contract test scenario factories missing Phase 119 gate fields**
- **Found during:** Task 3/4 verification run
- **Issue:** `_scenario_ofi_divergence` and `_scenario_liquidity_hunt` in test_i7_extrinsic_contract.py did not include HMM/CTF gate-passing values; after Task 1-3 refactoring the scenarios produced no_signal instead of firing
- **Fix:** Added `hmm_prob_trending_up`, `hmm_prob_trending_down`, `ctf_score` to both scenario feature dicts
- **Files modified:** tests/unit/intelligence/test_i7_extrinsic_contract.py
- **Verification:** Both `test_extrinsic_perturbation_does_not_change_confidence[ofi_divergence]` and `[liquidity_hunt]` pass; `test_confidence_within_bounds` also unlocked
- **Committed in:** 912b7f93 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both fixes were correctness issues discovered during test verification. No scope creep.

## Handoff to Plan 03: ctf_score Perturbation Contract

Per Task 4 instructions, `test_i7_extrinsic_contract.py` was NOT modified for the ctf_score perturbation contract (Plan 03 owns this). The extrinsic contract test currently passes for all Wave-1 plugins because the scenario factories now include gate-passing CTF values AND the 4-factor confidence composites are correctly insulated from extrinsic ctf_score perturbation (ctf_factor is derived from the same `ctf_score` already in features, so perturbing it above-threshold changes confidence - this is the Plan 03 concern to resolve by excluding ctf_score from the extrinsic perturbation key set).

No ctf_score-perturbation failures were observed in the current test run (all Wave-1 plugins pass the extrinsic contract test). Plan 03 should audit whether the `_EXTRINSIC_KEYS` dict in the test includes `ctf_score` and update accordingly.

## Test Suite Status

- Intelligence suite: 2782 passed, 33 skipped, 5 failed (all 5 pre-existing, unrelated to Phase 119)
- Pre-existing failures:
  - `test_lifecycle_tracker.py::TestTemporalGuard::test_activation_when_bar_time_equals_signal_timestamp`
  - `test_trade_framer.py::TestRRGate::test_viable_false_zero_risk`
  - `test_trade_framer.py::TestStructuralIntegration::test_structural_long_with_sr_targets`
  - `test_vwap_deviation.py::TestVWAPDeviation::test_long_signal_below_lower_band`
  - `test_vwap_deviation.py::TestVWAPDeviation::test_short_signal_above_upper_band`

## Next Phase Readiness

- Wave-1 plugins fully refactored; ready for Plan 02 (Wave-2 plugins: OFIContinuation, OrbSetup, etc.)
- All must_have truths verified
- Consumer audit of detect_spike_signal confirmed exactly 2 call sites

---
*Phase: 119-remaining-16-setup-refactoring*
*Completed: 2026-06-10*
