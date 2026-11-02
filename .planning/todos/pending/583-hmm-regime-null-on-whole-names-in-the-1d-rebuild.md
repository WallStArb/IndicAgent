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

Runs and where to read them (for a session that did not run them; all finished). Raw one-line-per-fit JSONL is
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
Intraday arms (2026-11-02, run after the 1d and 1h results; refused-segment share / names with zero
output / median written share; stored K=5 is the stage-2 output read with `--stored`, validated
identical to computed K=5 on 15 of 15 intraday names):

| tf, names | K=3 | K=4 | K=5 (stored) |
|---|---|---|---|
| 15m, 20 names, 239 segments | 0.8 / 0.0 / 100 | 5.9 / 0.0 / 100 | 26.8 / 0.0 / 88.3 |
| 5m, 8 names, 91 segments | 0.0 / 0.0 / 100 | not run | 15.4 / 0.0 / 94.8 |

Names: seeded draws (20261102) from the 650 stage-2 names. K=4 at 5m was skipped because K=3 beat the
stored K=5 by more than the 2-point band. 0 errors. Rule output per timeframe: 1d and 1h and 15m and 5m
all pick the smallest K tested, which is K=3 on 1h, 15m and 5m and K=2 on 1d (K=2 added after seeing
K=3/4/5; a 2-state trend model has no mid state, so K=2 is the owner's design call). The 5m arm is 8
names, so its figure is indicative only. Nothing else is owed from the measurement; changing the APR
component count or the 0.05 floor is the owner's call.

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

## Deep-data K study (preregistered 2026-11-02; owner direction: keep both families)

Provenance that motivates it: `docs/analysis/bic_k_selection.md` (2026-06-26) chose K=5 from four
ETFs on 5m only, one EM fit per (symbol, K), applied to every timeframe by migration 176; 1d was
never measured at all, and its BIC curves are jagged (EWT K=4 scores below K=2: EM local optima,
not information). The 583 sweep above is the production-validity measurement (walk-forward
refusals) and stands.

Arms (both run per timeframe; cut at 2026-09-30, same as the 583 sweep; bars from
`market_data_ohlcv_tradeable`):
- Refusal arm (production-exact: fixed `alpha.hmm.random_state`, walk-forward, the kernel's
  segment schedule): decides. Trend K in {3,4,5}; vol K in {2,3} (reference only, no production
  change this pass).
- BIC reference arm (one full-history fit per (name, K), best-of-3 restarts, converged fits
  only, K in {2,3,4,5,6}): records the full-information state count; never overrides the refusal
  arm.

Samples (seed 20261103, distinct from the 583 draws' 20261102; symbol lists written to the
scratch dir):
- 1d: the 437-name 583 set (337 refusal + 100 control), refit with BIC recording; trend and vol.
- 5m: names with at least 15 years of 5m history at study time; seeded draw, N=60 (probe 3 names
  first; if projected wall-clock exceeds about 6 h, halve BIC restarts before shrinking N; record
  any shortfall and its direction).
- 15m, 1h: seeded draws of N=60 from the same deep-5m names (resampled).

Decision rules, frozen before the first fit:
- Trend production K per intraday timeframe: the K in {3,4,5} with the lowest refused-segment
  share; ties within 2 percentage points to the smaller K (the 583 rule).
- 1d trend production K=3 stands (decided 2026-11-02 on complete data; no more 1d data can
  exist). The 1d BIC arm is the first-ever 1d reference: recorded, not decision-driving.
- Vol: K=2 this pass regardless of outcome; a per-timeframe vol change is a future preregistered
  decision that cites these tables.
- Divergence disclosure: if a timeframe's BIC-reference minimum sits more than one K from its
  refusal winner, the lead reports it to the owner before the pin moves; the refusal rule still
  governs.
- Zero-output name counts, error counts and per-fit convergence recorded; nothing is judged on
  returns (D6).

Deliverables: JSONL shards and summary tables appended to this todo in the 583 format (refused
share / zero-output names / median written share per cell) plus the BIC winner distribution per
timeframe; a methodology-change-ledger entry citing this section when the per-timeframe APR keys
land; the keys `feature.hmm.n_components.<tf>` are item 3's landing shape in todo 584.

Executor: extend `scripts/ops/ops_hmm_refusal_screen.py` (record BIC per fit, `--restarts`, a
vol-family K override; verify what `compute_regime_columns` exposes) through /simplify, /review
and the unit suite before any run; shards in `data/scratch/583-k-sweep-2/`.

Run state (Track C, indicagent-d6, 2026-11-02). Tool landed as commit 95fec2251 (`--bic` arm,
`--restarts`, BIC winner distribution + divergence disclosure in `--summarize`; the vol-family
K override already worked through `--family volatility` and `--n-components`, now pinned by
test). Pools written to `data/scratch/583-k-sweep-2/`: `pool_deep5m.txt` (381 names, first 5m
bar <= 2011-11-02 in `market_data_ohlcv_tradeable`), `set437_1d.txt` (dc's 337 genuine + the
100 control names read back from the 583 sweep shards; union 437, no overlap), `deep60.txt`
(the seeded draw, seed 20261103, reproduced with the tool's own sorted-sample algorithm, so it
equals `--sample 60 --seed 20261103` on the pool). One cohort: the same 60 names serve 5m, 15m
and 1h (the spec's one seed on one pool). Arms to run, cut 2026-09-30, 3-4 shards at a time
(the box shares the 534 backfill campaign):

- 1d, BIC arm only (refusal already decided, K=3 stands): `--tf 1d --bic` on `set437_1d.txt`,
  trend and volatility, default K grid 2-6, 3 restarts.
- 5m/15m/1h on `deep60.txt`: refusal arm trend K 3 4 5 and volatility K 2 3, then `--bic`
  (K 2-6, 3 restarts) for both families.
- Summarize with `--summarize data/scratch/583-k-sweep-2/*.jsonl`; message the lead the
  per-timeframe rule output and any |dK| > 1 divergence BEFORE appending the tables here.

Timing probe (IWM refusal K=3; GLD BIC K=5 x 3 restarts) launched 2026-11-02 ~22:10 UTC; read
`secs` from `probe_ref_IWM.jsonl` / `probe_bic_GLD.jsonl`. Projection rule: shard 3-4 ways
first, halve BIC restarts second, shrink N=60 last (lead 2026-11-02); record any change.

## Done when

1. The refusal reason per (name, segment) is measured across the full 1d universe (how many
   names have no regime at all, and why).
2. The cause is fixed, or the refusal is shown correct and the names are declared regime-unknown,
   before any spec segments by regime on 1d (principle: segment by regime).
3. The deep-data K study tables are recorded in this todo and the per-timeframe
   `feature.hmm.n_components.<tf>` keys have landed (item 3 of todo 584).
