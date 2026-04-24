---
phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
plan: 02
subsystem: intelligence
tags: [gradient, sigmoid, linear-ramp, threshold-decay, z-score, session-context, anchored-vwap, trend-regime, volatility-regime, ma-composites, volume-events, rsi-events]

# Dependency graph
requires:
  - phase: 65-01
    provides: gradient_utils.py with 8 canonical gradient functions
provides:
  - SessionContext continuous session progress fractions (27 fields)
  - AnchoredVWAP deviation sigma scoring for above_* fields
  - TrendRegime trend_regime_continuous field and gradient confidence
  - VolatilityRegime continuous vol_expansion
  - MAComposite separation percentage gradient for MA comparison fields
  - VolumeEvents z-score intensity, proximity BB touch, streak walking
affects: [65-03, 65-04, 65-05, all-I7-plugins, I6-CTF-confluence]

# Tech tracking
tech-stack:
  added: []
patterns: [session-progress-bell-shape-with-floor, deviation-sigma-scoring, z-score-intensity, streak-score-walking, proximity-decay-bb-touch]

key-files:
  created: []
  modified:
    - src/intelligence/context/session_context.py
    - src/intelligence/context/anchored_vwap.py
    - src/intelligence/context/trend_regime.py
    - src/intelligence/context/volatility_regime.py
    - src/intelligence/composites/ma_composites.py
    - src/intelligence/composites/volume_events.py
    - src/intelligence/composites/rsi_events.py
    - src/intelligence/schemas.py
    - tests/unit/intelligence/test_session_context_redesign.py
    - tests/unit/intelligence/test_context_plugins.py
    - tests/unit/intelligence/test_i2_plugins.py

key-decisions:
  - "Session window progress uses bell-shaped [0.2, 1.0] range with 0.2 floor inside window (preserves session-active signal while providing gradient depth)"
  - "AnchoredVWAP above_* fields use linear_ramp(sigma, -2, 2) for continuous deviation scoring"
  - "vol_expansion outputs ratio-1.0 continuous magnitude instead of ternary {-1, 0, 1}"
  - "trend_confidence uses 0.3 + 0.7 * linear_ramp(agreement_magnitude, 0, 1) when signals agree"
  - "vol_spike uses z_score_to_score(sigma_scale=3.0) so z=2.0 gives ~0.67 (meaningful but not saturated)"
  - "BB walking uses streak_score(saturation=5) instead of binary 3-bar threshold"
  - "rsi_events in_extreme kept as internal counter only; no output field changes needed"

patterns-established:
  - "Session floor pattern: bell-shaped gradient with 0.2 minimum inside window preserves active/inactive semantics"
  - "Deviation sigma scoring: (close - level) / std mapped via linear_ramp(-2, 2) to [0, 1]"
  - "Proximity decay for BB touches: threshold_decay(close, band, bb_width * 0.15)"

requirements-completed: [GRAD-I4-SESSION, GRAD-I4-VWAP, GRAD-I4-TREND, GRAD-I4-VOL, GRAD-I2-MA, GRAD-I2-VOL, GRAD-I2-RSI]

# Metrics
duration: 16min
completed: 2026-04-24
---

# Phase 65 Plan 02: I4 + I2 Gradient Conversion Summary

**25 binary fields converted to continuous gradients across 7 plugins: SessionContext bell-shaped session progress, AnchoredVWAP deviation sigma, TrendRegime continuous blended score, VolatilityRegime continuous expansion, MA separation percentages, volume z-score intensity, BB proximity decay**

## Performance

- **Duration:** 16 min
- **Started:** 2026-04-24T10:43:07Z
- **Completed:** 2026-04-24T10:58:58Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments
- SessionContext: all session/killzone/exchange/overlap flags output continuous progress fractions with 0.2 floor inside window; sub-session fields use linear decay/ramp
- AnchoredVWAP: above_session/swing/weekly_vwap use deviation sigma mapped to [0, 1]; alignment score automatically continuous
- TrendRegime: added trend_regime_continuous field (raw blended value [-1, 1]); gradient confidence based on agreement magnitude
- VolatilityRegime: vol_expansion outputs continuous ratio - 1.0 instead of ternary {-1, 0, 1}
- MAComposites: ema_9_gt_21, golden/death cross, sma_20_gt_50, price_above_sma200 output separation percentages via linear_ramp; price_touch_sma_50 uses proximity decay
- VolumeEvents: vol_spike uses z_score_to_score(sigma_scale=3.0); vol_drying uses linear_ramp; BB touch uses threshold_decay proximity; walking uses streak_score(saturation=5)
- All 74 tests pass (40 I4 + 34 I2); schema coverage validates

