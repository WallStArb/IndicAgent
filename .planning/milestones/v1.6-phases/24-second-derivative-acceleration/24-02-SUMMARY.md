---
phase: 24-second-derivative-acceleration
plan: "02"
subsystem: intelligence-plugins
tags: [hma, momentum, second-derivative, i1, i2, tdd]
dependency_graph:
  requires: ["24-01"]
  provides: ["hma_20", "rsi_curvature", "macd_hist_slope", "price_accel", "hma_slope", "hma_accel"]
  affects: ["24-03", "24-04"]
tech_stack:
  added: []
  patterns: ["diff_buffer deque seeded from historical batch", "state-before-write curvature pattern"]
key_files:
  created:
    - src/intelligence/indicators/hma.py
  modified:
    - src/intelligence/composites/momentum_accel.py
decisions:
  - "HMA diff_buffer seeded from last sqrt_n bars during compute_full — not incremental accumulation — so historical batches produce a valid HMA value on first call"
  - "price_accel formula uses close[-4:] window: velocity_prev=close[-3]-close[-4], velocity_now=close[-1]-close[-2] — matches test spec (0.25 for closes=[5000,5001,5003,5006,5010], atr=8)"
  - "rsi_curvature reads OLD prev_rsi_accel before state write — no off-by-one, matches plan truth"
  - "macd_hist_slope state key named prev_macd_hist — matches test injection pattern"
metrics:
  duration_minutes: 3
  completed_date: "2026-03-10"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 1
---

# Phase 24 Plan 02: HMA Plugin + MomentumAcceleration Extension Summary

HMA I1 plugin with WMA-of-diff formula and MomentumAccelPlugin extended from 4 to 9 outputs covering all second-derivative acceleration signals.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Implement HMA I1 plugin | ebb3d84 | src/intelligence/indicators/hma.py |
| 2 | Extend MomentumAcceleration with 5 new outputs | c13ac11 | src/intelligence/composites/momentum_accel.py |

## Decisions Made

1. **HMA batch seeding**: `compute_full` seeds `diff_buffer` from the last `sqrt_n` historical bars rather than accumulating incrementally. This ensures a single `compute_full` call on a 50-bar batch returns a valid HMA value immediately — critical for indicator service warmup.

2. **price_accel formula window**: Uses `close[-4:]` (4-value window): `velocity_prev = close[-3]-close[-4]`, `velocity_now = close[-1]-close[-2]`. Authoritative source is the test file (expects 0.25 for the reference case). The plan interface comment said 0.125 (which would use a 3-value window) — test wins.

3. **rsi_curvature ordering**: Computed from `prev_rsi_accel` BEFORE the `self._state["prev_rsi_accel"] = rsi_accel` write. Off-by-one avoided by design — reading old state before write is the correct pattern.

4. **State key `prev_macd_hist`**: Named to match the test injection (`plugin._state["prev_macd_hist"] = 0.3`) — not `prev_macd_histogram`.

## Test Results

- HMA: 6/6 GREEN
- MomentumAccelPlugin: 23/23 GREEN (12 existing + 11 new)
- Full unit suite: 1451 passing, 5 pre-existing RED stubs from plan 24-01 (`test_i7_exhaustion_wiring.py`) — not regressions

## Deviations from Plan

**1. [Rule 1 - Bug] HMA diff_buffer seeding approach**
- **Found during:** Task 1, first test run
- **Issue:** Initial implementation appended only 1 diff value per `compute_full` call — with 50 bars, buffer had 1 entry but needed sqrt_n=4 to compute final WMA, so result was `{}` not a float.
- **Fix:** Seeded buffer by computing the last `sqrt_n` diff values from rolling window prefixes of the close series during `compute_full`.
- **Files modified:** src/intelligence/indicators/hma.py
- **Commit:** ebb3d84 (fix folded into same commit)

**2. [Rule 1 - Bug] price_accel formula window**
- **Found during:** Task 2 test analysis
- **Issue:** Plan interface comment said `close[-3:]` (3 values) yielding 0.125, but test expects 0.25. Verified against test: 4-value window `close[-4:]` is correct.
- **Fix:** Implemented 4-value window: `velocity_prev = close[-3]-close[-4]`, `velocity_now = close[-1]-close[-2]`.
- **Files modified:** src/intelligence/composites/momentum_accel.py
- **Commit:** c13ac11 (fix folded into implementation commit)

## Self-Check: PASSED

- src/intelligence/indicators/hma.py: FOUND
- src/intelligence/composites/momentum_accel.py: FOUND
- 24-02-SUMMARY.md: FOUND
- Commit ebb3d84 (HMA plugin): FOUND
- Commit c13ac11 (MomentumAccel extension): FOUND
