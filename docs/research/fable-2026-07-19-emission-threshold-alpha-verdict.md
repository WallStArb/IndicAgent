# Emission Threshold Sweep and the Tradable-Alpha Question - Verdict Review

**Version:** 1.0
**Status:** answered - all five questions resolved with live evidence; verdict is a
measurement-integrity call plus a sequencing recommendation, not a redesign proposal
**Priority:** high (finds one silent data-corruption channel poisoning mean-return analyses,
and corrects two material misreadings of the first EM-CAL sweep's output)
**Milestone:** none - informs how the run_2025122405150000 results are interpreted and what
the next empirical step toward the OOS gate is
**Last Updated:** 2026-07-19
**Tags:** emission-threshold, em-cal, cost-hurdle, ensemble-ic, data-quality, forward-returns,
todo-065, todo-146, todo-148
**Source:** same-day session handoff (first full measurement-chain run against the corrected
corpus); every claim re-verified independently against live code and DB 2026-07-19 -
Author: Fable 5

**What was independently verified this review (not taken from the handoff):**

1. `_net_return_for_event` (`scripts/ops/alpha/ops_emission_threshold_sweep.py:135-140`):
   `direction_sign * forward_return - cost_hurdle`. Read directly from source.
2. `alpha.quant.cost_hurdle.{5m,15m,1h,1d}` all `0.0` in live `config_state`;
   `alpha.ic.lookahead.fast = 1`; `alpha.quant.threshold.{5m,15m,1h,1d} = 1.5/1.2/1.0/0.8`.
3. `ensemble_weights` for `weight_version='run_2025122405150000'`: exactly the 7 reported
   strata (5m: high_bear/high_neutral/low_bull/mid_bull; 15m: high_neutral/mid_bull/
   mid_neutral), zero 1h/1d rows. Meta-FDR gate confirmed in code
   (`services/ensemble_trainer.py:166-167`, min_fraction 0.50, min_cells 3).
4. `alpha_ensemble_ic` for the same weight_version: 28 (tf, regime, lookahead_bars) cells,
   27 with positive mean and median per-symbol IC, the one exception 5m/mid_bull/60
   (mean -0.0031). Per-symbol FDR pass counts match the handoff (5m/low_bull/5: 17/80 = 21%;
   5m/high_neutral/5: 11/80 = 14%; 15m: 0-1 of ~80 per cell).
5. `ensemble_alpha` coverage: 18.1M rows 5m, 2.7M rows 15m, spanning 2006-09 to 2026-07,
   80 symbols; in-sample cutoff 2025-12-24 covers the vast majority.
6. Forensic decomposition of the two headline sweep cells (queries below): 5m/low_bull at
   threshold 3.0 by symbol, 5m/high_neutral at threshold 1.8 by year.
7. Raw `market_data_ohlcv` bars behind the extreme events, and a corpus-wide scan of
   `forward_returns` for `abs(return_fast) > 0.5`.
8. `ic_engine.py` uses `scipy.stats.rankdata` (Spearman rank IC) at every IC call site -
   relevant to why IC survives what the mean-return sweep does not.
9. Cost-calibration state: `ops_cost_hurdle_calibration.py` does not exist anywhere in the
   repo (named in Phase 141.1 `deferred-items.md` as never created); execution-plan item B2a
   ("set cost_hurdle.5m/.15m to empirical P10/P25") is unchecked. There is no calibrated
   cost figure anywhere in the codebase.
10. `feature_ic_scores` for `training_window_end='2025-12-24 05:15'`: `ic_shrunk` populated
    on 30.8% of 854,299 rows (263,536). The handoff said the shrinkage batch was run; 30.8%
    is presumably the eligible-cell subset, but "eligible subset = 30.8%" was not itself
    verified. Residual flag, not a finding.

---

## Q1 - `mean_net_return` is GROSS return. No cost has been subtracted anywhere.

`_net_return_for_event` returns `direction_sign * forward_return - cost_hurdle`, and every
`cost_hurdle` is live at 0.0. So every number in the sweep table is the raw directional
executable open-to-open forward return at the `fast` horizon (1 bar), with zero deduction for
spread, slippage, or commission. The column name "net" is aspirational: it becomes net only
when `alpha.quant.cost_hurdle.{tf}` is seeded with a real value.

This changes the reading of the whole table. The correct frame is: **these are the gross
per-event edges that a cost hurdle would have to be subtracted FROM**, and they are:

- 5m pooled, best threshold: < 0.1 bp per event (displayed 0.00000, CI upper 0.00001)
- 15m pooled, best threshold: 0.2 bp per event (0.00002)
- 5m/high_neutral at 1.8 (the one granularity_earned=YES cell): 1.1 bp per event (0.00011)

Note the handoff's own characterization of 15m as "~1-2bp" is a 10x misread: 0.00002 in
return units is 0.2 bp, not 2 bp. That correction alone settles Q3's direction.

## Q2 - 5m is not "falsified vs. the IC finding". The two results are the same small signal in different units, measured at the signal's weakest horizon.

The apparent contradiction (strong IC, flat return surface) dissolves on arithmetic. Expected
per-event directional return scales roughly as IC x sigma(forward return). At the `fast`
horizon (1 bar of 5m), per-bar sigma for these ETFs is on the order of 5-15 bp, and the
pooled-across-regimes IC at 1 bar is ~0.005-0.02 (the sweep's pooled row set is dominated by
mid_bull, 3.1M rows, and high_bear, 1.5M rows, the two weakest-IC regimes). 0.01 x 10 bp
= 0.1 bp - exactly what the table shows. The sweep did not contradict the IC measurement; it
converted it into return units and confirmed its magnitude is tiny at 1 bar.

Three aggregation choices made the sweep read as flat:

1. **Horizon.** The sweep ran only at `fast` (1 bar), the horizon where measured ensemble IC
   is weakest in every cell (5m/high_neutral: 0.022 at 1 bar vs 0.049 at 20 bars, verified in
   `alpha_ensemble_ic`). The horizons where the IC actually lives (20/60 bars) were never
   swept - and cannot yet be swept cleanly, because per the same-day lookahead review
   (`fable-2026-07-19-lookahead-and-target-calibration-review.md` Q1), 5m slow/extended
   completeness is 71%/20% with a morning-only selection bias, pending todo 146.
2. **Regime pooling.** The per-regime table shows exactly the structure the IC engine
   predicted: the two strong-IC regimes (high_neutral, low_bull) select high optimal
   thresholds with positive means; the two weak-IC regimes (mid_bull, high_bear) select 0.4
   with zero. Pooling buries 3,232 high_neutral events under 6.85M near-zero ones.
3. **i.i.d. CIs.** `_sweep_stratum` computes SE as stdev/sqrt(N) over events that are heavily
   clustered - same symbol on adjacent bars, 80 symbols on the same timestamp. Effective N is
   far below nominal N; every CI in the table is materially too narrow. This cuts both ways:
   it weakens the 15m "significant" positive band AND means the flat 5m surface is even less
   informative than it looks.

**On EM-CAL's own falsification criterion:** the pooled 5m surface is flat within CI across
the grid, and the pooled 15m surface is monotone-but-overlapping, so a literal reading says
EM-CAL is falsified and the seed thresholds stand. Do not retire the script on this run. The
run was conducted at the one horizon where no threshold structure could have appeared, with
zero cost hurdle (the gate EM-CAL exists to calibrate against), and with corrupt prints in
the event set (Q4). The falsification check has not yet been run under conditions capable of
falsifying. Seed thresholds (`alpha.quant.threshold.*`) stand in the meantime.

Separate honest caveat on the best cell: 5m/high_neutral at threshold 1.8 decomposed by year
(query in appendix) flips sign repeatedly (-2.9 bp/event 2007, +3.2 bp 2021, -0.0 bp 2025),
and **2021 alone (1,019 of 3,232 events, +0.00032 mean) contributes roughly 85% of the cell's
total net edge**. The one granularity_earned=YES result in the whole report is substantially
one calendar year. Its nominal CI separation from the TF optimum should not be treated as
replication.

## Q3 - 15m's edge is 0.2 bp gross, and there is no calibrated cost figure in the repo to compare it against - but no plausible figure is below 0.2 bp.

Verified: no cost calibration has ever been done (`ops_cost_hurdle_calibration.py` never
created; B2a unchecked; `measurement-alpha-emission.md` explicitly lists cost-hurdle values as
unresolved). So the comparison must be first-principles: the tightest large-ETF round trips
(SPY-class: ~1 cent spread on ~$500, plus commission) cost >= 0.5-1 bp; the mid-liquidity
names in this 80-symbol corpus (KRE, EWT, VWO, and especially their 2006-2012 history, which
dominates row counts) cost several bp. A 0.2 bp gross edge per event is erased 5-25x over by
any defensible cost assumption. The consistency of the 15m band across thresholds is real but
irrelevant at this magnitude - and its i.i.d. CI is overstated per Q2.3 anyway.

15m at 1-bar is not a tradable edge. Whether 15m at 5/20 bars is - where measured IC rises to
0.017-0.038 - is unmeasured, same reason as Q2.1.

## Q4 - The 5m/low_bull N=260 standout is not overfitting bait. It is a single corrupt price print.

Decomposition by symbol (appendix query 1): the stratum mean of 0.01052 is UUP. UUP's 36
events have mean directional return **0.10253 with sd 0.614**; XRT's 11 events (all on
2007-09-18) have mean **-0.08785**. Every other symbol is within +/- 15 bp. Tracing UUP's
largest event: bar 2007-06-20 17:55 has `return_fast = 3.686`, i.e. a +368% five-minute
"executable" return on a dollar-index ETF. Root cause, verified in raw `market_data_ohlcv`:

