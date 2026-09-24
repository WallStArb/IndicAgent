# Phase 176 gate verdict: earnings-season conditioning

## Run provenance

- **Command** (run from `/home/bg/dev/indicagent`, detached with `setsid nohup`):

  ```
  .venv/bin/python services/ic_engine.py \
      --symbols <COVERED_SCOPE_SYMBOLS from 176-RECOMPUTE-LOG.md, 233 symbols> \
      --tf 5m 15m 1h 1d \
      --training-window-end 2025-12-24T05:15:00Z
  ```

  No `--refresh`. Output: `logs/corpus_pipeline/176-08-ic-engine.out`, `logs/ic_engine.log`;
  metadata: `logs/corpus_pipeline/176-08-run.meta`.
- **TRAINING_WINDOW_END**, derived with the plan's verbatim `LEAST()` clamp:
  - raw `MAX(bar_ts)` of `feature_vectors`: `2026-09-18 19:55:00+00`
  - `alpha.validation.oos_start`: `2025-12-24T05:15:00Z` (set, so an OOS holdout is in effect)
  - effective clamped value: **`2025-12-24 05:15:00+00`**
- **Git SHA at run time:** `main` at `e5688d4e8`; last commit touching `services/ic_engine.py`:
  `e5688d4e8`.
- **Start:** 2026-09-23 22:47:47 UTC. **End:** 2026-09-24 08:17:14 UTC (resumed invocation, status
  success, total_committed 348,760, total_skipped 32,870, elapsed_s 20,860.79). Wall clock 9h29m.

### Pre-flight (2026-09-23 22:46 UTC)

1. **Competing processes and locks:** none against `feature_vectors` or `ic_engine`'s other
   inputs. The one other job running was the concurrent session's OHLCV catch-up backfill
   (`infrastructure_run_historical_pipeline.py`), which writes only `market_data_ohlcv`, outside
   ic_engine's upstream watermark. No compress/decompress/autovacuum on `feature_vectors`.
2. **Registry alignment:** 300 feature concepts joined to `concept_gate` = 300 `FeatureVector`
   fields. The plan's literal query (`count(*) FROM concept_registry WHERE domain='feature'`)
   returns 302 because two gate-less deprecated rows (`new_high_flag`, `new_low_flag`) remain;
   ic_engine's own gate loads through the `concept_gate` join and sees exactly 300
   (`176-08-PREFLIGHT-NOTES.md`). Both new features have gate rows.
3. **Coverage precondition:** zero `feature_vectors` rows written after 176-07's COVERED_SCOPE
   snapshot (`bar_ts > 2026-09-18 19:55`), so 176-07's corpus-wide result (0 NULL
   `earnings_season_flag`) holds unchanged.
4. **Training window:** above.
5. **`--dry-run-validity`:** `n_symbols_compute=233, n_symbols_skip=0` and
   `n_cs_compute=124, n_cs_skip=0`. **compute / (compute + skip) = 357 / 357 = 1.00**, above the
   pinned 0.80 threshold. No skipped cells to list. Routing placed 232 of the 233 symbols in a
   regime group (`ic_engine.unrouted_symbols`), so one symbol is measured per-symbol but belongs
   to no cross-sectional group.

### Code in the run beyond plans 176-04/05/06 (bundled so one recompute absorbs it)

- Concurrent session's Phase 174 review fixes (`fix/174-code-review`, merged at `ccfbad153`).
- Todo 385 speedups: counting-rank numba bootstrap kernel (`alpha.ic.bootstrap_numba_kernel`,
  a computational fingerprint field; CI bounds within 2.3e-8 of the scipy path, zero gate flips
  on SPY 1h), concurrent ordered cross-sectional chunk fetch.
- Two determinism fixes: per-symbol regime cells iterated in hash-randomized set order (9/4506
  `passes_ci_gate` flips run to run on SPY 1h before the fix); cross-sectional rows sharing a
  timestamp returned in plan-dependent order (now `ORDER BY bar_ts, symbol`). Results from runs
  before this one are therefore not bit-reproducible at knife-edge CI gates; this run is.
