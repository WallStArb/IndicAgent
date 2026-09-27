---
status: pending
priority: P1
filed: 2026-09-27
source: phase 186 planning (plan 186-13), found by reading the regime_writer source; not yet proven by a test
---

# HMM walk-forward segment gates read the segment's own future labels (suspected lookahead)

## What

In the walk-forward HMM path, the occupation gate for each refit segment reads that segment's
decoded labels, up to `refit_every_bars` bars after the bar being labeled. Whether bar t gets a
label, and the duration and churn resets after a skipped gap, then depend on later bars. Two
whole-series length gates have the same shape. This is separate from todo 248 (full-history fit):
it survives the walk-forward fix.

## Exposure

HMM regime columns (`regime`, `regime_volatility` and their numeric columns) are kept out of every
research family until the phase 186 rebuild (STATE.md). Legacy results that stratified or gated
on these labels carry the leak.

## Fix

Plan 186-13 task 2: RED tests proving the dependence first; then gate each segment on the decode
of its own training data only, in its own commit; regenerate the regime golden in a separate
commit with the diff limited to segments whose verdict flipped; trace the caveat to every
consumer of the stored columns. If the RED tests do not fail, close this todo as not a bug with
the test as evidence.
