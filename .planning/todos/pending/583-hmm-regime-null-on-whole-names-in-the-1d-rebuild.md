---
status: pending
priority: P1
filed: 2026-11-01
source: todo 564 column screen, per-name view (scripts/ops/ops_feature_column_screen.py)
---

# HMM regime outputs are NULL on whole names in the 186-26 1d rebuild

## What the screen found

The per-name screen on the todo 564 eight-name 1d pool (report
`logs/feature_column_screen_20261101T225359Z.json`) shows the seven `hmm_*` probability and state
columns (`hmm_churn`, `hmm_duration`, `hmm_entropy`, `hmm_prob_ranging`,
`hmm_prob_trending_down`, `hmm_prob_trending_up`, `hmm_regime_prob`) all NULL on three of eight
names, and `regime` NULL with them. A pooled screen does not see it because the other names are
populated.

| symbol | 1d rows | hmm rows | first hmm row |
|---|---|---|---|
| AAPL | 5,470 | 0 | none |
| HON | 5,469 | 0 | none |
| SCCO | 3,929 | 0 | none |
| MSFT | 5,468 | 1,239 | 2018-10-19 |
| KO, JPM | 5,469 | 5,217 | warmup only missing |
| SPY, XOM | 5,465 / 5,468 | all | |

Twenty-one years of AAPL and HON with no regime is not warmup. The likely path is the
walk-forward gate in `src/intelligence/features/kernels/_hmm.py` refusing every segment
(`not_converged` or degenerate state occupation, around lines 613-640 and 959-1004); NULL is the
correct output for a refused fit, so this may be a kernel-input or gate-threshold problem rather
than a persistence one. Related: todo 226 (n_iter convergence headroom).

`equity_beta_z` is NULL on SPY only (beta of the market proxy to itself, by construction) and
populated on about 2,700 of about 5,470 rows on the other names; confirm the window start is
declared, not a gap.

## Measurement (2026-11-02, indicagent-dc)

Instrument: `scripts/ops/ops_hmm_refusal_screen.py` (commit f0328d67e; `--stored` and `--within-panel`
follow). It calls the rebuild's `compute_regime_columns` on `market_data_ohlcv_tradeable` bars
cut at 2026-09-30, fits on the full history and writes nothing. Reproduction check: on MSFT, KO,
JPM, SPY, XOM and AAPL every stored 1d row is a reproduced written row (the 21-22 extra reproduced
rows per name are bars the panel grid lacks).

Two causes, kept apart:

- Stale volume: 104 of the 194 names with no 1d trend output are `fallback`-kind names (HON, SCCO
  and others). Before migration 543 their volume was NULL, the trend family hit the input gap and
  wrote nothing. In process on current bars HON writes 5,491 bars and SCCO 3,408. The rebuild at
  the new pin fixes these; nothing else is needed.
- Genuine refusal: 337 non-fallback names (90 with no output, 247 partial) of 1,210. On these, 4,036
  of 5,260 K=5 segments were refused (4,035 `degenerate_occupation`, 1 `fit_failed`, 0
  `not_converged`); every fit converged and none reached the 200-iteration cap, so todo 226
  headroom does not explain it. Of the 1,371 lowest per-name state fractions among refused
  segments, 813 are below 0.001 (a state is never occupied), 418 are 0.001-0.03, 140 are 0.03-0.05.
  The 0.05 occupation floor is not the cause and stays.

K sweep (trend family, `hmm_n_components` overridden; rule fixed before the run: per timeframe the
lowest refused-segment share, and among K within 2 percentage points of it the smallest K).
Cells are refused-segment share / names with zero output / median written share of modeled rows.

| tf, set | K=3 | K=4 | K=5 |
|---|---|---|---|
| 1d, refusal set (337 names, 5,240 segments) | 29.9 / 2.2 / 76.1 | 56.4 / 6.2 / 53.3 | 76.7 / 18.3 / 27.8 |
| 1d, control (100 names, 2,374 segments) | 2.9 / 0.0 / 100 | 3.4 / 0.0 / 96.0 | 6.8 / 0.0 / 95.1 |
| 1d, combined (437 names) | 21.5 / 1.7 / 86.8 | 39.8 / 4.7 / 63.7 | 54.9 / 13.9 / 38.7 |
| 1h (40 names, 519 segments) | 0.2 / 0.0 / 100 | 3.7 / 0.0 / 100 | 10.2 / 0.0 / 90.9 |

