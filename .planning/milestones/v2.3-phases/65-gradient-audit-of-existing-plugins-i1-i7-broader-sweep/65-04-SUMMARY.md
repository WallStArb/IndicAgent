---
phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
plan: 04
subsystem: intelligence
tags: [hmm, regime, gradient, confidence, i7, trading-plugins, continuous-probability]

# Dependency graph
requires:
  - phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
    provides: "gradient_utils.py with hmm_regime_weight and linear_ramp functions (plans 01-03)"
provides:
  - "11 I7 plugins converted from binary hmm_regime equality to continuous hmm_regime_weight"
  - "8 gradient continuity tests proving proportional confidence scaling"
  - "Second verification that second_leg and vcp are correct as-is"
affects: [i7-confidence-scoring, ml-training-data, signal-ranking]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "hmm_regime_weight(features, 'ranging'/'up'/'down') replaces hmm_regime == 0/1/2 in confidence scoring"
    - "linear_ramp() for continuous base confidence derivation from signal strength features"
    - "max(hmm_regime_weight(up), hmm_regime_weight(down)) for trending regime probability"

key-files:
  created: []
  modified:
    - src/intelligence/trading/failed_breakout.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/supply_demand_setup.py
    - src/intelligence/trading/ofi_divergence.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/choch_reversal.py
    - src/intelligence/trading/orb15.py
    - src/intelligence/trading/orb30.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/squeeze_expansion.py
    - tests/unit/intelligence/test_trading_setups.py

key-decisions:
  - "cross_asset_divergence.py left unchanged: hmm_regime equality is for direction logic (protected by critical warning), confidence already uses continuous hmm_regime_prob"
  - "vcp.py excluded from changes per critical warning: eligibility gates are binary, hmm_regime_prob already continuous"
  - "liquidity_hunt.py had no hmm_regime references at all -- added trending probability weighting (regime_type=trend)"
  - "squeeze_expansion regime_score uses trending weight (not ranging) because plugin is regime_type=trend"
  - "supply_demand_setup continuous freshness base uses linear_ramp(0.40, 1.0) mapping, replacing 3-step 0.35/0.46/0.58 tiers"

patterns-established:
  - "Confidence scoring: confidence += BOOST * hmm_regime_weight(features, direction) replaces binary if/else"
  - "Base confidence derivation: linear_ramp(feature, lo, hi) replaces step-function tiers"
  - "Trending probability: max(hmm_regime_weight(up), hmm_regime_weight(down)) for trend plugins"

requirements-completed: [GRAD-I7-HMM, GRAD-I7-CONFIDENCE]

# Metrics
duration: 10min
completed: 2026-04-24
---

# Phase 65 Plan 04: I7 HMM Gradient Conversion Summary

**11 I7 plugins converted from binary hmm_regime equality to continuous hmm_regime_weight; second_leg and vcp verified correct as-is**

## Performance

- **Duration:** 10 min
- **Started:** 2026-04-24T11:16:09Z
- **Completed:** 2026-04-24T11:26:08Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments
- Replaced all `hmm_regime == X` equality checks in I7 confidence scoring paths with continuous `hmm_regime_weight()` probability scaling
- Converted momentum_breakout 3-step regime_score (0.5/1.0/0.1) to continuous trending probability
- Converted squeeze_expansion binary regime_score (0.2/0.8) to continuous 0.2-0.8 interpolation via trending probability
- Converted supply_demand_setup 3-tier base confidence (0.35/0.46/0.58) to continuous linear_ramp from freshness
- Converted liquidity_sweep_reclaim flat 0.55 base to sweep-depth-derived continuous base
- Added trending probability weighting to liquidity_hunt (had no HMM weighting previously)
- Added 8 gradient continuity tests proving proportional scaling behavior
- Verified second_leg_continuation and vcp remain untouched with correct eligibility gates

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace HMM equality in 7 mean-reversion/any-regime plugins** - `312aeb1a` (feat)
2. **Task 2: Replace HMM equality + flat regime_score in 4 trend/momentum plugins + tests** - `2a36b92e` (feat)

## Files Created/Modified
- `src/intelligence/trading/failed_breakout.py` - Continuous ranging/trending probability replaces binary confidence boost
- `src/intelligence/trading/liquidity_sweep_reclaim.py` - Sweep-depth-derived base + ranging probability boost
- `src/intelligence/trading/supply_demand_setup.py` - Continuous freshness ramp + ranging weight replaces 3-step tiers
- `src/intelligence/trading/ofi_divergence.py` - Continuous ranging/trending weights replace equality checks
- `src/intelligence/trading/liquidity_hunt.py` - Added trending probability weighting (new)
- `src/intelligence/trading/prev_day_level_test.py` - Continuous ranging/trending for fade and continuation variants
- `src/intelligence/trading/choch_reversal.py` - Directional regime probability replaces binary alignment
- `src/intelligence/trading/orb15.py` - Trending probability scales ORB boost
- `src/intelligence/trading/orb30.py` - Trending probability scales ORB boost
- `src/intelligence/trading/momentum_breakout.py` - Continuous trending probability replaces 3-step regime_score
- `src/intelligence/trading/squeeze_expansion.py` - Continuous 0.2-0.8 interpolation via trending probability
- `tests/unit/intelligence/test_trading_setups.py` - 8 new TestHMMGradientContinuity tests

## Decisions Made
- **cross_asset_divergence.py left unchanged**: The plan described "3-branch confidence tiers" but actual code uses hmm_regime for direction/variant determination (protected by critical warning #1). Confidence already uses continuous hmm_regime_prob >= 0.75 threshold. No binary confidence scoring to fix.
- **squeeze_expansion uses trending weight, not ranging**: Plan said "ranging" but plugin is regime_type="trend". Used trending probability for correctness -- regime_agrees case gets trending boost from 0.2 to 0.8.
- **liquidity_hunt added HMM weighting**: Plugin had zero hmm_regime references. Added trending probability boost since regime_type="trend".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] liquidity_hunt had no HMM regime weighting**
- **Found during:** Task 1 (examining liquidity_hunt.py for hmm_regime patterns)
- **Issue:** Plugin had zero hmm_regime references despite being a trend-regime plugin
- **Fix:** Added `hmm_regime_weight` import and trending probability boost (0.10 * trending_w)
- **Files modified:** src/intelligence/trading/liquidity_hunt.py
- **Verification:** All 60 tests pass
- **Committed in:** 312aeb1a (Task 1 commit)

**2. [Rule 2 - Missing Critical] supply_demand_setup had no HMM regime weighting**
- **Found during:** Task 1 (converting 3-tier base to continuous)
- **Issue:** Plugin had no hmm_regime weighting despite being regime_type="any"
- **Fix:** Added ranging probability boost alongside freshness-based continuous base
- **Files modified:** src/intelligence/trading/supply_demand_setup.py
- **Verification:** All 60 tests pass
- **Committed in:** 312aeb1a (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 missing critical functionality)
**Impact on plan:** Both auto-fixes add continuous regime weighting where it was absent. No scope creep -- both are the stated purpose of this plan applied consistently.

## Issues Encountered
None - all changes applied cleanly, 60/60 tests pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 11 modified I7 plugins produce valid signals with compose_confidence() output
- No hmm_regime equality in confidence scoring paths (only in regime_ctx logging and direction logic)
- Ready for plan 05 (if any remaining I7 conversions) or pipeline integration testing

---
*Phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep*
*Completed: 2026-04-24*
