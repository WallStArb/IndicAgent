---
status: pending
priority: P2
filed: 2026-09-30
source: plan 186-14 live dry run of services/ic_measure.py
---

# The fresh IC writer's bootstrap is serial and too slow for the 186-28 run

## What

`services/ic_measure.py` calls the 186-10 measure jobs, whose `pooled_rank_ic` calls
`_circular_block_bootstrap_ic` with its default `max_workers=1`: 2000 resamples, each re-ranking the
resampled (n, 32) block. Measured 2026-09-30 on one idle core (single cell, 32 features,
2000 resamples): 22 s at 5,000 strided rows, 102 s at 20,000, linear, so about 5 ms per strided
row per cell.

A full 1d cell (931 names x about 2,700 sessions, stride 5, about 500,000 strided rows) is about
42 minutes, and a unit costs five cells (term structure at four horizons, plus the proposer cell
at the first horizon), so the 1d proposer alone is on the order of 35 hours serial before
`regime_volatility` disclosure (per label, per horizon). The unbounded dry run confirmed it: 1d on
931 names ran 73 minutes without finishing its first unit; 15m on 40 names ran 37 minutes
without finishing its first unit (both killed).

ic_engine avoided this with bootstrap threads (`alpha.ic.cross_sectional_bootstrap_threads.*`,
about 5x at 16 workers) and early stopping (`alpha.ic.bootstrap_early_stop.*`); `MeasureParams`
carries neither.

## Why it matters

186-28 runs the fresh IC once on the rebuilt features. At serial speed that is days of wall clock,
and a kill loses the current unit (units are the resume grain).

## What to do

Measure first (the 186-14 numbers above are the baseline), then pick: a thread count on
`MeasureParams` passed to the bootstrap (determinism holds: only the order-free resample step is
threaded), unit-level worker processes in the writer (compute-only workers, writes stay serial in
main, the CLAUDE.md pool rule), or both. Keep the stored values bit-identical to the serial path
for one small cell as the acceptance test. Decide before 186-28 starts, not during it.