- Todo 386: exact pre-flight cell row count; `alpha.ic.max_cell_rows` restored to 15,000,000
  (migration 353).
- Not included, by pre-registration: todo 389's short-horizon cell deletion (176-01's A1
  evidence was measured on `return_fast`, which 389 would delete).

### Progress and failures

- **Per-symbol pass: 22:47:47 -> 02:24:22 UTC, 3h37m wall** (233 symbols x 4 tfs, 8 workers x 3
  kernel threads). The previous full run's per-symbol leg took about 2.6-3.0 days
  (todo 385, leg A), so the todo 385/386 bundle measured roughly 17-20x end to end on the real
  corpus. No errors. Memory: main-process result retention (todo 399) pushed available RAM to
  about 1 GB at the worst point, with swap peaking around 16 GB; no OOM, no measurable stall.
- Cross-sectional stage started 02:24:22 UTC with 13 GB available after the workers exited.
- **Deliberate kill and resume, 02:29 UTC.** Once the cross-sectional fetch started allocating,
  the main process began paging its retained per-symbol rows (todo 399) back in from swap
  (~250 MB/s swap-in, 95% CPU idle, main RSS 16.4 -> 17.7 GB, swap ~34 GB). That is the swap
  stall todo 399 predicts, most likely Python's cyclic GC walking the retained row dicts.
  Terminated at 02:29:19 (no orphaned workers); the identical command was re-run at 02:29:30.
  Correctness is unaffected: every per-symbol row was already durable, and `_backfill_bh_fdr`
  resolves corpus-level BH-FDR from the database over all pending rows for this
  `training_window_end`, whichever invocation wrote them. Resume partition:
  `n_symbols_skip=233, n_symbols_compute=0, n_cs_compute=124`; main RSS 4.3 GB. Lost work: the
  one in-flight cross-sectional cell (5m `high_bear`, ~5 min).

## Decision rules (pinned before any Task 2 query ran)

Copied from 176-08-PLAN.md Task 2 verbatim in substance; not adjusted after results.

1. **Primitive gate (Query 1).** Per new feature: `PASS` iff at least one cell at this run's
   `training_window_end` has `reliable = true AND passes_fdr = true AND passes_walkforward = true`;
   `INSUFFICIENT_N` iff no cell reached `reliable = true`; `FAIL` otherwise.
2. **Conditioning (Query 2).** `SHARPENS` iff at least one feature that passes FDR unconditioned
   shows an in-season `|ic_sharpe_hac|` at least 1.7x both its off-season and its unconditioned
   value in at least two tfs; `DEGRADES` iff conditioned cells are uniformly weaker (in-season
   `|ic_sharpe_hac|` <= 1.1x parent); `INSUFFICIENT_N` iff too few season cells reached
   `reliable = true`; `NEUTRAL` otherwise.
3. **Lifecycle (Query 3).** Report `concept_transition_log` rows for the two new concepts written
   by this run; never hand-edit `concept_registry.status`. If none, say why.
4. **Isolation (Query 4).** (a) `regime_scope='earnings_season'` rows exist; (b)
   `ensemble_trainer._eligibility_where(False)[1]` as a COUNT predicate selects zero
   earnings-season rows; (c) `ic_engine.regime_label_unmapped` warnings are not inflated by
   season labels.
5. **APR action (Step 5).** `SHARPENS` -> keep `alpha.ic.earnings_season_conditioned = true`,
   rollback token `RETAINED`. Any other verdict -> set it `false` through `ConfigService`
   with `changed_by` and a reason citing the token and this document,
   rollback token `DISABLED`.

### Rule 2 operationalization (pinned before the Query 2 numbers were computed)

