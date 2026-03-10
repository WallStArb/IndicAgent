---
phase: 24-second-derivative-acceleration
plan: 04
subsystem: intelligence
tags: [swing-momentum, structure, i3-plugin, peak-valley-detection, tdd]

# Dependency graph
requires:
  - phase: 24-01
    provides: InputSpec, I3 plugin patterns established in phase
provides:
  - SwingMomentumPlugin singleton in src/intelligence/structure/swing_momentum.py
  - struct_energy, struct_accel_bias, swing_amplitude_ratio, swing_amplitude_expanding, swing_velocity_bars, swing_velocity_trend outputs
affects:
  - 24-05 (I7 wiring — consumes struct_energy and struct_accel_bias)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Self-contained ±N=3 peak/valley detection: scan for extremes where high[i]==max(high[i-N:i+N+1])"
    - "_dedup_extremes() ensures alternating high/low sequence needed for swing amplitude analysis"
    - "Incremental state via full-frame rebuild on every compute_full call (non-incremental plugin)"
    - "ATR-14 computed inline without pandas dependency; raw-price fallback when ATR=0"

key-files:
  created:
    - src/intelligence/structure/swing_momentum.py
  modified: []

key-decisions:
  - "Full-frame rebuild of extremes on every compute_full call — simpler than incremental tracking, correct for non-incremental plugin"
  - "Peak detection uses >= (not strict >) to handle plateaus at max correctly"
  - "_dedup_extremes() keeps stronger extreme when consecutive same-type extremes appear, ensuring alternating H/L sequence"
  - "ATR computed inline (last 14 true-range bars) rather than reading from features frame — avoids frame dependency and keeps plugin self-contained"

patterns-established:
  - "Self-contained swing analysis: no dependency on SwingDetector or external extreme list"
  - "Warmup gate: returns {} until len(extremes) < 6 — 3 complete swings required"

requirements-completed: []

# Metrics
duration: 4min
completed: 2026-03-10
---

# Phase 24 Plan 04: SwingMomentum Summary

**Self-contained I3 SwingMomentumPlugin with ±3 peak/valley detection, 6-extreme warmup gate, struct_energy formula, and struct_accel_bias trend classification**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-10T12:32:41Z
- **Completed:** 2026-03-10T12:36:08Z
- **Tasks:** 1 (TDD: RED already existed, GREEN + verify)
- **Files modified:** 1

## Accomplishments
- Implemented SwingMomentumPlugin as a fully self-contained I3 plugin with no SwingDetector dependency
- ±3 confirmation window peak/valley detection with `_dedup_extremes()` for alternating H/L enforcement
- All 6 outputs correct: struct_energy clamped formula, struct_accel_bias HH+HL/LL+LH classification, amplitude expanding flag
- All 7 test_swing_momentum tests GREEN; zero regressions in 1468 passing tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement SwingMomentum plugin** - `a672855` (feat)

**Plan metadata:** (docs commit to follow)

_Note: TDD tasks — RED stubs existed from Wave 0; GREEN implemented here_

## Files Created/Modified
- `src/intelligence/structure/swing_momentum.py` — SwingMomentumPlugin with 6 outputs and plugin singleton

## Decisions Made
- Full-frame rebuild of extremes on every `compute_full` call rather than incremental tracking: simpler, correct for non-incremental plugin, avoids state desync across sliding window calls
- Peak detection uses `>=` (not strict `>`) to handle flat plateaus at the max/min correctly
- `_dedup_extremes()` ensures alternating H/L sequence: when two consecutive same-type extremes appear, the stronger one is kept (higher of two highs, lower of two lows)
- ATR-14 computed inline from the frame's high/low/close arrays rather than reading from `features` frame — keeps plugin self-contained and avoids missing-ATR edge cases

## Deviations from Plan

None - plan executed exactly as written. The plan gave discretion to choose full-frame vs incremental approach; full-frame rebuild was selected as simpler and correct.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `swing_momentum.py` exports `SwingMomentumPlugin` and `plugin` singleton — ready for Plan 05 I7 wiring
- `struct_energy` and `struct_accel_bias` are the primary outputs consumed by Plan 05
- Pre-existing RED stubs in `test_acceleration_regime.py` and `test_i7_exhaustion_wiring.py` are Plan 03/05 targets, not regressions

---
*Phase: 24-second-derivative-acceleration*
*Completed: 2026-03-10*
