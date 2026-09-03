# Phase 148 Promotion Decision: Alpha Scoring System OOS Proof Gates

Author: Claude Sonnet 5 (GSD executor, phase 148-05), synthesizing two independent
irreversible gate runs against live production data. Human sign-off obtained mid-execution
for the `forward_returns` backfill described below (see Gate 1 section).

Status: FINAL. Both gates recorded in `gate_evaluations`. Per D-04 (`docs/plans/OOS-EVAL-PROTOCOL.md`),
neither gate can be re-run for this milestone.

## Purpose

This document synthesizes the two independent OOS proof gates Phase 148 exists to produce:
**Gate 1 (signal proof)** -- does `alpha_score` predict forward returns out-of-sample? -- and
**Gate 2 (execution proof)** -- does the frame simulation capture that signal as real P&L
out-of-sample? It also records the SCORE-04 v2.x comparison note and the overall promotion
decision.

## Gate 1: Signal Proof (SCORE-02)

**Verdict: PASS.** Recorded in `gate_evaluations` (`gate_id='gate1_signal'`,
`run_ts=2026-07-22T21:02:22Z`).

`ops_oos_gate1_signal_eval.py` measured rank-IC between `alpha_score` and four forward-return
horizons (`return_fast/mid/slow/extended`) across every (symbol, tf, scale) cell in the active
80-symbol universe, on the OOS side of `ensemble_alpha` (`bar_ts >= alpha.validation.oos_start`,
2025-12-24T05:15:00Z), using the same Fisher-z CI + BH-FDR methodology `ensemble_ic_engine.py`
already applies in-sample.

**Evidence:**

- 640 (symbol, tf, scale) cells computed, all 640 reliable (`n_valid >= min_reliable_n=100`;
  actual `n_valid` ranged 536-7,455, mean ~4,105) -- **zero cells returned insufficient-N.**
  This is a materially different outcome from what was anticipated going into this plan
  (a partial insufficient-N fraction due to a short OOS window); see the pre-run blocker below
  for why the actual outcome differs.
- 140 of 640 reliable cells (21.875%) qualify (BH-FDR-corrected `p < 0.05` AND
  `ic_ci_lower > 0`) against `alpha.ensemble_ic.min_qualifying_fraction = 0.02` (2%) -- passes
  with more than 10x margin over the threshold.
- Qualifying-cell breakdown by timeframe/scale:

  | tf  | scale    | n_cells | n_qualifying |
  |-----|----------|---------|--------------|
  | 5m  | fast     | 80      | 6            |
  | 5m  | mid      | 80      | 11           |
  | 5m  | slow     | 80      | 14           |
  | 5m  | extended | 80      | 34           |
  | 15m | fast     | 80      | 0            |
  | 15m | mid      | 80      | 27           |
  | 15m | slow     | 80      | 21           |
  | 15m | extended | 80      | 27           |

  Signal concentrates at longer lookaheads (`extended` scale) and largely absent at `5m/fast`
  and `15m/fast` -- consistent with a slower-moving ensemble alpha signal, not a
  microstructure-timing one.