A matched triple is (in-season cell, off-season cell, unconditioned parent cell) sharing
`feature_name`, `tf`, `symbol`, `lookahead_bars`, and for cross-sectional sub-cells the parent
`regime` (the label before `__`). Per-symbol season cells (`in_season`/`off_season`, 176-04) are
matched to the per-symbol `regime_scope='pooled'` cell; cross-sectional sub-cells (176-06) to
their `regime_scope='cross_sectional'` parent. A triple counts only when the parent has
`passes_fdr = true` and all three `ic_sharpe_hac` values are non-null. For each (feature, tf),
take the median over triples of `|hac_in|`, `|hac_off|`, `|hac_parent|`. A (feature, tf)
qualifies as sharpened iff median `|hac_in|` >= 1.7x both the off-season and the parent median.
`SHARPENS` iff some feature qualifies in >= 2 tfs. `DEGRADES` iff, pooled over all triples,
median `|hac_in|` / `|hac_parent|` <= 1.1 in every tf and no (feature, tf) qualifies.
`INSUFFICIENT_N` iff fewer than 30 matched triples exist in total.

## Query 1: primitive gate

All queries run 2026-09-24 against `training_window_end = '2025-12-24 05:15:00+00'`, read-only.

```sql
SELECT feature_name, tf, regime_scope, is_pooled, count(*),
       sum(reliable::int), sum(passes_fdr::int), sum(passes_walkforward::int),
       sum((reliable AND passes_fdr AND passes_walkforward)::int) AS gate, ...
FROM feature_ic_scores
WHERE training_window_end = '2025-12-24 05:15:00+00'
  AND feature_name IN ('earnings_season_flag','days_since_quarter_end')
GROUP BY 1,2,3,4;
```

Every cell of both features is `reliable = true`; not one has `passes_fdr = true`.

| feature | tf | scope | pooled | cells | reliable | FDR | WF | gate | CI | med n_indep | mean IC | mean HAC | min BH p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| days_since_quarter_end | 5m | cross_sectional | f/t | 7830/116 | all | 0 | 1876/23 | 0 | 153/5 | 2541/1789 | -0.0062 | -0.047 | null |
| days_since_quarter_end | 5m | earnings_season | f | 1856 | all | 0 | 545 | 0 | 21 | 15438 | -0.0057 | -0.052 | null |
| days_since_quarter_end | 5m | pooled / symbol_hmm | | 928 / 2464 | all | 0 | 411 / 523 | 0 | 8 / 16 | 31692 / 2541 | -0.0068 / -0.0073 | -0.059 / -0.036 | null |
| days_since_quarter_end | 15m | cross_sectional | f/t | 7738/110 | all | 0 | 2002/34 | 0 | 114/2 | 1843/1468 | -0.0072 | -0.074 | null |
| days_since_quarter_end | 15m | earnings_season | f | 1863 | all | 0 | 558 | 0 | 11 | 8142 | -0.0061 | -0.067 | null |
| days_since_quarter_end | 15m | pooled / symbol_hmm | | 932 / 2594 | all | 0 | 345 / 626 | 0 | 8 / 47 | 22427 / 1780 | -0.0071 / -0.0072 | -0.058 / -0.077 | null |
| days_since_quarter_end | 1h | cross_sectional | f/t | 4804/67 | all | 0 | 507/8 | 0 | 68/1 | 398/401 | -0.0168 | -0.241 | null |
| days_since_quarter_end | 1h | earnings_season | f | 1814 | all | 0 | 350 | 0 | 28 | 1196 | -0.0164 | -0.060 | null |
| days_since_quarter_end | 1h | pooled / symbol_hmm | | 928 / 1499 | all | 0 | 265 / 162 | 0 | 10 / 28 | 1773 / 332 | -0.0177 / -0.0137 | -0.078 / null | null |
| days_since_quarter_end | 1d | cross_sectional | f/t | 2055/28 | all | 0 | 8/1 | 0 | 38/0 | 148/181 | -0.0193 | null | null |
| days_since_quarter_end | 1d | earnings_season | f | 1762 | all | 0 | 198 | 0 | 30 | 302 | -0.0233 | null | null |
| days_since_quarter_end | 1d | pooled / symbol_hmm | | 914 / 6 | all | 0 | 310 / 0 | 0 | 12 / 0 | 891 / 121 | -0.0220 / -0.0765 | null | null |
| earnings_season_flag | 5m | cross_sectional | f/t | 7830/116 | all | 0 | 1571/21 | 0 | 432/11 | 2541/1789 | 0.0031 | -0.007 | 0.4313 |
| earnings_season_flag | 5m | pooled / symbol_hmm | | 928 / 2464 | all | 0 | 225 / 493 | 0 | 30 / 71 | 31692 / 2541 | 0.0012 / 0.0014 | -0.010 / -0.015 | 0.7170 |
| earnings_season_flag | 15m | cross_sectional | f/t | 7738/110 | all | 0 | 1535/16 | 0 | 298/6 | 1843/1468 | 0.0023 | -0.028 | 0.5388 |
| earnings_season_flag | 15m | pooled / symbol_hmm | | 932 / 2594 | all | 0 | 235 / 536 | 0 | 46 / 71 | 22427 / 1780 | 0.0012 / 0.0024 | -0.009 / -0.008 | 0.4030 |
| earnings_season_flag | 1h | cross_sectional | f/t | 4804/67 | all | 0 | 472/9 | 0 | 209/2 | 398/401 | 0.0096 | -0.002 | 0.3183 |
| earnings_season_flag | 1h | pooled / symbol_hmm | | 928 / 1499 | all | 0 | 139 / 145 | 0 | 23 / 50 | 1773 / 332 | 0.0017 / 0.0028 | 0.006 / null | 0.1395 |
| earnings_season_flag | 1d | cross_sectional | f/t | 2055/28 | all | 0 | 2/0 | 0 | 73/1 | 148/181 | 0.0096 | null | null |
| earnings_season_flag | 1d | pooled / symbol_hmm | | 914 / 6 | all | 0 | 166 / 0 | 0 | 16 / 0 | 891 / 121 | -0.0006 / 0.0120 | null | null |