```
2007-06-20 18:00  open 25.07                    volume 200
2007-06-20 19:00  open 1000, high 1000, low 28.97  volume 200   <- corrupt print
2007-06-20 19:50  open 24.08                    volume 300
```

ln(1000/25.07) = 3.686. The $1000 print has volume 200, so it **passes the
`market_data_ohlcv_tradeable` volume>0 filter** - the tradeable view guards against synthetic
fills, not corrupt prices. That single row contributes 3.686/260 = +0.0142 to the stratum
mean, i.e. MORE than the entire reported 0.01052 (ex-UUP/XRT the stratum mean is ~0.5 bp,
noise). The largest number in the whole sweep report is one bad IBKR tick from 2007.

Corpus-wide scan: 27 rows across 13 (symbol, tf) pairs have `abs(return_fast) > 0.5`
(UUP 5m/15m/1h, XRT, EZU, ITA, VUG, CWB, VWO, IPO; worst 3.73). Rare - but mean-based
analyses over small-N strata have no defense against them, and nothing in
`forward_return_writer` or the sweep filters them. Filed as todo 148 (price-sanity guard).

Two secondary observations from the same decomposition:

- The script's granularity_earned=NO verdict for low_bull was correct but for the wrong
  reason (CI overlap driven by the corrupt print's own giant variance). Right answer,
  no credit.
- The IC-side results are structurally immune to this failure: `ic_engine.py` and the
  ensemble IC path are Spearman (rankdata) throughout, so a 368% outlier is just the top
  rank. This is precisely why the IC findings survive this review and the mean-return
  numbers required forensics. Any future promotion gate based on mean returns (EM-CAL,
  FRAME-04, Kelly sizing) inherits the fragility; the rank-based layers do not.

## Q5 - Verdict

**Does IndicAgent currently have real, tradable, cost-surviving alpha? No.**

What it demonstrably has - and this survived every check I threw at it - is a small, real,
statistically coherent predictive signal: the champion ensemble's rank IC is positive in
27/28 measured cells, rises monotonically with horizon in most cells, concentrates exactly
where the feature-level IC said it would (5m high_neutral/low_bull), and a nontrivial
minority of individual symbols (up to 21% in the best cells) independently clear corpus-wide
BH-FDR. That is a genuine measurement result, robust by construction to the data faults
found here.

What it does not have is evidence that this signal survives costs. At the only horizon swept,
the gross edge is 0.0-1.1 bp per event against a >= 1-2 bp realistic cost floor that has
never actually been calibrated (`cost_hurdle` all 0.0, calibration never run). The single
best cell is ~85% one calendar year. The single largest number in the report was a corrupt
$1000 print. The horizons where the IC is strong enough that the arithmetic could plausibly
clear costs (20-60 bars, where IC x sigma reaches ~1.5-4 bp gross in the best cells) were
never swept and cannot be cleanly measured until the lookahead grid is fixed (todo 146).

**What would flip the verdict to yes:** a per-regime sweep at the hold horizon where the IC
lives (slow, 20 bars), against a spread-calibrated non-zero cost hurdle, with
timestamp-clustered standard errors and a corrupt-print guard in place, showing
5m/high_neutral (and ideally one replication cell) sustaining net-of-cost per-event return
> 0 with year-by-year sign stability - then confirmed once through the Phase 144
EnsembleICEngine OOS gate per OOS-EVAL-PROTOCOL. Nothing less.

**Highest-leverage next step** (one decisive experiment, two cheap prerequisites):

1. *Prerequisite A (day-scale):* todo 148 - price-sanity guard on forward returns; re-run the
   ~27 poisoned rows' neighborhoods. Every mean-based analysis is silently wrong until this
   lands.
2. *Prerequisite B (already filed):* todo 146 - per-tf lookahead recalibration, so a 20-bar
   5m horizon is measurable without morning-only selection bias.
3. *The experiment:* calibrate `alpha.quant.cost_hurdle.{5m,15m}` from actual spread data
   (IBKR quotes or a high/low-based estimator - the never-built B2a), then re-run this sweep
   per-regime at the slow horizon with clustered SEs. That run, not more corpus and not
   FRAME-04 simulation, is the shortest path to a promotable yes/no on economic viability.
   FRAME-04 execution realism matters only after some cell survives a calibrated hurdle.

Do not spend on downstream infrastructure before that experiment resolves - this is exactly
the "prove edge before production infra" gate, and it currently sits unresolved, not failed.

---

## Appendix - forensic queries (reproducible)

Stratum decomposition, 5m/low_bull, threshold 3.0 (mirrors the sweep's four-gate stack):

```sql
SELECT ea.symbol, count(*) AS n,
       avg(CASE WHEN ea.alpha_score>0 THEN fr.return_fast ELSE -fr.return_fast END) AS mean_dir_ret
FROM ensemble_alpha ea
JOIN forward_returns fr ON fr.symbol=ea.symbol AND fr.tf=ea.tf AND fr.bar_ts=ea.bar_ts
WHERE ea.weight_version='run_2025122405150000' AND ea.tf='5m' AND ea.regime='low_bull'
  AND ea.bar_ts < '2025-12-24 05:15+00' AND ea.effective_n >= 3
  AND abs(ea.alpha_score) > 3.0
  AND ((ea.alpha_score>0 AND ea.alpha_ci_lower>0) OR (ea.alpha_score<0 AND ea.alpha_ci_upper<0))
  AND fr.return_type='executable_open_to_open' AND fr.complete_fast AND fr.return_fast IS NOT NULL
GROUP BY ea.symbol ORDER BY n DESC;
```

Same shape for 5m/high_neutral at 1.8 grouped by `date_trunc('year', ea.bar_ts)` (year
concentration), and the corpus scan:

```sql
SELECT symbol, tf, count(*), max(abs(return_fast))
FROM forward_returns
WHERE return_type='executable_open_to_open' AND abs(return_fast) > 0.5
GROUP BY symbol, tf;
```

## References

- `scripts/ops/alpha/ops_emission_threshold_sweep.py` - the sweep under review
- `docs/research/measurement-alpha-emission.md` - EM-CAL spec and falsification criterion
- `docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md` - same-day
  lookahead-grid findings this verdict depends on (Q2.1, prerequisite B)
- `docs/plans/OOS-EVAL-PROTOCOL.md` - the only path a calibrated threshold may take to OOS
- `.planning/todos/pending/146-lookahead-grid-per-tf-recalibration.md`
- `.planning/todos/pending/148-forward-return-corrupt-print-guard.md` - filed by this review
- `.planning/phases/141.1-*/deferred-items.md` - record that cost-hurdle calibration was
  deferred and never built