**Pre-run blocker, resolved before this gate ran (full disclosure, not a footnote):** the
mandated `--dry-run` pre-flight (run before any irreversible action, per this plan's own
safety protocol) initially returned `input_population_row_count=0` -- a total absence of data,
not the "some cells insufficient-N" scenario anticipated. Root-caused: `forward_returns`
(joined by Gate 1's fetch query) had **zero rows** with `bar_ts >= alpha.validation.oos_start`
for any of the 320 registered (symbol, tf) pairs, despite raw bar data existing 7+ months past
that boundary. This traced to `forward_return_writer.py`'s Phase 141.1 OOS-holdout clamp
(`docs/plans/OOS-EVAL-PROTOCOL.md`) apparently never having been overridden to compute the OOS
side of that label table. Execution halted at this point rather than spending Gate 1's one
irreversible shot on a definitionally-empty result. After explicit human sign-off, `forward_returns`
was backfilled (`forward_return_writer.py --training-window-end 2026-07-07T16:45:00Z`, full
active universe, no threshold or parameter changes -- purely populating a previously-missing
raw label table; the in-sample side was untouched, protected by `ON CONFLICT DO NOTHING`). This
is why the ACTUAL Gate 1 run found zero insufficient-N cells rather than the partial
insufficiency this plan's own text anticipated: once the label substrate existed, the 7-month
OOS window had ample data per cell, and the earlier "insufficient" dry-run result was pure data
absence (a missing prerequisite), not signal absence -- per `OOS-EVAL-PROTOCOL.md`'s own
"diagnose data absence vs. signal absence" framing, these are two different things and must not
be conflated.

**Coverage limitation, disclosed (found after this irreversible run had already recorded its
verdict, cannot be corrected by re-running per D-04):** all 640 cells are `5m`/`15m` only.
`tf='1h'` produced zero cells and `tf='1d'` produced zero cells -- not because of
insufficient-N, but because `ensemble_alpha` itself has **zero rows** with
`bar_ts >= alpha.validation.oos_start` at `tf='1h'` for any weight_version, and zero at
`tf='1d'` for the weight_version this run resolved to (`run_2025122405150000`, which has
identical 5m/15m row counts to `143.1-08-champion` and may be an alias for the same underlying
scoring run). This is a distinct, pre-existing gap in ensemble scoring coverage -- not a defect
in this gate's methodology, and not something a re-run could fix even if D-04 permitted one
(the data to score simply is not there). Filed as
[todo 173](../../.planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md) for
separate investigation. **The recorded PASS verdict is accurate for what it measured (5m/15m
signal proof) but is not a full 4-timeframe signal proof** -- stated plainly here rather than
implied to cover more than it does.

## Gate 2: Execution Proof (SCORE-03)

**Verdict: FAIL.** Recorded in `gate_evaluations` (`gate_id='gate2_execution'`,
`run_ts=2026-07-23T00:26:31Z`, strictly after Gate 1 per D-02). Zero `gate_id='FRAME-04'` rows
exist -- per D-08, this single row satisfies both SCORE-03 and Phase 142B's frame-quality gate.

Per D-06, this evaluation adopts the champion's (`weight_epoch='143.1-08-champion'`)
already-measured population rather than re-deriving an equivalent computation from scratch and
presenting it as a fresh look: 33,892 closed primary frames across 69 OOS trading days,
unchanged since the original 143.1-08 measurement (confirmed via `alpha_frames.measured_at` --
every row is the same 2026-07-21 batch).

### The five SHADOW-REVIEW criteria, as actually evaluated

| # | Criterion | Threshold | Value | Verdict |
|---|-----------|-----------|-------|---------|
| c1 | Minimum sample | >= 60 OOS days | 69 days | **PASS** |
| c2 | Mean P&L CI lower bound | > 0 | -0.1214896346368989 | **FAIL** |
| c3 | Sharpe | > 0.5 annualized | 0.38512018365944 | **FAIL** |
| c4 | Max drawdown ratio | < 0.25 | 9.596266492204732 | **FAIL** |
| c5 | No IC-Sharpe cliff (via `c7_confident_loss` proxy) | no confident loss | `confident_loss=False` | **PASS** |

**3 of 5 criteria fail** -- matching D-06's "known going in" framing exactly. This was known
before Gate 2 ran (D-06 disclosed it up front from the 143.1-08 pooled numbers), not discovered
as a surprise during execution.

Criterion 5's literal definition (`last_20d_IC_Sharpe / full_period_IC_Sharpe >= 0.5`) is N/A
on this champion population -- no recurring `ensemble_ic_engine` cadence exists to form a
trailing-vs-full-period split. `c7_confident_loss` (short-side confident-loss tail: fails iff
`n_short > 0` and short-side bootstrap CI upper bound < 0) is adopted as its documented
operational proxy, explicitly labeled as such in the evidence -- not silently dropped, not
silently substituted for the literal criterion without disclosure.

### c4 (max drawdown): a real reproducibility finding, and its resolution

The first real-run attempt at Gate 2's `--dry-run` pre-flight reproduced c2 and c3 exactly
against the frozen `143.1-08-SHADOW-VALIDATION.md` section 7 baseline, but c4 came back
`9.597283167649175` against a cited baseline of `9.598299843093644` -- a ~0.001 absolute
difference, four orders of magnitude past this plan's 1e-6 reproduction tolerance. Per this
plan's own safety protocol, execution halted rather than proceeding to the irreversible real
run on an unexplained divergence.

**Root cause:** the champion OOS population has ~22-way ties at the `bar_ts` grain (33,892
rows across only 1,534 distinct `bar_ts` values -- multiple symbols' frames opened at the exact
same 5-minute bar, i.e. genuinely SIMULTANEOUS positions, not sequential ones). `c4` is computed
via a cumulative-sum equity-curve walk (`_max_drawdown`), a path-dependent statistic sensitive
to row order. Both the original `phase143_1_08_shadow_validation.py` script and the new Gate 2
script fetched this population with `ORDER BY bar_ts ASC` and no tie-break, so the frozen
baseline itself was never a reproducible ground truth -- it was whatever chunk-scan interleaving
TimescaleDB's parallel scan across 1,034 child chunks happened to produce on 2026-07-21, not a
stable number.

An initial fix (a deterministic `frame_id` row-level tie-break) made the query reproducible but
was the wrong fix conceptually: treating same-`bar_ts` frames as sequential via ANY row
ordering -- arbitrary-but-consistent included -- is not economically meaningful. A real
portfolio holding N concurrent positions experiences their combined P&L simultaneously at that
instant, not one after another. **The correct fix**, implemented in
`scripts/analysis/score03_gate2_execution_eval.py`: aggregate (SUM) `counterfactual_pnl_r`
across all frames sharing the same `bar_ts` FIRST, producing one P&L value per distinct
timestamp, THEN run the cumulative-equity/drawdown walk over that aggregated series. This
eliminates the tie-break question structurally -- after aggregation there is exactly one row
per `bar_ts`, so `ORDER BY bar_ts` alone is fully deterministic and economically correct.

This produced a third distinct number: `9.596266492204732` (reproducible across independent
runs to ~1e-15 float-summation noise, well within tolerance). **The verdict is unaffected under
every method tested** -- `9.598` (frozen baseline), `9.597` (unfixed re-run), `9.606` (arbitrary
tie-break), and `9.596` (correct aggregation) are all catastrophic drawdowns (~960% of peak
cumulative R) against a 0.25 threshold. This was never a borderline call under any of the four
numbers.

A related order-sensitivity symptom (not fixed here, tracked separately) surfaced in the
regime-stratified companion's cluster-mean array construction -- see below and
[todo 172](../../.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md).

### Regime-stratified companion (D-07, mandatory -- pooled verdict never stands alone)

Only 2 of 8 champion (direction, regime) cells clear `min_clusters=20` day-coverage; both
evaluated cells fail:

| direction | regime | n_frames | n_clusters | coverage | ci_lower |
|-----------|--------|----------|------------|----------|----------|
| long | high_bear | 153 | 11 | insufficient | -0.122 |
| long | high_neutral | 21,563 | 19 | insufficient | -0.579 |
| long | low_bull | 51 | 6 | insufficient | -0.538 |
| **long** | **mid_bull** | **6,934** | **37** | **evaluated** | **-0.077 (FAIL)** |
| long | mid_neutral | 4,996 | 7 | insufficient | ~-0.006 (unstable, see below) |
| short | high_neutral | 42 | 5 | insufficient | -0.869 |
| short | low_bull | 3 | 1 | insufficient | nan |
| **short** | **mid_bull** | **150** | **23** | **evaluated** | **-0.278 (FAIL)** |

**What the regime breakdown reveals about WHY the pooled number failed:** todo 165 proved on
this exact data (regime-stratified re-evaluation, `143.1-08-SHADOW-VALIDATION.md` section 7)
that a pooled single-window verdict is structurally blind to regime-conditional edge -- shorts
profited in the COVID crash, were breakeven through the 2022 bear market, and lost money
specifically in the one rally window (`mid_bull`) tested here. The two cells with enough
day-coverage to evaluate are both `mid_bull` -- the specific regime the champion's OOS window
happens to land in -- and both fail. This is not evidence that the underlying signal is
worthless everywhere; it is evidence that the champion's OOS window is a narrow, single-regime
sample that cannot speak to regime-conditional performance the pooled number implicitly claims
to represent. Six of eight cells lack enough independent day-clusters to say anything at all.

**Order-sensitivity caveat (disclosed, not fixed in this plan):** the `long/mid_neutral` cell's
`ci_lower` was observed to drift across independent re-runs of the same script
(`-0.006660639938119944` -> `-0.006587583828354219` -> `-0.006455963676706368` -- no two runs
matching), traced to `frame_gate_passes`/`evaluate_frame_gate`'s cluster-mean array construction
being insertion-order-dependent (Python dict iteration order feeds a fixed-seed
`scipy.stats.bootstrap` resample). This cell is `coverage=insufficient` and excluded from the
aggregate `c2_regime_stratified_passes` verdict, so it did not affect Gate 2's result -- the two
cells that DO count (`mid_bull` long/short) matched exactly across every run in this
investigation. Filed as
[todo 172](../../.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md)
for a broader sweep of path-dependent statistics elsewhere in the codebase, not blocking this
gate.

## Independence Statement

Gate 1 and Gate 2 are two independent measurements answering two different questions. Gate 1's
PASS (does `alpha_score` predict forward returns?) does not imply or excuse Gate 2's FAIL (does
the frame simulation capture that signal as tradeable P&L?), and Gate 2's FAIL does not
retroactively cast doubt on Gate 1's signal-proof methodology. A signal can be real (Gate 1)
while the specific stop/target/hold execution rules simulated in `alpha_frames` fail to capture
it profitably (Gate 2) -- that is exactly the kind of question splitting Phase 142A (signal)
from Phase 142B (frame) was designed to answer separately, and this record preserves that
separation rather than conflating a signal failure with an execution failure or vice versa.