`earnings_season_flag` inside `regime_scope='earnings_season'` has null IC in every cell
(1856/1863/1814/1762 per tf): the flag is constant within an in-season or off-season partition,
so those rows are correctly degenerate.

**Why no cell entered FDR at all.** ic_engine's BH-FDR admits only one representative per
(regime, lookahead, cluster_id), the member with max `|ic_value|`; non-representatives get
`passes_fdr = false`, `bh_adjusted_p = null`.

- `days_since_quarter_end` shares a cluster with `quarter_position` in **40,308 of 40,308** cells
  and is never the representative, so it has zero `bh_adjusted_p` rows. Its FAIL is structural
  redundancy, not a measured rejection: the cluster it belongs to passes FDR in 60 cells through
  `quarter_position`. This is D-02's own concern (Spearman 0.935 with `quarter_position`)
  answered by the engine: it cannot clear its own gate while it clusters with the older feature.
- `earnings_season_flag` is the representative in only 648 cells (min BH p = 0.1395); elsewhere
  its cluster is represented mostly by `quarter_cycle_sin` (32,270 cells).
- `partial_ic` / `passes_partial_fdr` are null for both new features and for `quarter_position`
  in every row at this window, so the plan's suggested partial-IC reading is not available.

**GATE_VERDICT_EARNINGS_SEASON_FLAG=FAIL**

**GATE_VERDICT_DAYS_SINCE_QUARTER_END=FAIL**

Both primitives are reliable-N everywhere and subsumed by pre-existing calendar features
(`quarter_cycle_sin`, `quarter_position`) under the engine's cluster deduplication.

## Query 2: conditioning

SQL: Appendix A (matched triples as pinned above: in/off season cell joined to its `pooled` or
`cross_sectional` parent on feature, tf, symbol, lookahead, parent regime).

Usable triples (parent `passes_fdr` and all three HAC values non-null):

| kind | 5m | 15m | 1h | 1d |
|---|---|---|---|---|
| cross-sectional sub-cells | 432 | 893 | 555 | 514 |
| per-symbol | 3714 | 2462 | 0 | 0 |

Per-symbol 1d and 1h contribute nothing: `ic_sharpe_hac` is null on every per-symbol 1d row and
on most per-symbol 1h rows, so per-symbol conditioning at 1d, 176-01's canonical tf, is
unmeasurable under this rule.

