---
phase: 24-second-derivative-acceleration
plan: 03
subsystem: intelligence
tags: [i2, composite, exhaustion, acceleration, momentum, plugin]

# Dependency graph
requires:
  - phase: 24-02
    provides: rsi_curvature, macd_hist_slope, price_accel, hma_accel outputs in MomentumAccelPlugin

provides:
  - ExhaustionScorePlugin with exhaustion_score (tiered 0.2/0.6/1.0), exhaustion_side (bull/bear/none), exhaustion_bars (state counter)
  - AccelerationRegimePlugin with accel_regime (building/peak/trough/waning/neutral), accel_score ([-1,1]), accel_agreement ([0,1])

affects:
  - 24-05 (I7 wiring — reads exhaustion_score as guard/boost)
  - market_analysis_service (I2 composite pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - RSI-gated exhaustion scoring: side determined by RSI extreme first, then count matching curvature/slope conditions
    - Inflection-first regime priority: peak/trough checked before building/waning to prevent masking single-bar events
    - State-only counter: exhaustion_bars tracked exclusively in _state, not read from features accumulator
    - 4-vote agreement: accel_agreement = max(pos, neg) / 4 for symmetric 2/2 split = 0.5

key-files:
  created:
    - src/intelligence/composites/exhaustion_score.py
    - src/intelligence/composites/acceleration_regime.py
  modified: []

key-decisions:
  - "ExhaustionScore RSI-gated logic: bull_count and bear_count only increment when RSI is in the respective extreme zone (>70 or <30) — prevents spurious bear scores when RSI is at 75 but curvature/slope are positive"
  - "AccelerationRegime inflection priority: peak/trough checked before building/waning — trough fires correctly even when accel_score=1.0 (all-positive) follows a deeply negative bar"
  - "4-vote AccelerationRegime: hma_accel added as 4th vote per test authority; accel_agreement uses max(pos,neg)/4 formula giving 0.5 for exact 2/2 split"

patterns-established:
  - "RSI-gated condition counting: determine side from RSI extreme first, then count matching secondary conditions"
  - "Inflection-first branch order: single-bar events (peak/trough) always precede multi-bar state detection"

requirements-completed: []

# Metrics
duration: 4min
completed: 2026-03-10
---

# Phase 24 Plan 03: ExhaustionScore + AccelerationRegime I2 Plugins Summary

**Two I2 composite plugins synthesizing second-derivative outputs into tiered exhaustion scoring and momentum regime classification consumed by I7 setups**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-10T12:33:44Z
- **Completed:** 2026-03-10T12:37:03Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- ExhaustionScorePlugin: tiered scoring (0.0/0.2/0.6/1.0) from RSI extreme + curvature + MACD histogram slope; state-tracked exhaustion_bars counter; RSI-gated so curvature/slope only score within their respective extreme zone
- AccelerationRegimePlugin: sign-votes 4 acceleration measures; 5-state regime (building/peak/trough/waning/neutral); inflection events (peak/trough) evaluated before directional states to prevent masking single-bar events
- All 19 unit tests GREEN (10 ExhaustionScore + 9 AccelerationRegime)
- Zero regressions in full unit suite (1477 passing, 5 pre-existing failures from Plan 05 not yet implemented)

## Task Commits

1. **Task 1: ExhaustionScore plugin** - `99ac8e9` (feat)
2. **Task 2: AccelerationRegime plugin** - `0031698` (feat)

## Files Created/Modified

- `src/intelligence/composites/exhaustion_score.py` — ExhaustionScorePlugin: RSI-gated tiered exhaustion detection with state-tracked bar counter
- `src/intelligence/composites/acceleration_regime.py` — AccelerationRegimePlugin: 4-vote sign-consensus regime classifier with inflection detection

## Decisions Made

- **RSI-gated bull/bear counts**: When RSI=75 and curvature/slope are positive (wrong direction for bull exhaustion), only the RSI condition contributes to bull_count — the curvature/slope conditions must NOT count toward bear_count because RSI is not in bear territory. Score=0.2, not 0.6.
- **Inflection-first branch order**: The plan specifies `building` first, but the test `test_accel_regime_trough_fires_once_on_inflection_bar` sends all-positive inputs on bar 2 after an all-negative bar 1. That gives accel_score=1.0 which would match "building" before reaching "trough" check. Test authority overrides plan spec; peak/trough evaluated first.
- **4-vote agreement formula**: Tests use 4 inputs (rsi_curvature, macd_hist_slope, price_accel, hma_accel). `test_accel_agreement_min_when_split` expects 0.5 for 2+2 split. `max(pos,neg)/4` gives 2/4=0.5, matching the test. Plan's 3-vote division by 3 was superseded by test file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] RSI-gated condition counting**
- **Found during:** Task 1 (ExhaustionScore) GREEN phase
- **Issue:** Initial implementation counted bull_count and bear_count independently. With rsi=75, curvature=+0.3, hist_slope=+0.1, bear_count=2 (curvature>0 and hist_slope>0), giving score=0.6 instead of expected 0.2.
- **Fix:** Determine RSI side first; count conditions only within the active side's context.
- **Files modified:** src/intelligence/composites/exhaustion_score.py
- **Committed in:** `99ac8e9` (Task 1 feat commit)

**2. [Rule 1 - Bug] Inflection-before-directional branch order**
- **Found during:** Task 2 (AccelerationRegime) GREEN phase
- **Issue:** "building" check (accel_score > 0.5) blocked "trough" from firing on bar with accel_score=1.0 following deeply negative bar.
- **Fix:** Evaluate peak/trough inflection conditions before building/waning directional states.
- **Files modified:** src/intelligence/composites/acceleration_regime.py
- **Committed in:** `0031698` (Task 2 feat commit)

**3. [Rule 1 - Bug] 4-vote vs 3-vote accel_agreement**
- **Found during:** Task 2, reading test file
- **Issue:** Plan specifies 3 inputs and division by 3. Test file uses 4 inputs (adds hma_accel) and expects accel_agreement=0.5 for 2+2 split. 3-vote formula gives 0.33 for 2/3 agreement, not 0.5.
- **Fix:** Implemented 4-vote formula: `max(pos_count, neg_count) / 4`.
- **Files modified:** src/intelligence/composites/acceleration_regime.py
- **Committed in:** `0031698` (Task 2 feat commit)

---

**Total deviations:** 3 auto-fixed (3 Rule 1 - Bug)
**Impact on plan:** All fixes required for correctness per test authority. Test files are the authoritative specification for interface/formula details.

## Issues Encountered

None beyond the auto-fixed bugs above.

## Next Phase Readiness

- ExhaustionScore ready for I7 guard/boost wiring (Plan 05)
- AccelerationRegime ready for SwingMomentum context consumption (Plan 04 already complete)
- Both plugins follow I2 dataclass pattern with frozenset outputs — register in market_analysis_service when Plan 05 wires them

---
*Phase: 24-second-derivative-acceleration*
*Completed: 2026-03-10*