## SCORE-04: v2.x Comparison Note

Documentation only -- no numeric comparison. No live v2.x comparison population exists: the
v2.x I1-I7 real-time pipeline (`indicagent-intelligence-pipeline.service`) has been `failed`
since 2026-07-17 with its `ExecStart` pointing at a deleted file, and zero v2.x plugins were
ever promoted or evaluated against a live-promotion criteria document analogous to
`docs/plans/SHADOW-REVIEW.md`. There is no v2.x `alpha_score`, `alpha_frames`, or equivalent
counterfactual-P&L artifact to measure against these same five criteria. SCORE-04 is satisfied
by this documentation-only note, per the 2026-07-19 operator call downgrading it from a
comparison requirement to a disclosure requirement.

## Overall Promotion Decision

**Do not promote the v3.0 AlphaEngine to live trading capital at this time.**

Rationale, grounded in both gate verdicts:

- Gate 1 establishes real, measurable signal in `alpha_score` against forward returns
  out-of-sample (21.875% of reliable cells qualify against a 2% floor, concentrated at longer
  lookaheads) -- the foundational "is there anything here" question has a genuine PASS answer,
  at least for the 5m/15m timeframes actually measured (see the Gate 1 coverage limitation
  above; 1h/1d remain unmeasured, not failed).