## Task Commits

Each task was committed atomically:

1. **Task 1: Convert I4 SessionContext + AnchoredVWAP + TrendRegime + VolatilityRegime to gradients** - `eef849e9` (feat)
2. **Task 2: Convert I2 composites (ma_composites, volume_events, rsi_events) to gradients** - `836590b3` (feat)

## Files Created/Modified
- `src/intelligence/context/session_context.py` - Bell-shaped session progress fractions with 0.2 floor, gradient sub-session
- `src/intelligence/context/anchored_vwap.py` - Deviation sigma scoring for above_* fields via linear_ramp
- `src/intelligence/context/trend_regime.py` - trend_regime_continuous field, gradient confidence
- `src/intelligence/context/volatility_regime.py` - Continuous vol_expansion (ratio - 1.0)
- `src/intelligence/schemas.py` - Added trend_regime_continuous to I4Context (94 fields now)
- `src/intelligence/composites/ma_composites.py` - Separation percentage gradients for MA comparison fields
- `src/intelligence/composites/volume_events.py` - z-score intensity, proximity BB touch, streak walking
- `src/intelligence/composites/rsi_events.py` - Added gradient import for future use
- `tests/unit/intelligence/test_session_context_redesign.py` - Gradient range checks, continuity tests for mid-session
- `tests/unit/intelligence/test_context_plugins.py` - trend_regime_continuous assertions, vol_expansion gradient test
- `tests/unit/intelligence/test_i2_plugins.py` - Gradient assertions for vol_spike, MA composites, BB touch/walking

## Decisions Made
- Session window progress uses [0.2, 1.0] bell-shaped range with 0.2 floor inside window -- pure tent function (0.0 at edges) would lose "session active" signal at session boundaries
- z_score_to_score uses sigma_scale=3.0 for vol_spike so z=2.0 gives ~0.67 (not saturated), z=3.0 saturates
- BB walking uses streak_score(saturation=5) instead of binary 3-bar check -- longer streaks score higher, saturates at 5 bars
- trend_confidence uses 0.3 + 0.7 * linear_ramp(agreement_magnitude, 0, 1) when signals agree -- minimum 0.3 even with weak agreement
- rsi_events in_extreme kept as internal counter only -- no standalone binary output field exists to convert

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Session progress edge behavior returned 0.0 at session boundaries**
- **Found during:** Task 1 (I4 test execution)
- **Issue:** session_progress() tent function returns 0.0 at window edges, so session_asia/session_ny returned 0.0 at session start time -- breaking "session is active" semantics
- **Fix:** Replaced session_progress() call with custom bell-shaped gradient using 0.2 floor inside window: `_SESSION_FLOOR + (1.0 - _SESSION_FLOOR) * peak` where peak is tent-shaped
- **Files modified:** src/intelligence/context/session_context.py
- **Verification:** test_ny_session_open_post_dst_1330_utc passes (session_ny > 0.0 at 09:30 start)
- **Committed in:** eef849e9 (Task 1 commit)

**2. [Rule 3 - Blocking] Test used time inside NY session window for "outside all sessions" assertion**
- **Found during:** Task 1 (gradient continuity test)
- **Issue:** test_session_outside_window_is_zero used 18:00 UTC Sunday = 14:00 ET, which is inside the NY window (09:30-16:00 ET)
- **Fix:** Changed test time to 21:00 UTC Sunday = 17:00 ET (after NY close, before Asia open)
- **Files modified:** tests/unit/intelligence/test_session_context_redesign.py
- **Verification:** test_session_outside_window_is_zero passes
- **Committed in:** eef849e9 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 7 I4+I2 plugins converted with gradient scoring
- Schema coverage validated (I4Context: 94 fields)
- 74 tests CI-clean
- Ready for Plans 03-04 (remaining plugin tiers: I1, I3, I5, SMC, I6, I7)
- Binary scanner baseline (114 violations from Plan 01) ready for post-fix comparison

---
*Phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep*
*Completed: 2026-04-24*

## Self-Check: PASSED

All files verified present: session_context.py, anchored_vwap.py, trend_regime.py, volatility_regime.py, ma_composites.py, volume_events.py, rsi_events.py, schemas.py, test_session_context_redesign.py, test_context_plugins.py, test_i2_plugins.py
All commits verified in git log: eef849e9 (Task 1), 836590b3 (Task 2)