The rule picks K=3 on 1d and on 1h. Name sets: the 1d refusal set is the 337 genuine names above;
the control is a draw of 100 (seed 20261102) from the 332 non-fallback names with at least 90% of
1d rows written in stored data (a 99% pool has only 127 names, so a draw of 100 would be nearly the
whole pool); the 1h set is a draw of 40 (seed 20261102) from the 1,055 non-fallback names with at
least 15,000 1h bars. 0 errors in 1,431 fits; one 1h K=5 fit hit the iteration cap, the only one.

Added arm, chosen after seeing the K=3/4/5 results (2026-11-02): 1d K=2 on the same 437 names.

| 1d, K=2 | refused / zero-output names / median written share |
|---|---|
| refusal set (337) | 7.0 / 0.0 / 100 |
| control (100) | 0.0 / 0.0 / 100 |
| combined (437) | 4.8 / 0.0 / 100 |

The fixed rule picks K=2 mechanically, but a 2-state trend model has no mid state (the label map gives
only `low` and `high`, so no `ranging` or transition label); a low refused share there is a design
question, not a free win. Changing the APR component count or the 0.05 floor is the owner's call.

Runs and where to read them (for a session that did not run them). Raw one-line-per-fit JSONL is
copied to `data/scratch/583-k-sweep/` (on disk only, not in git); the scripts are
`scripts/ops/ops_hmm_refusal_screen.py`. Read any finished run with
`.venv/bin/python scripts/ops/ops_hmm_refusal_screen.py --summarize <files>`; stored and computed
records of one cell are checked against each other and the computed one is used on a mismatch.
- 1d: `1d_refusal_{0..3}.jsonl` (337 names from `genuine.txt`) and `1d_control_{0..3}.jsonl` (100 names,
  `--sample 100 --seed 20261102` from `full_pool.txt`, the 332 non-fallback names at least 90% written),
  `--tf 1d --n-components 2 3 4 5`, 4 shards each.
- 1h: `1h_{0..2}.jsonl`, `--tf 1h --n-components 3 4 5 --symbols-file pool_1h.txt --sample 40 --seed 20261102`.
- 15m: `15m_{0..2}.jsonl`, 20 names `--symbols-file stage2_15m.txt --sample 20 --seed 20261102`
  (the 650 stage-2 names), computed `--within-panel --n-components 3 4`, then `--stored` for the
  stored K=5 on the same names.
- 5m: `5m_{0..3}.jsonl`, 8 names `--symbols-file stage2_5m.txt --sample 8 --seed 20261102`, computed
  `--within-panel --n-components 3`, then `--stored`; K=4 only if K=3 does not beat the stored K=5
  by more than the 2-point band.
Decision still owed: the per-timeframe table for 15m and 5m once those runs finish (a run is done
when `ps aux | grep ops_hmm_refusal_screen` is empty), then the rule's output, written here. Stored
arm validated against computed K=5 on 14 of 14 1d and 15 of 15 intraday names.

Caveats. K=3 is the smallest K tested and the refused share falls monotonically with K, so the
minimum is not located; a K=2 arm on 1d was added after seeing these results (recorded below when
run). Computed 1d counts include segments before 2005, the stored panel start, so they are
comparable across K but not equal to stored counts. A change to the APR component count or to the
floor is the owner's call; this record stops at the decision-rule output.

Stored arm: `--stored` lays the segments over the bars and counts a segment written when its first
row has stored regime output; with `--within-panel` (segments starting at or after the first stored
row) it equals the computed K=5 arm on 14 of 14 1d names (segments, refused, modeled, written). The
walk-forward needs 39,600 bars at 5m, 13,200 at 15m and 3,300 at 1h before its first fit, so the
stored arm duplicates the kernel's segment layout (`_walk_forward_hmm_full`: first boundary
`max(warmup, K * min_obs_factor)`, then one segment per refit step) and counts a segment refused when
its first row has no stored output, so a null for another reason also reads as refused; if the
kernel's schedule changes, rerun the stored-vs-computed check (`--summarize` prints the pairs) before
trusting it. The intraday check uses stage-2 names just above that (a first check on recent listings was vacuous:
no segments in either arm).

## Done when

1. The refusal reason per (name, segment) is measured across the full 1d universe (how many
   names have no regime at all, and why).
2. The cause is fixed, or the refusal is shown correct and the names are declared regime-unknown,
   before any spec segments by regime on 1d (principle: segment by regime).