- Gate 2 establishes that the specific frame simulation (stop/target/hold execution rules
  currently calibrated for the champion ensemble) does not capture that signal as profitable
  out-of-sample P&L under the frozen `SHADOW-REVIEW.md` criteria -- 3 of 5 criteria fail
  decisively (not a close call under any of the four `c4` numbers measured during this
  investigation), and the regime-stratified companion shows the OOS window's coverage is too
  narrow (2 of 8 cells, both `mid_bull`) to characterize regime-conditional performance with
  any confidence.
- Per this project's core value ("Alpha must be demonstrated empirically before any ensemble
  weight is assigned... nothing sizes a live trade until the alpha behind it has survived
  out-of-sample"), a real signal that the current execution simulation cannot yet turn into
  profitable trades is not a promotable system. Promoting on Gate 1 alone while Gate 2 fails
  decisively would mean sizing live capital against a frame/execution design already shown, on
  this exact OOS data, not to work.

**Diagnosing WHY Gate 2 failed and whether a frame/execution recalibration could fix it is
explicitly out of scope for this record and this phase** -- per `148-CONTEXT.md`'s deferred
scope, that is real follow-on work for a future phase, not something to propose or begin here.
This record's job is to produce the verdict and the diagnostic evidence (which it has, in full,
above), not to fix a failing frame.

## References

- `gate_evaluations` table: `gate_id IN ('gate1_signal', 'gate2_execution')`
- `.planning/gate_look_log.jsonl` -- both gates' pre-run integrity snapshots
- `.planning/milestones/v3.1-phases/148-alpha-scoring-system/148-CONTEXT.md` -- D-01 through D-08
- `.planning/milestones/v3.1-phases/143.1-measurement-and-eligibility-integrity-fisher-z-ci-bootstrap-/143.1-08-SHADOW-VALIDATION.md`
  sections 6-7 -- the champion's original pooled/regime-stratified measurement, cited per D-06
- `docs/plans/SHADOW-REVIEW.md` -- the frozen five criteria
- `docs/plans/OOS-EVAL-PROTOCOL.md` -- run-once cadence, data-starvation-is-diagnostic rule
- [todo 172](../../.planning/todos/pending/172-path-dependent-frame-statistics-order-sensitivity-sweep.md) --
  path-dependent statistics sweep, filed from this record's c4 investigation
- [todo 173](../../.planning/todos/pending/173-ensemble-alpha-1h-1d-oos-scoring-gap.md) --
  `ensemble_alpha` 1h/1d OOS coverage gap, filed from this record's Gate 1 coverage limitation
