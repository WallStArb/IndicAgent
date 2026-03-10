---
phase: 24-second-derivative-acceleration
plan: 05
subsystem: intelligence
tags: [exhaustion-score, acceleration-regime, swing-momentum, i7-wiring, register-plugins, plugin-registration]

# Dependency graph
requires:
  - phase: 24-02
    provides: HMA indicator enabling hma_accel vote in AccelerationRegime
  - phase: 24-03
    provides: ExhaustionScore and AccelerationRegime composite plugins
  - phase: 24-04
    provides: SwingMomentum structure plugin
provides:
  - 3 new plugins registered in TIER_I2 (ExhaustionScore, AccelerationRegime) and TIER_I3 (SwingMomentum)
  - LiquiditySweepReclaim exhaustion boost: +0.10 confidence when exhaustion_score > 0.6 in sweep direction
  - LiquidityHunt exhaustion boost: same pattern as SweepReclaim
  - MomentumBreakout exhaustion guard: -0.15 confidence when exhaustion_score > 0.7 AND exhaustion_bars >= 3
  - TrendFollowing exhaustion guard: same penalty + _no_signal() suppression when confidence drops below threshold
affects: [signal-generator, market-analysis, i7-setups, exhaustion-wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Exhaustion boost pattern: score > 0.6 + direction-matched exhaustion_side → confidence += 0.10"
    - "Exhaustion guard pattern: score > 0.7 AND bars >= 3 → confidence -= 0.15"
    - "TrendFollowing suppression: confidence < confidence_threshold after guard → _no_signal()"
    - "Boost/guard placed after all other confidence adjustments, before final clamp"

key-files:
  created: []
  modified:
    - src/intelligence/register_plugins.py
    - src/intelligence/trading/liquidity_sweep_reclaim.py
    - src/intelligence/trading/liquidity_hunt.py
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/trend_following.py
    - tests/unit/intelligence/test_i2_registration.py
    - tests/unit/intelligence/test_i7_registration.py

key-decisions:
  - "Exhaustion boost is directional: bull exhaustion only boosts long sweeps, bear only boosts short sweeps — wrong-direction exhaustion is ignored"
  - "MomentumBreakout exhaustion guard does NOT suppress signal — only lowers confidence (floor 0.10 by clamp)"
  - "TrendFollowing exhaustion guard triggers _no_signal() when confidence < confidence_threshold (0.4) — prevents chasing exhausted trends"
  - "Guard placed after zone friction penalty to stack deterrents for highest-risk scenarios"
  - "Registration test counts updated: TIER_I2 9→11, total plugins 92→95"

patterns-established:
  - "Exhaustion boost/guard pattern: read score + optional side/bars, apply delta, append tag, re-clamp"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-03-10
---

# Phase 24 Plan 05: Integration — Plugin Registration + I7 Exhaustion Wiring Summary

**3 new plugins registered in TIER_I2/I3; exhaustion boost wired into 2 sweep/hunt plugins (+0.10) and guard into 2 trend/breakout plugins (-0.15 with TrendFollowing suppression)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-10T12:39:31Z
- **Completed:** 2026-03-10T12:42:51Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments
- Registered ExhaustionScore and AccelerationRegime into TIER_I2 (now 11 plugins), SwingMomentum into TIER_I3 (now 8 plugins) — validate_tier() will no longer hard-crash at startup
- Wired exhaustion boost into LiquiditySweepReclaim and LiquidityHunt: decelerating momentum into a sweep zone confirms the stop-run setup with +0.10 confidence
- Wired exhaustion guard into MomentumBreakout and TrendFollowing: prevents chasing exhausted moves with -0.15 confidence; TrendFollowing additionally suppresses the signal entirely when penalty pushes below fire threshold
- All 9 I7 exhaustion wiring tests GREEN; 1482 total tests passing with zero regressions

## Task Commits

1. **Task 1: Register 3 new plugins in register_plugins.py** - `17e4c36` (feat)
2. **Task 2: Wire exhaustion boost into LiquiditySweepReclaim and LiquidityHunt** - `02598fd` (feat)
3. **Task 3: Wire exhaustion guard into MomentumBreakout and TrendFollowing** - `48f2b22` (feat)

## Files Created/Modified
- `src/intelligence/register_plugins.py` - Added 3 imports, 3 register_pattern() calls, TIER_I2 +2, TIER_I3 +1
- `src/intelligence/trading/liquidity_sweep_reclaim.py` - Exhaustion boost block + corrected clamp to min(0.95, max(0.10))
- `src/intelligence/trading/liquidity_hunt.py` - Exhaustion boost block (same pattern)
- `src/intelligence/trading/momentum_breakout.py` - Exhaustion guard block after zone friction penalty
- `src/intelligence/trading/trend_following.py` - Exhaustion guard block + _no_signal() suppression on threshold breach
- `tests/unit/intelligence/test_i2_registration.py` - Count updated 9→11
- `tests/unit/intelligence/test_i7_registration.py` - Total count updated 92→95

## Decisions Made
- Exhaustion boost is directional: `bull` exhaustion only boosts long (direction==1) sweeps; `bear` only boosts short (direction==-1) sweeps. Wrong-direction exhaustion side has no effect — a bear exhaustion signal doesn't boost a long setup.
- MomentumBreakout applies the penalty but does NOT suppress via _no_signal() — only TrendFollowing has the suppression path. MomentumBreakout has a natural floor at 0.10 from the clamp.
- Guard placed after zone friction penalty to stack deterrents: the combination of zone friction + exhaustion can cumulatively push a marginal trade below threshold.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated stale plugin count constants in registration tests**
- **Found during:** Task 1 (Register 3 new plugins in register_plugins.py)
- **Issue:** `test_i2_registration.py::test_tier_i2_constant_exists` checked `len(TIER_I2) == 9` (now 11) and `test_i7_registration.py::test_total_plugin_count` checked `total == 92` (now 95 with 3 new patterns)
- **Fix:** Updated TIER_I2 assertion 9→11; updated total plugin count 92→95
- **Files modified:** tests/unit/intelligence/test_i2_registration.py, tests/unit/intelligence/test_i7_registration.py
- **Verification:** Both tests pass after update
- **Committed in:** 17e4c36 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - stale count constants)
**Impact on plan:** Necessary update — hardcoded counts always need updating when new plugins are registered. No scope creep.

## Issues Encountered
None — plan executed cleanly.

## Next Phase Readiness
- Phase 24 is now fully complete: HMA (24-02), ExhaustionScore/AccelerationRegime (24-03), SwingMomentum (24-04), registration + I7 wiring (24-05)
- Pipeline will pick up exhaustion_score, exhaustion_side, exhaustion_bars from market_analysis_service (I2/I3 outputs) and route them into the 4 wired I7 setups on every bar
- validate_tier() at startup will find all 3 new plugins correctly registered

---
*Phase: 24-second-derivative-acceleration*
*Completed: 2026-03-10*