Population-level result (median `|hac_in|` / median `|hac_parent|` over all usable triples):
5m 1.028, 15m 0.982, 1h 1.000, 1d 0.957. Off-season over parent: 0.958, 0.910, 0.998, 1.052.
Across (feature, tf) with >= 10 triples (164 of them), the median in/off ratio is 1.06, 1.04,
0.87, 0.80 (5m, 15m, 1h, 1d).

(feature, tf) qualifying under the rule: 42 of 576. Features qualifying in >= 2 tfs (the rule's
SHARPENS trigger):

| feature | tf | triples | in/off | in/parent |
|---|---|---|---|---|
| bars_since_extreme_move_fast | 5m / 15m / 1h | 2 / 9 / 5 | 2.85 / 3.79 / 4.85 | 9.24 / 2.95 / 2.70 |
| fvg_open_count | 1h / 1d | 3 / 5 | 3.88 / 2.05 | 3.34 / 3.89 |
| ob_strength | 5m / 15m | 2 / 3 | 5.48 / 2.37 | 2.33 / 1.72 |
| ret_acf1_z | 5m / 1d | 1 / 4 | 2.99 / 1.98 | 1.77 / 2.34 |
| trend_direction | 5m / 1h | 10 / 9 | 3.93 / 3.28 | 3.93 / 2.06 |
| yield_slope_momentum_product | 15m / 1h | 10 / 5 | 5.76 / 2.16 | 2.51 / 1.78 |

**CONDITIONING_VERDICT=SHARPENS**

The pinned rule fires, and it is recorded as it fired. The evidence behind it is thin, and the
document says so rather than re-deciding:

- Every qualifying (feature, tf) rests on 1 to 10 triples; the population ratio is about 1.0 in
  every tf. Six features out of 576 (feature, tf) cells clearing a two-tf bar is within what a
  rule with no minimum-N and no null arm can produce by chance.
- Mirror control (diagnostic only, computed after the token, does not change it): off-season
  >= 1.7x both in-season and parent qualifies 17 (feature, tf), 2 features in >= 2 tfs, versus
  42 and 6 for in-season; at >= 10 triples, 8 in-season versus 1 mirror. The asymmetry is real
  in count, but the in-season partition is about one third of the sample, so its per-cell
  statistics are noisier and hit extreme ratios more often under the null; the mirror is not a
  size-matched null.
- None of the six is in 176-01's 31 `SWEEP_SURVIVORS` (all vol/volume); they are structural /
  SMC / momentum features the sweep never tested.
- Raw per-symbol `|IC|` separations at 1d (largest: `range_pct_fast` 0.060 in vs 0.028 off,
  `high_52w_dist`, `parkinson_vol_z`, `garman_klass_vol_z`, `hv_ratio`, 854 triples each) show the
  same about 2x pattern that pure sample-size scaling of `|IC|` predicts (in-season n about 0.32
  of parent), so raw `|IC|` ratios are not evidence of conditioning either.

**`up_vol_body_diff`** (the feature whose A1 claim motivated this workstream):

| kind | tf | triples | parent FDR | mean IC in / off / parent | median \|HAC\| in / off / parent |
|---|---|---|---|---|---|
| cross-sectional | 5m | 84 | 4 | 0.0047 / 0.0097 / 0.0082 | 0.098 / 0.106 / 0.123 |
| cross-sectional | 15m | 108 | 16 | 0.0104 / 0.0105 / 0.0081 | 0.176 / 0.151 / 0.159 |
| cross-sectional | 1h | 113 | 3 | 0.0060 / 0.0128 / 0.0097 | 0.237 / 0.180 / 0.165 |
| cross-sectional | 1d | 114 | 9 | 0.0177 / 0.0077 / 0.0133 | 0.334 / 0.303 / 0.285 |
| per-symbol | 5m | 928 | 118 | 0.0071 / 0.0055 / 0.0060 | 0.102 / 0.089 / 0.078 |
| per-symbol | 15m | 932 | 42 | 0.0063 / 0.0063 / 0.0068 | 0.108 / 0.089 / 0.090 |
| per-symbol | 1h | 921 | 3 | 0.0092 / 0.0020 / 0.0049 | null / 0.107 / 0.098 |
| per-symbol | 1d | 908 | 3 | 0.0073 / 0.0080 / 0.0117 | null |

