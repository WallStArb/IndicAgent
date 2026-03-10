---
phase: 24-second-derivative-acceleration
plan: "01"
subsystem: testing
tags: [tdd, red-tests, momentum-accel, hma, exhaustion-score, acceleration-regime, swing-momentum, i7-wiring]

requires:
  - phase: 23-signal-generator-gate
    provides: Signal gate infrastructure — exhaustion wires build on same signal flow

provides:
  - RED test stubs for HMA (test_hma.py — ImportError)
  - RED test stubs for MomentumAccel new outputs — rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel (test_momentum_accel.py — 11 new FAILs)
  - RED test stubs for ExhaustionScore — score tiers, side, bars counter (test_exhaustion_score.py — ImportError)
  - RED test stubs for AccelerationRegime — regime states, accel_score, accel_agreement (test_acceleration_regime.py — ImportError)
  - RED test stubs for SwingMomentum — warmup gate, struct_energy, amplitude_expanding (test_swing_momentum.py — ImportError)
  - RED test stubs for I7 exhaustion wiring — boost (sweep/hunt) and guard (breakout/trend) (test_i7_exhaustion_wiring.py — 5 FAILs)

affects:
  - 24-02 (HMA implementation + MomentumAccel extension — turns test_hma.py and new momentum_accel stubs GREEN)
  - 24-03 (ExhaustionScore + AccelerationRegime — turns test_exhaustion_score.py and test_acceleration_regime.py GREEN)
  - 24-04 (SwingMomentum — turns test_swing_momentum.py GREEN)
  - 24-05 (I7 exhaustion wiring — turns test_i7_exhaustion_wiring.py fully GREEN)

tech-stack:
  added: []
  patterns:
    - "make_frames_extended() helper: builds frames with hma_20, macd_histogram_12_26_9, atr_14 for state-based MomentumAccel tests"
    - "make_oscillating_prices(): sine-wave close price array for SwingMomentum warmup gate tests"
    - "_sweep_frames/_hunt_frames/_breakout_frames/_trend_frames: minimal valid-signal frame builders for I7 exhaustion wiring tests"
    - "State injection pattern: plugin._state['key'] = value directly in test to simulate prior-bar state without calling compute_next twice"

key-files:
  created:
    - tests/unit/intelligence/composites/test_exhaustion_score.py
    - tests/unit/intelligence/composites/test_acceleration_regime.py
    - tests/unit/intelligence/test_swing_momentum.py
    - tests/unit/intelligence/test_hma.py
    - tests/unit/intelligence/test_i7_exhaustion_wiring.py
  modified:
    - tests/unit/intelligence/composites/test_momentum_accel.py

key-decisions:
  - "macd_hist_slope reads macd_histogram_12_26_9 (not macd_12_26_9) — histogram is the MACD component that reveals slope of momentum momentum, not signal line"
  - "price_accel formula: (velocity_now - velocity_prev) / atr — ATR-normalized so cross-instrument comparable; 0.0 guard when ATR absent"
  - "hma_slope and hma_accel are state-based (not from prev_features) — hma_20 key comes from I1 HMAPlugin output in live pipeline; test injects via features dict directly"
  - "I7 wiring tests use frame builders that produce real signals (not _no_signal) so penalty/boost deltas are measurable; 4 negative-threshold tests pass at RED because logic absent is equivalent to logic absent — GREEN state requires correct conditional"
  - "SwingMomentum test file uses conditional assertions (if result:) for warm-up-sensitive tests so they do not become blocking false-positives when run in isolation against a partially-warmed plugin"

patterns-established:
  - "RED-only plan: 6 test files, zero source files — establishes contract before any implementation begins"
  - "I7 boost/guard tests baseline pattern: call plugin twice (once without exhaustion, once with) and diff confidence delta to pin exact +0.1 / -0.15 values"

requirements-completed: []

duration: 8min
completed: "2026-03-10"
---

# Phase 24 Plan 01: Second-Derivative Acceleration RED Test Stubs

