---
status: completed
closed: 2026-09-30
priority: P1
filed: 2026-09-27
source: phase 186 planning (plan 186-13), found by reading the regime_writer source; not yet proven by a test
---

# HMM walk-forward segment gates read the segment's own future labels (lookahead, fixed in 186-13)

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

## Closed 2026-09-30 (plan 186-13, task 2)

The lookahead was real. Two RED tests failed against the moved kernel before any fix:

- Segment gate: on a 920-bar series whose first segment (bars 620..919) decodes into one state for
  its last rows, the full run gave segment status 2 (degenerate_occupation) for bars 620..648
  while the run cut at bar 649 gave status 1 (written) for the same rows. `causality_probe`
  raised on the same row.
- Length gate: at 602 observations (bars 0..621) every row was refused, while the full 700-bar
  series labeled bars 620 and 621 (code 0.0 against NaN).

Fix (commit e24427178): the occupation gate runs on the fitted model's own smoothed decode of its
training slice (`gate_basis: training_slice`); the first boundary is
`max(initial_warmup_bars, n_components * min_obs_factor)` regardless of series length, and a
series with no boundary returns unlabeled rows instead of raising. Golden regenerated in its own
commit (bef01e2d7). Every difference from the pre-fix output lies in a refit segment whose verdict
flipped, except `hmm_duration` in the first written run after a flip.

Flips by case (rows that gained or lost a label): SPY 1d trend +3,052; SPY 1d volatility -252;
SPY 1h trend +18,034; SPY 1h volatility +4,355 and -1,650; LQD 1d trend -252; LQD 1d volatility
+252; TLT 1d trend +252 and -252; TLT 1d volatility unchanged; synthetic trend +2,080, volatility
+300. The training-slice gate accepts far more segments than the whole-segment gate (which
rejected a segment on its own future collapse), so stored coverage rises when the rebuild runs.
Stored `feature_vectors` regime columns keep the old mask until the 186-26 rebuild (todo 466).