It does not qualify in any tf (best in/off HAC ratio 1.32x at cross-sectional 1h).

**Agreement with 176-EVIDENCE-A1.md: disagreement.** The proxy found `A1_VERDICT=CONFIRMED`
(1d pooled IC 0.0196 in vs 0.0101 off, 1.94x) and `SWEEP_VERDICT=CONFIRMED` (31 of 57 vol/volume
features). In the real gate, only the cross-sectional 1d raw mean IC reproduces the direction
(0.0177 vs 0.0077, 2.3x); the per-symbol 1d IC does not (0.0073 vs 0.0080), and on the rule's
risk-adjusted metric the feature shows 1.10x at 1d. The proxy pooled rows across symbols and
tested an IC difference with autocorrelated daily returns (D-04's caveat); the real gate
measures per-cell HAC Sharpe and finds no broad sharpening. The token's SHARPENS comes from a
different, thinly supported feature set. Answer to D-03 ("verify the number before wiring it
in"): the cheap proxy overstated the conditioning effect.

## Query 3: lifecycle

```sql
SELECT name, from_status, to_status, triggered_at FROM concept_transition_log
WHERE name IN ('earnings_season_flag','days_since_quarter_end');          -- 0 rows
SELECT count(*) FROM concept_transition_log
WHERE triggered_at >= '2026-09-23 22:47:47+00';                              -- 0
SELECT metric_name, count(*), min(evaluated_at) FROM integrity_monitor
WHERE monitor_type='ic_lifecycle' AND training_window_end='2025-12-24 05:15:00+00' GROUP BY 1;
--  guard_fail_fraction | 7 | 2026-07-22 14:56:52
--  regime_shift_fraction | 1 | 2026-07-19 14:25:24
```

The hook wrote nothing. Log: `ic_engine.lifecycle_hook_already_ran`
(`training_window_end=2025-12-24 05:15:00+00:00`, 08:17:14 UTC). The hook's Step 0
(`services/ic_engine.py` ~line 6398) short-circuits when `integrity_monitor` already holds an
`ic_lifecycle` `guard_fail_fraction`/`decay_cells_flagged` fact for the window; one was written
2026-07-22. Both concepts stay at their migration-350 genesis status `active` with no evidence
event recorded. `concept_registry` was not touched (UCR Invariant 1).

**Finding:** the idempotency key is `training_window_end` alone. Because `alpha.validation.oos_start`
pins the window at 2025-12-24 05:15, every corpus recompute since 2026-07-22 (new features,
new code, new fingerprints) has skipped lifecycle evaluation, and the last feature transitions
are dated 2026-08-05. A recompute at an unchanged window never re-evaluates lifecycle, so the two
new concepts, which fail the gate, remain `active`. Filed as todo 402.

## Query 4: isolation proof

```
_eligibility_where(False)[1] =
  symbol = 'POOLED' AND is_pooled = true AND regime != '_pooled'
  AND regime_scope <> 'earnings_season' AND ic_ci_lower > 0 AND reliable = true
  AND ic_sharpe_hac IS NOT NULL AND passes_walkforward = true AND passes_fdr = true
```

- (a) `SELECT count(*) FROM feature_ic_scores WHERE regime_scope='earnings_season'` = **2,399,040**.
- (b) the predicate AND `regime_scope='earnings_season'` = **0**. Without the
  `regime_scope <> 'earnings_season'` clause the same predicate would admit **1,339**
  earnings-season rows, so the 176-05 guard is doing live work, not guarding an empty set.
  The predicate selects 1,446 rows at this window in total.
- (c) `ic_engine.regime_label_unmapped` during the run: 0 in `logs/ic_engine.log` (04:41 onward)
  and 0 in `176-08-ic-engine.out`. `logs/ic_engine.log.1` holds 18, all at 21:02:56 on
  2026-09-23 for `training_window_end=2026-07-10`, a separate invocation 1h45m before this run
  started; none carries a season label.

## Step 5: APR action

Rule: `SHARPENS` -> retain. **CONDITIONING_ROLLBACK=RETAINED**

```
SELECT config_value FROM config_state WHERE config_key='alpha.ic.earnings_season_conditioned';
true
latest config_history: 2026-09-23 11:06:24 | version 1 | true | migration_350 |
  Seed ic_engine earnings-season conditioning switch, default on [user_preference]
```

No write made. Given the thin support above, todo 403 asks for a pre-registered re-decision
(minimum triples per (feature, tf) and a size-matched null) before the next full corpus run
pays for the conditioning passes again.

## Scope of this verdict

From `176-RECOMPUTE-LOG.md` COVERED_SCOPE: **233 symbols x 4 tfs (5m/15m/1h/1d), 932 pairs,
108,639,338 rows, `MAX(bar_ts)` 2026-09-18T19:55:00Z.** IC measured through
`training_window_end` 2025-12-24 05:15 UTC.

Earnings-season cells actually produced:

- Per-symbol (176-04): all four tfs, 229-233 symbols per tf, 300 features, in and off season.
- Cross-sectional sub-cells (176-06), from the 124 `ic_engine.season_subcell_pass` log lines:

  | tf | parent cells | sub-cells computed | skipped `disk_backed_cell` | skipped `subset_below_min_n` |
  |---|---|---|---|---|
  | 5m | 31 | 21 | 10 | 0 |
  | 15m | 31 | 27 | 4 | 0 |
  | 1h | 31 | 30 | 0 | 1 |
  | 1d | 31 | 29 | 0 | 2 |

  Pre-flight predicted most 5m and 15m cells would be disk-backed; after todo 386's exact row
  count only 14 of 62 were. Cross-sectional sub-cells cover 260 of 300 features.

### Limitations

- An OOS holdout is in effect (`alpha.validation.oos_start` = 2025-12-24T05:15:00Z); nothing
  after it was measured.
- `days_since_quarter_end` correlates 0.935 (Spearman) with `quarter_position`; the plan asked for
  its marginal contribution via `partial_ic`, but those columns are null at this window, and the
  cluster deduplication above already shows it never becomes a representative.
- D-04's autocorrelation caveat applies to the original proxy evidence (1.90x in-season, Welch
  p=5.05e-05, 67% of symbols (155/233) on the corrected 14-42-day window): daily returns inside a
  six-week block are autocorrelated, so the proxy's effective N was overstated. This gate's
  result is consistent with that caveat.
- Per-symbol `ic_sharpe_hac` is null at 1d and mostly at 1h, which removes per-symbol 1d/1h from
  the conditioning rule entirely.
- The SHARPENS token rests on the rule as pinned; the rule had no minimum-N or null arm.

## Appendix A: Query 2 SQL

```sql
CREATE TEMP TABLE trip AS
WITH s AS (SELECT * FROM feature_ic_scores WHERE training_window_end='2025-12-24 05:15:00+00' AND regime_scope='earnings_season'),
k AS (SELECT feature_name, tf, symbol, lookahead_bars,
   CASE WHEN regime LIKE '%\_\_%' THEN split_part(regime,'__',1) ELSE '_pooled' END parent,
   CASE WHEN regime LIKE '%\_\_%' THEN 'cs' ELSE 'ps' END kind,
   max(ic_sharpe_hac) FILTER (WHERE regime LIKE '%in_season') hin,
   max(ic_sharpe_hac) FILTER (WHERE regime LIKE '%off_season') hoff,
   max(ic_value) FILTER (WHERE regime LIKE '%in_season') icin,
   max(ic_value) FILTER (WHERE regime LIKE '%off_season') icoff
 FROM s GROUP BY 1,2,3,4,5,6)
SELECT k.*, p.ic_sharpe_hac hpar, p.ic_value icpar, p.passes_fdr pfdr
FROM k JOIN feature_ic_scores p ON p.training_window_end='2025-12-24 05:15:00+00' AND p.feature_name=k.feature_name AND p.tf=k.tf AND p.symbol=k.symbol AND p.lookahead_bars=k.lookahead_bars AND p.regime=k.parent
 AND p.regime_scope = CASE WHEN k.kind='cs' THEN 'cross_sectional' ELSE 'pooled' END;
\echo triples_total / usable (parent passes_fdr, all hac non-null)
SELECT kind, tf, count(*) all_trip, count(*) FILTER (WHERE pfdr AND hin IS NOT NULL AND hoff IS NOT NULL AND hpar IS NOT NULL) usable FROM trip GROUP BY 1,2 ORDER BY 1,2;
CREATE TEMP TABLE ft AS SELECT feature_name, tf, count(*) n,
 percentile_cont(0.5) within group (order by abs(hin)) mi, percentile_cont(0.5) within group (order by abs(hoff)) mo, percentile_cont(0.5) within group (order by abs(hpar)) mp
FROM trip WHERE pfdr AND hin IS NOT NULL AND hoff IS NOT NULL AND hpar IS NOT NULL GROUP BY 1,2;
\echo qualifying (feature,tf)
SELECT *, round((mi/nullif(mo,0))::numeric,2) r_off, round((mi/nullif(mp,0))::numeric,2) r_par FROM ft WHERE mi >= 1.7*mo AND mi >= 1.7*mp ORDER BY feature_name, tf;
\echo features qualifying in >=2 tfs
SELECT feature_name, count(*) FROM ft WHERE mi >= 1.7*mo AND mi >= 1.7*mp GROUP BY 1 HAVING count(*)>=2;
\echo pooled per-tf ratio (DEGRADES test)
SELECT tf, count(*), round((percentile_cont(0.5) within group (order by abs(hin)) / percentile_cont(0.5) within group (order by abs(hpar)))::numeric,3) in_over_par, round((percentile_cont(0.5) within group (order by abs(hoff)) / percentile_cont(0.5) within group (order by abs(hpar)))::numeric,3) off_over_par FROM trip WHERE pfdr AND hin IS NOT NULL AND hoff IS NOT NULL AND hpar IS NOT NULL GROUP BY 1 ORDER BY 1;
\echo (feature,tf) with n>=10 : distribution of r_off, r_par
SELECT tf, count(*) nft, round(percentile_cont(0.5) within group (order by mi/nullif(mo,0))::numeric,2) med_r_off, round(percentile_cont(0.5) within group (order by mi/nullif(mp,0))::numeric,2) med_r_par, count(*) FILTER (WHERE mi>=1.7*mo AND mi>=1.7*mp) nq FROM ft WHERE n>=10 GROUP BY 1 ORDER BY 1;
\echo top separation (median |ic_in| - |ic_off| over all triples, any parent), n>=20
SELECT feature_name, tf, count(*) n, round(percentile_cont(0.5) within group (order by abs(icin))::numeric,4) med_abs_in, round(percentile_cont(0.5) within group (order by abs(icoff))::numeric,4) med_abs_off, round(percentile_cont(0.5) within group (order by abs(icpar))::numeric,4) med_abs_par
FROM trip WHERE kind='ps' GROUP BY 1,2 HAVING count(*)>=20 ORDER BY percentile_cont(0.5) within group (order by abs(icin)) - percentile_cont(0.5) within group (order by abs(icoff)) DESC LIMIT 8;
\echo up_vol_body_diff by tf and kind
SELECT kind, tf, count(*) n, count(*) FILTER (WHERE pfdr) n_par_fdr, round(avg(icin)::numeric,4) avg_ic_in, round(avg(icoff)::numeric,4) avg_ic_off, round(avg(icpar)::numeric,4) avg_ic_par,
 round(percentile_cont(0.5) within group (order by abs(hin))::numeric,3) med_hin, round(percentile_cont(0.5) within group (order by abs(hoff))::numeric,3) med_hoff, round(percentile_cont(0.5) within group (order by abs(hpar))::numeric,3) med_hpar
FROM trip WHERE feature_name='up_vol_body_diff' GROUP BY 1,2 ORDER BY 1,2;
```