**6 test files covering HMA, rsi_curvature/macd_hist_slope/price_accel/hma_slope/hma_accel, ExhaustionScore, AccelerationRegime, SwingMomentum, and all 4 I7 exhaustion wires — all in RED state before implementation begins**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-10T12:18:21Z
- **Completed:** 2026-03-10T12:26:15Z
- **Tasks:** 3
- **Files modified:** 6 (1 extended, 5 created)

## Accomplishments

- Established test contracts for every Phase 24 component before a single line of implementation is written
- 16 new test functions FAILING (11 AssertionError/KeyError, 5 AssertionError) + 4 files ERROR on ImportError = full RED gate
- Zero regressions: 1434 pre-existing tests still pass
- Complete coverage: HMA formula (flat-series WMA property), MomentumAccel state-based outputs, ExhaustionScore scoring tiers and persistence, AccelerationRegime peak/trough single-bar inflection events, SwingMomentum warmup gate, and I7 exhaustion wiring with both boost and guard patterns

## Task Commits

1. **Task 1: Extend test_momentum_accel.py with RED stubs** - `5b7c039` (test)
2. **Task 2: Create RED test stubs for ExhaustionScore, AccelerationRegime, SwingMomentum** - `5ecaca9` (test)
3. **Task 3: Create RED test stubs for HMA and I7 exhaustion wiring** - `3ae3338` (test)

## Files Created/Modified

- `tests/unit/intelligence/composites/test_momentum_accel.py` — 11 new RED test functions for rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel; make_frames_extended helper added
- `tests/unit/intelligence/composites/test_exhaustion_score.py` — 11 RED tests (ImportError): score tiers (0.0/0.2/0.6/1.0), exhaustion_side (bull/bear/none), exhaustion_bars increment/reset
- `tests/unit/intelligence/composites/test_acceleration_regime.py` — 9 RED tests (ImportError): building/waning/neutral/peak/trough regimes, accel_score float range, accel_agreement max/min
- `tests/unit/intelligence/test_swing_momentum.py` — 7 RED tests (ImportError): warmup gate (returns {}), struct_energy formula and clamp, amplitude_expanding (0/1), output key presence
- `tests/unit/intelligence/test_hma.py` — 5 RED tests (ImportError): hma_20 in outputs, min_lookback=20, warmup gate, float on valid input, flat-series WMA property
- `tests/unit/intelligence/test_i7_exhaustion_wiring.py` — 9 tests (5 FAIL / 4 PASS): boost tests for LiquiditySweepReclaim+LiquidityHunt, guard tests for MomentumBreakout+TrendFollowing, signal suppression

## Decisions Made

- `macd_hist_slope` reads `macd_histogram_12_26_9` (not `macd_12_26_9`) — the histogram reveals slope of momentum, not the MACD signal line
- `price_accel` is ATR-normalized: `(velocity_now - velocity_prev) / atr` — produces cross-instrument comparable values; guard returns 0.0 when ATR absent
- HMA and hma_slope/hma_accel tests inject `hma_20` directly into `features` dict (simulating I1 pipeline output) — no need to call HMAPlugin from within MomentumAccel tests
- I7 wiring tests use a diff-confidence-delta pattern (baseline call vs. with-exhaustion call) to pin the exact +0.1 / -0.15 values to catch off-by-one implementation bugs

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Plan 24-02 ready to implement: HMA plugin (`src/intelligence/indicators/hma.py`) and MomentumAccel extensions (rsi_curvature, macd_hist_slope, price_accel, hma_slope, hma_accel)
- Plan 24-03 ready to implement: ExhaustionScore + AccelerationRegime composite plugins
- Plan 24-04 ready to implement: SwingMomentum structure plugin
- Plan 24-05 ready to implement: I7 exhaustion wiring (boost + guard)
- All test contracts locked — no implementation ambiguity

---
*Phase: 24-second-derivative-acceleration*
*Completed: 2026-03-10*
