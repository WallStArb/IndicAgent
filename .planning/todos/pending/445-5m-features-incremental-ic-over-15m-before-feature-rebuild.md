---
status: pending
priority: P2
filed: 2026-09-26
source: owner question "do we need 5m?" (2026-09-26); gates the phase 186 feature_vectors rebuild
---

# Do 5m features add IC over 15m at matched horizons? Decide before the rebuild

## What

5m holds 75.1M of the 108.6M `feature_vectors` rows (about 69%), so it is most of the phase 186
rebuild's cost. No active research family reads 5m features: families 1 and 2 run on the 15m
grid, and ledger family 3 (sector ETF leads constituents) is written "5m or 15m". The
2026-09-13 per-timeframe cost check (`scripts/analysis/personal_cost_hurdle_by_tf.py`) found 5m
signal real but economic only at about half-day holds (H=39 bars), a horizon 15m also covers
(H=10 bars clears everywhere). Never tested: whether 5m-computed features carry information the
15m versions of the same features do not.

## Test

On the 233 `compute_eligible` names, for each feature present at both timeframes, sample 5m
features at 15m bar closes and measure the IC of the 5m feature on the forward return at
matched clock horizons (about 2.5 hours and half a day), after residualizing on the same
feature's 15m value. Report the share of features with incremental IC distinguishable from zero
after multiple-testing correction, and whether any of them clear the cost hurdle at that
horizon. This is a scoping measurement, not a verdict: it goes through the research runner in
exploration mode so it is counted.

## Decision it feeds

Nothing incremental: the rebuild covers 15m, 1h and 1d; raw 5m bars keep ingesting (raw data is
permanent) and 5m features can be rebuilt later from them. Real incremental IC that survives
costs: keep 5m in the rebuild and record which features earn it.
