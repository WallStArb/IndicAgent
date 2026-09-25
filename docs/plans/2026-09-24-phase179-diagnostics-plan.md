# Phase 179 section 11 diagnostics: plan

**Author:** Claude (Opus 5.5), 2026-09-24; parent `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`
section 11.
**Status:** plan, lands before the freeze (harness plan Task 10). Implementation follows the
verdict run.

## Constraint that shapes it

Diagnostics never feed the token. They live in one script outside the harness package,
`scripts/analysis/sleeve_walk_forward_diagnostics.py`, that reads the S1, S2 and S3 artifacts.
The harness stage key hashes every `.py` file in `scripts/analysis/sleeve_walk_forward/`, so
putting diagnostics inside the package would move the frozen code key and force a rerun of every
stage. Outside it, a diagnostics fix never touches a verdict artifact.

The script needs from S3 the per-arm daily weight matrix, which S3 does not persist today. The
first implementation step adds it to the S3 payload before the freeze (a payload-only change,
tested for identical `decide` output), so the diagnostics can be computed after it without
touching the frozen code.

## Diagnostics

| # | Diagnostic | Definition |
|---|---|---|
| 1 | Turnover | Per arm, per trading day: one-way L1 turnover, sum over symbols of the absolute weight change after the day's rebalance. Reported as the annual mean and the per-year series |
| 2 | Net-of-cost Sharpe | Cost per day = turnover x (b / 2) / 10,000 for round-trip cost b in bps, subtracted from the day's excess log return. Reported at each band of `alpha.construction.cost_hurdle_bps_round_trip` (1, 3, 5, 10). No per-asset-class calibration exists in the repo yet, so the bands are uniform across symbols and say so; todo 393 replaces the old diagnostic's cost proxy the same way |
| 3 | Shape per arm | Sortino, max drawdown, skew, excess kurtosis, daily hit rate: already in the S3 payload (real run and null median) |
| 4 | Excess by period | Per year and per pre-registered sub-period, per arm |
| 5 | Per-symbol contribution | Sum over days of weight x forward return per symbol, per arm |
| 6 | Per-stratum excess | Excess return split by the day's equity-regime stratum |
| 7 | References | `equal_weight` long-only; static tilt (each symbol's time-averaged signed weight held constant over the span) |
| 8 | Deviation sizing | Uniform-weight variant (what production ran) and the production-pool variant (D2 exclusions put back), each a separate S1-S3 run under a suffixed output directory |
| 9 | Feature decay | For each refit k, each selected feature's pooled 1d IC over year k+1 (computed on the snapshot with the same cell function) against its training IC |
| 10 | No-weight days | Per year, sessions whose stratum had no weights (already counted by S2) |

## Order

1. Before the freeze: add the per-arm weight matrix to the S3 payload, with a test that `decide`
   is unchanged.
2. After the verdict: diagnostics 1-7 and 10 in one pass (minutes); 8 and 9 each need their own
   refits (about 6 minutes per S1 on four workers).
3. Report all of them in the verdict writeup next to the token, labeled as diagnostics.
