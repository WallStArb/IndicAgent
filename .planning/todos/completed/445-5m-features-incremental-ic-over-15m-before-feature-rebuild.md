---
status: completed
closed: 2026-09-28
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

## Decision (2026-09-28, phase 186 plan 07)

Method change from this todo's original "Test" section (R-08): the phase 183 research runner has
no exploration mode and S0 does not read `feature_vectors`, so this ran as a committed script
(`scripts/research/todo445_5m_incremental_ic.py`) instead, in-sample only, recorded as one counted
look in `.planning/gate_look_log.jsonl` (`run_ts` 2026-09-28T20:25:04Z). It is a scoping
measurement, not a verdict: no `concept_registry` row, no `research_run` row.

Window: 15m S0 panel, 2016-01-01 to `oos_start` (2025-12-24T05:15Z). Universe: `compute_eligible`
(233 names). 240 real feature columns tested (43 more reported `identical_across_tf` and excluded);
2 horizons (10 and 13 15m bars, about 2.5 hours and half a session). 480 (feature, horizon) cells:
176 BH-significant at q=0.05 (94 at horizon 10, 83 at horizon 13). Of those, 4 cleared the cost
hurdle at every (library rank, breadth) grid point: `ret_autocorr_1` and `sweep_detected`, both
horizons (corrected p 0.019-0.028, partial rank IC 0.002-0.0035, turnover 0.006-0.008).

Decision: **keep_5m**.

Rebuild timeframes: 15m, 1h, 1d, 5m
5m name set: ret_autocorr_1, sweep_detected

5m features stay at the 233 `compute_eligible` names that already have them; the 931-name
extension is a separate decision after todo 449's backfill and the R-09 disk guard.

Result JSON: `.planning/phases/186-old-ensemble-chain-retirement-and-ic-engine-re-scope/186-07-todo445-result.json`
(carries a `_correction_note`: a BH-FDR bug found reading the run's own output, fixed on the same
recorded p-values with no new DB query, did not change this decision).
