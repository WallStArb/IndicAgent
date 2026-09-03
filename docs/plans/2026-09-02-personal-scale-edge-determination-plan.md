# Personal-Scale Edge Determination — Program Plan (pre-registered)

**Status:** Active program. Pre-registered 2026-09-02 before any workstream number exists.
**Current position (2026-09-02):** 0a/0b/0c run; pre-registration 1 (`range_pct_fast_xs_ls_h5`)
DEAD; remaining queue = workstream 2 (the 15m residual diagnostic) and the todo 368 successor
decision; 0c complete (todo 367 closed 2026-09-02: Phase 148's construction KILLED ON
PAPER, gap_z recorded, screen spread-anchor 10x bug found and fixed, no verdict flipped).
**Author:** Claude (Sonnet 5), interactive session, 2026-09-02.
**Origin:** User directive 2026-09-02: "it feels like we have been drifting aimlessly for
weeks, we need to figure out how to push past this hump." Council review (same session)
rejected two earlier framings: (1) coverage was initially sequenced as parallel housekeeping,
corrected to a precondition; (2) the cost hurdle was initially a table, corrected to a
horizon-axis function. User directive the same session resolved the gates question: gate
STRUCTURE stays rigid (null-arm, BH-FDR, pre-registration, OOS); what changes is the ruler's
constants (personal-scale, not institutional) and one new axis (holding period).
**Gates status:** 5/5 discovery-track candidates DEAD; both regime-stratification candidates
DEAD; N1 confirmed structural-inconclusive; Phase 148 Gate 1 PASS / Gate 2 FAIL; Phase 167
retracted. The falsification queue is empty. This program is the plan for what comes next.

---

## The empirical observation that shapes this program

Found live 2026-09-02, from existing `feature_ic_scores` (pooled, 1d, reliable cells):

| lookahead_bars (days) | FDR-passing cells | cell count |
|---|---|---|
| 1 | 62 | 8104 |
| 2 | 86 | 8104 |
| 5 | 162 | 8104 |
| 10 | 124 | 7172 |

Measured signal mass roughly doubles from 1d to 5-10d horizons, and the carrying features
change family: not momentum, but range/volatility/position (`range_to_close`,
`range_pct_fast`, `ctf_regime_align`, `atr_z`, `bars_since_high`, `hurst`,
`yang_zhang_vol_z`). Meanwhile turnover at a 5-10d horizon is 5-10x lower than at 1d, so the
cost hurdle is easiest exactly where signal mass peaks. The weeks of short-horizon
falsification were testing the wrong corner of the (signal × horizon) space.

Integrity check performed before trusting this: `canary_acausal_placebo` (deliberate
positive control, feature_factory.py:1950) passes strongly at all horizons with IC decaying
~1/sqrt(N) exactly as a 1-day-perfect signal should. It is registered `status='candidate',
enabled=false` and cannot reach promotion paths (Invariant 1). The long-horizon measurement
path is therefore validated, not contaminated.

**Scope boundary (user-set):** the TF stack is 5m→1d by design; 1d is the top. The horizon
search space is the bands the corpus already measures: 1h/20-60 bars, 1d/5-10 days. No HTF
swing system; going past ~2 weeks is a different project (universe-expansion branch, not
this program).

## Workstreams

### 0a — Library dimensionality (the breadth number)

Two questions, pure analysis on existing `feature_ic_scores`:

1. **Effective rank** of the IC-correlation matrix across measured features (pooled, 1d,
   fixed lookahead, training-window time series): how many independent signals does the
   ~250-feature library actually contain? Method: Marchenko-Pastur noise ceiling on the
   eigenvalue spectrum (same unsupervised method as `statistical_factor_residual`'s
   K-selection, reused deliberately).
2. **Family independence:** is the 5-10d range/vol family's IC time series independent of
   the momentum family's? If yes, it is new breadth; if not, it is the same signal in
   different clothes and the breadth math does not improve.

### 0b — The personal hurdle function (the ruler)

Net-of-cost Sharpe as a **function** of (IC, breadth, signal autocorrelation, horizon,
cost), not a table: IC requirements and turnover are coupled (slow signal = low turnover =
low hurdle), so the hurdle must be evaluated per candidate per horizon.

**Pre-registered cost assumptions (committed BEFORE any candidate is placed against the
output; changing any of these after seeing a placement invalidates the placement):**

- **Spread estimation:** Corwin-Schultz (2012) high-low estimator from existing 1d OHLC,
  per symbol, time-averaged over the trailing window.
- **Spread validation anchor:** one-off live top-of-book snapshot for ~20 liquid symbols
  via the (working) ib-gateway, client ID per `src/providers/ibkr.py` conventions.
  Validation passes if the median ratio (CS estimate / live quoted spread) on the
  validation set falls within [0.5, 3.0]; CS is documented to overestimate on less-liquid
  names, so the band is asymmetric-tolerant upward. If validation fails, the estimator is
  declared unusable and live-derived spreads are used for the validation symbols only, with
  the failure recorded; no silent fallback for the rest.
- **Commissions:** IBKR tiered, USD 0.0035/share, min USD 0.35/order, cap 1% of trade
  value (personal accounts).
- **Market impact:** explicitly negligible at personal clip sizes (100-1000 shares) in
  the liquid-ETF universe that dominates this corpus; stated, not ignored.
- **Turnover:** measured from actual feature-rank membership churn in `feature_vectors`
  per horizon band, not assumed.

Deliverable: the hurdle function over the TF stack's horizon bands, ready to evaluate any
candidate's (IC, breadth, autocorr, horizon) tuple.

### 0c — Paper placement (kills candidates before code)

Place what is ALREADY measured against the 0b hurdle: the 5-10d range/vol mass, the N1
residual, the `alpha_score` demeaned residual, `gap_z`, Phase 148's Gate-1-passing
construction. Each exits with one of three verdicts: **killed on paper**, **advanced**,
or **needs-a-construction** (signal mass clears the hurdle but no construction exists to
falsify). No new measurement runs in this workstream; it consumes 0b's function and
existing numbers only.

### 1 — Coverage fix (todos 280+283 merged)

Route all active symbols into regime groups: seed `instrument_tags` for the ~115 untagged
2026-08 expansion symbols with definitional (human/ITR) priors, enable routing so
single-name equities stop being invisible to regime-stratified IC. The `ic_engine`
recompute is **deferred to the decision gate** so it runs once, for whichever branch wins.

### 2 — The 15m residual diagnostic (the one ready falsification)

The residual-stripping construction's pre-registered diagnostic-tier test
(day-clustered bootstrap / shuffled-null / BH-FDR at 15m), a prerequisite before any new
gate_id run per todo 278's resolution (a completed 2026-08-08 decision todo; this
diagnostic is the work that resolution mandates, not an open todo itself).
Runs unchanged and in parallel. No post-hoc parameter moves (the N1 lesson).

### 3 — Decision gate (the anti-drift mechanism)

Pre-registered NOW, before any number exists:

1. **A construction passes its falsification AND its (IC, breadth, autocorr, horizon)
   tuple clears the 0b hurdle** → promote to formal gate re-run. That phase is scoped via
   `/gsd-discuss-phase` when triggered. This is the proven construction Phase 168 and
   156-159 have been blocked on.
2. **0c shows measured signal mass clears the hurdle but no construction exists** →
   exactly ONE new construction is designed and pre-registered for that band. This is not
   "candidate #6": measurement says where, the hurdle says what is required, and the
   construction is the last step, not the first.
3. **Nothing clears the correctly-calibrated hurdle** → KILL CRITERION fires: "this
   corpus, at breadth ~8 and this TF stack, cannot carry the endgame." Universe expansion
   becomes primary via its own scoping phase. This is a final answer, not an invitation to
   recalibrate again.

## Governance

- **Verdict registry:** construction verdicts get `concept_registry` rows with
  `domain='construction'` at verdict time (name, verdict, numbers, script, date). No new
  table; reuses the existing governance system. Ends the "which verdict is current" drift.
- **Gate structure unchanged:** null-arm controls, BH-FDR, pre-registration, OOS
  discipline, Invariant 1. What changed is the ruler's constants and the horizon axis,
  both pre-registered here.
- **Harness extraction** (todo 365) happens on the scripts' next touch, never
  mid-falsification.
- **Execution track:** no GSD phase for the workstreams themselves (research track, per
  this repo's planning-system separation). The decision gate's winning branch earns its
  phase.

## Results

### 0a — Library dimensionality, run 2026-09-02

Script: `scripts/analysis/feature_library_dimensionality.py` (interpretation bands
pre-registered in its docstring before running). **The library's predictive content is
CONCENTRATED; the range/vol long-horizon family is genuinely NEW breadth.**

- **IC-profile (predictive) effective rank: MP-K=7** of 244 measurable features
  (participation ratio 17.3). The ~250-feature library contains about SEVEN independent
  predictive signals — most features are the same few signals in different clothes.
  Within-family correlation confirms it: the momentum family's 27 features correlate
  +0.435 with each other (roughly 1-2 real signals), while the range/vol family's 69
  members sit at +0.037 (noise floor at T=84 symbols is ~0.11, so "no detectable shared
  structure").
- **Range/vol vs momentum: mean cross-family IC-profile correlation -0.003 → INDEPENDENT**
  (pre-registered bar: < 0.3, APR `alpha.regime_stratification.max_correlation`). The
  5-10d range/vol signal mass is not the momentum signal in different clothes; it is
  additional independent breadth.
- **Value-space (informational) rank: MP-K=48** of 244 columns (80,762 sampled 1d rows,
  T=80,762; participation ratio 28.0). The library spans ~48 orthogonal information
  directions but only ~7 carry independent predictive content — massive informational
  redundancy, concentrated predictive value.
- **Breadth math, per-period framing (see caveat):** IC-profile rank 7 × universe breadth
  4.5-8.4 = 32-59 simultaneous bets. At measured per-cell ICs (0.03-0.055), the
  per-period IR ceiling is 0.17-0.38.
- **Caveat for 0c, flagged not hidden:** the fundamental law's breadth is INDEPENDENT
  BETTS PER YEAR, which includes periods/year — at a 5-day horizon there are ~50
  rebalances/year, so annualized breadth is (universe × signals × effective periods),
  with "effective" discounted by signal autocorrelation at that horizon. The per-period
  numbers above therefore UNDERSTATE annualized IR; the honest placement (workstream 0c)
  must use measured signal autocorrelation at each horizon band to convert to effective
  annual bets. Both the cost side (lower turnover) and the breadth side (fewer periods)
  of slower horizons are now first-class in the hurdle evaluation.

Coverage caveat, stated: per-symbol IC profiles exist for the 85 routed symbols only
(todos 280/283); workstream 1's coverage fix will widen this measure.

### 0b — Personal hurdle function, run 2026-09-02

Script: `scripts/analysis/personal_cost_hurdle.py` (assumptions pre-registered in the
program doc and the script's docstring before running).

**Corwin-Schultz FAILED validation and is declared unusable** — pre-registered rule
applied. 20 live top-of-book quotes pulled through `IBKRProvider` (client 48): median
live spread **1.4 bps**; median CS/live ratio 15.7x, far outside the pre-registered
[0.5, 3.0] band. The estimator measures volatility, not bounce, on this tiny-spread
universe. Live levels are the anchor; sensitivity band 0.7 / 1.4 / 2.8 bps.

**Turnover, measured from actual cross-sectional ranks** (not assumed):
`range_to_close` 0.160-0.170 per rebalance at H=1-10 (nearly horizon-independent);
`ctf_momentum` 0.081 (H=1) rising to 0.230 (H=10).

**The hurdle table's headline: at H=5-10, the WORST-CASE personal IC_min is ~0.003-0.004**
(2.8bp spread × lib_rank 3 × low universe breadth), and the mid-band IC_min is ~0.001-0.002.
Even at H=1 the range family's worst-case hurdle is ~0.028.

**Placement against measurement (informal 0c preview):** the range/vol family's measured
avg ICs at H=5-10 are 0.03-0.055 — roughly an order of magnitude above the worst-case
personal hurdle. **The cost hurdle is not the binding constraint at personal scale.**
The institutional-calibrated Gate 2 that killed Phase 148 was measuring the wrong trader:
at 1.4bp spreads, negligible impact, and 0.7bp commissions, slow low-IC signals clear
costs easily.

Both items formerly listed here as the critical path are closed: (1) the annualized
breadth/IR question is consumed by 0c's bet accounting (periods/year and the
autocorrelation discount are in the screen); (2) decision rule 2's construction
(`range_pct_fast` XS-LS @ H=5) ran and returned DEAD.

### 0c — Paper screen, run 2026-09-02

Script: `scripts/analysis/personal_edge_paper_screen.py`. **Design per user direction:
the library is a flat, theory-free panel of primitives — no family grouping, no thesis
layer. The shortlist is every FDR-passing pooled cell the corpus's own measurements
already produced.** Standalone accounting (per the user's correction that edge does not
require orthogonality; correlation only limits combination credit, a separate later
question): bets = universe breadth × periods/year × autocorrelation discount (1.0/0.5),
spread band anchored on the measured 1.4bp live level, verdict = worst case across ALL
assumption bands.

- One implementation bug caught and fixed before recording anything: the first run passed
  the band multipliers as spread fractions, producing absurd IC_min values (~10); the
  corrected run is what is recorded here.
- **Second bug, found and fixed 2026-09-02 (later the same day, during the Phase 148
  placement): the screen's `_LIVE_SPREAD_ANCHOR` was 0.0014 (14 bps), a 10x transcription
  of 0b's measured live median 0.000138 (1.4 bps; cache re-verified).** The bug was
  conservative — every IC_min was computed with 4-7x too-large one-way costs — so no
  verdict flips: the re-run reproduces 208/208 clears and the same 87 broad-support cells.
  Recorded margins were understated by the same factor and are corrected below. 0b's own
  hurdle table was unaffected (it used the live median directly).
- **Result: 208 FDR-passing (feature, H) cells at 1d; all 208 clear the worst-case
  standalone personal hurdle; 87 with per-symbol support ≥ 10 symbols.** Corrected
  margins 8.8x to 207x (previously recorded as 1.25x-29x on the bad anchor). The
  deliberate look-ahead canary tops the raw margin list (validating the screen's
  mechanics; excluded from candidacy). H=5-10 dominates high margins; H=1-2 clusters at
  the low end (min 8.8x) — the turnover-drag story in one table, unchanged in shape.
- **Selection rule (pre-registered): margin AND cross-symbol sign consistency.** The sign
  check eliminates several high-margin names (`range_vs_atr`, `efficiency_ratio_slow`,
  `realized_var_ratio_fast`: ~50/50 per-symbol sign splits — their pooled numbers are
  regime-mix artifacts).
- **Selected: `range_pct_fast` @ H=5.** 210/60 positive per-symbol cells (78% sign
  consistency), per-symbol avg IC +0.057, 27/85 symbols with their own CI>0, robust 30-cell
  pooled measurement (avg pooled IC 0.027), worst-case hurdle margin ~12.9x at the broadest
  measurement on the corrected anchor (~42.9x on the screen's own H=5 cell avg 0.0906).
  A pure bar-range primitive, theory-free per the program's stance.
- Stated caveat, not hidden: these measured ICs come from `feature_ic_scores` at a single
  training window (2025-12-24). The screen SHORTLISTS; it does not verdict. Decision rule
  2's construction gets a fresh falsification (day-clustered bootstrap, shuffled-null,
  BH-FDR) before anything is claimed.

**Decision rule 2 fires: exactly ONE construction will be designed and pre-registered —
`range_pct_fast` cross-sectional LS at H=5** (sign inherited from the pre-registered
screen; the falsification run is the fresh test). Per the program's approval discipline,
the pre-registration is written and reviewed before that run executes.

**`gap_z` verdict line (todo 367 item, recorded 2026-09-02 from the corrected screen):**
`gap_z` @ H=1 is among the 208 placed cells — avg IC 0.1039, worst-case margin 23.4x,
per-symbol support 3 of 85 → **CLEARS (thin support)**. A single-cell, 3-symbol feature:
real by the screen's ruler but not standalone construction material; it stays on the
shortlist as combination input, not as a decision-rule-2 candidate.

### Phase 148 placement — KILLED ON PAPER, 2026-09-02

Script: `scripts/analysis/phase148_personal_hurdle_placement.py` (todo 367's substantive
remainder; existing numbers only). Verdict registered in `concept_registry`
(`domain='construction'`, `phase148_alpha_score_directional`, migration 328).

Phase 148's Gate-1-passing per-symbol directional construction (`alpha_score`) fails the
personal hurdle on **every** (tf, scale) cell under the screen's pre-registered
worst-case band rule, and — decisive, band-independent — **Gate 2's realized OOS frame
P&L was NEGATIVE gross of personal costs** (mean −0.1215 R, Sharpe 0.385, max-dd 9.60
over 33,892 frames / 69 OOS days). A lower cost hurdle cannot rescue a construction
whose gross mean return is negative: 0b's "wrong trader" insight creates room for slow
low-IC constructions with POSITIVE gross edge — Phase 148's intraday construction is not
one. Placement inputs, all measured: unbiased all-cell mean OOS rank-IC per cell
0.000-0.050 (the 0.031-0.180 qualifying-cell means are selection-inflated — 140 cells
chosen from 640 by BH-FDR, the exact trap the discipline exists to catch); sign
co-firing 100.0% at 15m/1h/1d (todo 277) → ONE systematic directional bet per rebalance
(bets band 1-2, measured 1); intraday horizons → 504-19,656 rebalances/yr; worst-case
IC_min 0.024-1.64 per cell. Turnover is unmeasured for `alpha_score`; the band spans the
program's two measured anchors (0.08 daily-feature to 0.45 quintile-construction), and
the kill does not rest on it: 5 of 8 cells fail even the MOST favorable band, and the
gross-negative Gate 2 fact is turnover-independent.

Caveat recorded, not a reopening: the 15m mid/slow/extended and 5m extended cells clear
the MOST favorable band by 4.7-11.7x — that mass is the demeaned-residual thread's, and
workstream 2's 15m diagnostic (todo 278's design) is the properly-powered test of it.
This verdict kills the RAW construction only.

**Scope against todo 367 (0c's todo): fully executed as of this placement.** All five
items resolved: (1) 5-10d range/vol mass — placed, decision rule 2 fired, pre-reg 1 DEAD;
(2) `gap_z` — verdict line above; (3) `alpha_score` demeaned residual — superseded by
workstream 2's stronger diagnostic; (4) N1 residual — blocked on structural instability
(todo 364); (5) Phase 148's construction — KILLED ON PAPER above. Todo 367 closes.

### Pre-registration 1 run — DEAD, 2026-09-02

Script: `scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py` (amended design,
commit 0c9a344dd), read-only, run once. Panel 920,411 rows / 231 symbols, 690
settled-at-zero returns, 931 rebalances (offset 0), 0 skipped.

- **The cross-sectional association is real:** shuffled-null p = 0.0010 (N=1000); gross
  LS mean +22.5 bp/rebalance, CI [+9.2, +35.1] bp.
- **It is a beta tilt, not a market-neutral edge:** OLS on the EW-universe mean gives
  beta +1.14, R² = 0.75 — exactly the Phase 148 failure mode the amendment's
  neutralization criterion targets. The neutralized intercept is +4.9 bp/rebalance and
  is net-negative at ALL 9 spread × borrow combos once personal costs apply (measured
  one-way turnover 0.45/rebalance, 2.6× 0b's 0.17 rank-churn prior — AGY finding 9
  vindicated; commissions 2.8-3.2 bp/side at $100k quintile breadth). Cheapest-corner
  net CI [−7.9, +5.8] bp.
- **Stability fails:** net-at-anchor negative in 2/3 subperiods (only 2019-2025
  positive).
- **Offsets 1-4 agree:** all five neutralized-net means negative at anchor cost (betas
  1.08-1.20).
- **Attribution (reported, ungated):** 52/231 symbols pass per-symbol BH-FDR, 47 with
  CI lower bound > 0 (BNTX, SDOG, SCHD at the top) — per-name signal mass exists; the
  XS-LS construction is what fails.
- **Verdict registered** as the first `concept_registry` `domain='construction'` row
  (migration 329, renamed from 320 after a number collision with the commodity regime APR migration): `range_pct_fast_xs_ls_h5`, status deprecated.

Per the pre-registration's DEAD branch: no successor is auto-promoted. Any successor
needs its own pre-registration and must address why the sign-consistency-selected leader
failed: market-beta loading plus personal-scale costs on a 0.45-churn quintile
construction. The program's remaining queued falsification is workstream 2 (the 15m
residual diagnostic from todo 278's closed design, unchanged).

---

## Pre-registration 1 — `range_pct_fast` XS-LS @ H=5 (decision rule 2)

Written 2026-09-02, after 0c, before any construction statistic was computed. Every
researcher degree of freedom is locked here; the falsification script's docstring restates
this section verbatim-by-reference before its first run.

**Amendment 1 (2026-09-02, pre-run).** Amended after the AGY adversarial review (archived
at `.planning/research/2026-09-02-agy-review-range-pct-fast-prereg.md`); no IS or OOS
statistic of this construction existed at amendment time. Original text: commit 9507829b9.
Adopted: the OOS tripwire now evaluates all 5 stride phases on net returns; eligibility no
longer conditions on return completion (LEFT JOIN, missing returns settle at 0);
beta-tilt neutralization added as a PASS criterion (intercept net of costs); bootstrap
block=2 rebalances with a percentile CI; stability upgraded to net > 0 in 3/3 subperiods
at anchor cost; log returns converted to simple before leg means; the $0.35/order minimum
commission modeled at $100k account equity; anchor locked to the first date with >= 20
eligible names, with all 5 stride offsets reported as ungated robustness; short-leg
borrow band {0.25, 0.5, 1.0} bp per rebalance added; permutation null raised to N=1000;
the OOS gate look appends `.planning/gate_look_log.jsonl` (D-04) alongside
`gate_evaluations`. Not adopted: AGY's R²-cap form of Gate 2, because the
intercept-net-of-costs criterion is strictly stronger here (it tests profitability net of
market beta directly instead of capping exposure share); oos_start stays 2025-12-24
(resolved above). Footnote: 0b's 0.17 turnover prior is mean |Δ rank|, a different metric
from quintile-membership churn; this run measures the churn itself and reports it.

### Construction spec

- **Signal:** `range_pct_fast` as persisted in `feature_vectors` (tf=1d, the single live
  `pipeline_version`): (rolling 20-bar high − rolling 20-bar low) / close, window from APR
  `feature.breakout.range_window_fast=20`. No re-computation, no winsorizing, no
  transforms — the stored column is the signal.
- **Sign (inherited from 0c, locked):** LONG the top quintile (high recent range), SHORT
  the bottom quintile. 0c measured +0.057 avg per-symbol IC, 78% sign consistency.
- **Portfolio:** quintile buckets by cross-sectional rank each rebalance day (ties broken
  by symbol name, deterministic); equal-weight within each leg; spread = mean(long leg) −
  mean(short leg); dollar-neutral by construction.
- **Cadence:** non-overlapping, every 5th trading day. Anchor = the first eligible date
  whose cross-section is >= 20 symbols, locked with no search. Hold exactly 5 trading
  days. All 5 stride offsets (anchor + 0..4 positions in the eligible-date calendar) are
  evaluated; offset 0 is primary, offsets 1-4 are reported as ungated robustness against
  calendar-phase luck.
- **Return (Invariant 1):** `forward_returns.return_mid` (APR
  `alpha.ic.lookahead.mid=5`, `return_type='executable_open_to_open'`), read via LEFT
  JOIN with no `complete_mid` filter: eligibility must not condition on return
  completion at T. A name whose return is missing settles at 0 in the leg means (halt,
  delisting, or a hold straddling the persisted-returns endpoint; 693 panel rows, all at
  the 2025-12 tail, verified pre-run). Log returns convert to simple (`e^r − 1`) before
  any averaging or cost arithmetic; per-rebalance LS return = mean(long simple) −
  mean(short simple). IS reads persisted rows; the OOS gate look computes the same
  quantity ON THE FLY from `market_data_ohlcv_tradeable` opens via the canonical
  `forward_log_return()` (todo 253's sanctioned pattern — the normal pipeline never
  persists past `oos_start`, by design, and nothing in this program populates it).
- **Eligibility per rebalance day:** a non-null signal row at T (row presence is the
  tradability proxy: the feature requires a tradeable bar). ≥ 20 eligible symbols or the
  date is skipped and counted in the report; a skipped date is omitted from the sample
  (no zero-fill) and the stride continues on the global eligible-date calendar.
- **Universe:** all 231 equity-ETF symbols present in `feature_vectors` at 1d (verified
  single asset class 2026-09-02). No regime routing filter — the verdict must cover the
  full active universe. Survivorship properties are the corpus's own, not this test's.

### Sample windows (fixed)

- **IS (this falsification):** 2007-03-23 → 2025-12-24 (`alpha.validation.oos_start`;
  also the persisted forward_returns endpoint). ~950 rebalances. Selection consumed this
  window; this run is the acknowledged selection-biased test. Its defenses: the
  shuffled-null, 0c's FDR-controlled screen lineage, and worst-case cost bands.
- **OOS (the one-shot gate look, ONLY if IS passes):** 2025-12-24 → 2026-08-12 (holdout,
  untouched by every selection measurement — structurally, via the clamp). ~32
  rebalances per stride phase; all 5 phases evaluated. Recorded to `gate_evaluations`
  under `gate1_range_pct_fast_xs_ls_h5` and appended to
  `.planning/gate_look_log.jsonl` (D-04), never re-run. **No holdout statistic of any kind —
  including the interim diagnostic scorer — is computed between this pre-registration and
  that look.**
- **oos_start does not move** (resolved 2026-09-02, user question): the 12/24 anchor is a
  calendar-convention artifact of Phase 141 (~6 months back from its choosing date) —
  data-content-blind, which is what a holdout boundary must be. Re-anchoring would
  convert virgin holdout into training data for ~2% IS sample gain, shrink OOS from ~7.5
  to ~5.3 months, and renegotiate a boundary with 7 consumed looks against it
  (`gate_evaluations`: Phase 148/166/167 gates).

### Costs (0b's model, amended: the retail minimum binds)

One-way cost = spread/2 + commission frac. Spread band {0.7, 1.4, 2.8} bp around 0b's
measured 1.4 bp live anchor. Commission frac per rebalance = max(0.0035/share at the $50
assumed price, $0.35 order minimum / per-name notional) at $100k account equity, $50k
per leg; the minimum binds at quintile breadth (~3.2 bp/side at k=46, vs 0.7 bp for an
institutional clip). Turnover = actual one-way quintile-membership churn measured in the
run (0.5 × Σ |Δ w|; the entry rebalance pays 1.0; terminal liquidation is not charged;
0b's 0.17 prior is mean |Δ rank|, context only). Short-leg borrow: {0.25, 0.5, 1.0} bp
per rebalance on short-leg notional. Net per-rebalance LS return = gross − 2 × turnover
× one_way_cost − borrow. Equity held flat at $100k (no compounding). The PASS rule spans
all 9 spread × borrow combinations; anchor cost (stability and robustness tables) =
1.4 bp spread + 0.5 bp borrow.

### Statistical protocol

Primary estimator: the beta-neutralized mean per-rebalance LS return. Neutralization:
OLS of the per-rebalance gross LS series on the equal-weight universe mean over the same
eligible cross-section and window (the market-factor proxy; `range_pct_fast` is a
vol/beta proxy, and long-high-range/short-low-range carries positive market beta in a
bull sample, the exact Phase 148 failure mode). Beta is estimated once on the full IS
sample; the neutralized series is gross_t − beta × ewm_t, whose mean is the regression
intercept. Reported alongside, never gated: beta, regression R², unneutralized gross and
net means. The OOS gate look applies the IS-estimated beta with no re-estimation.

CI: circular block bootstrap on the rebalance series, block_size=2 rebalances (10
trading days; the daily-calibrated block=10 would span 50 days on this non-overlapping
series), B=2000, percentile interval at 95%, seed `hash_key_to_int` on the construction
name (codebase RNG convention, never builtin `hash()`). Applied to the neutralized net
series at each of the 9 cost combinations.

Null: within-rebalance-date cross-sectional permutation of the signal (breaks the
signal→return link, preserves return distribution and cross-sectional dependence),
N=1000 replicates, one-sided empirical p = (1 + #{null mean ≥ observed}) / (N + 1),
same seed policy, evaluated on the gross mean.

**PASS rule — all three, else the construction is DEAD:**
1. Neutralized-net mean, bootstrap CI lower bound > 0 at ALL 9 spread × borrow
   combinations (worst case across bands, per 0c's convention).
2. Shuffled-null p < 0.05 (gross).
3. Stability: neutralized-net mean > 0 in 3/3 equal subperiods (rebalance-index thirds)
   at anchor cost.

Reported, never gated: per-symbol Spearman IC family with BH-FDR
(`ic_math.apply_bh_fdr`, alpha=0.05) as attribution (0c's 27/85 was the routed subset;
this is the fresh full-universe count; rank IC is invariant to the log→simple change);
per-subperiod means; skipped-day count; the 5-offset robustness table.

**Pre-registered OOS interpretation rule (amended; tripwire, not a significance test):**
the gate look evaluates ALL 5 stride phases in the OOS window (~160 rebalance
evaluations). Returns are net at anchor cost, beta-neutralized with the IS beta. OOS is
CONSISTENT iff (i) the pooled all-phase OOS net mean has the same sign as the IS
neutralized-net mean AND is ≥ 0.5× it (`alpha.validation.oos_significant_drop_fraction`,
the pre-committed drop tolerance), and (ii) at least 4 of 5 phase-level net means are
positive. AGY's calibration: a single 32-rebalance phase passes the pre-amendment rule
~40% of the time under a zero-edge null; pooling phases plus the phase-level sign
requirement is materially more conservative. Consistency is a promotion tripwire, not
evidence of edge; inconsistency blocks promotion. No post-hoc reinterpretation of a
disappointing or encouraging OOS number.

### Fixed quantities

quintiles=5 · min cross-section=20 · stride=5 trading days · anchor=first date with
≥ 20 eligible · block=2 rebalances · B=2000 · N_null=1000 · alpha=0.05 · subperiods=3
(net, 3/3) · spread band {0.7, 1.4, 2.8} bp · borrow band {0.25, 0.5, 1.0} bp/rebalance ·
equity $100k · commission = max(0.7 bp, $0.35 / per-name notional) per side · seeds via
`hash_key_to_int("range_pct_fast_xs_ls_h5…")`.

### Execution & verdict

Script: `scripts/analysis/range_pct_fast_xs_ls_h5_falsification.py`, read-only, design
locked in its docstring before running. Harness note (todo 365): this script reuses
`src/intelligence/statistics/ic_math.py` primitives as-is; extraction happens on next
touch elsewhere, never here mid-falsification.

Verdict (PASS→ADVANCED / FAIL→DEAD) lands in `concept_registry` as the first
`domain='construction'` row (name `range_pct_fast_xs_ls_h5`, verdict, numbers, script,
date) via a post-run registration step — the falsification script itself writes nothing.

ADVANCED → decision rule 1: the formal gate re-run (one-shot OOS look above) gets its
own execution phase, scoped via `/gsd-discuss-phase`; it extends the Phase 167
`cross_sectional_spread_tracker` gate pattern to `return_mid` with on-the-fly returns.

DEAD → no successor is auto-promoted. 0c's other 86 cells were not pre-registered as a
fallback queue; any successor needs its own pre-registration and must address why the
sign-consistency-selected leader failed.

**Invalidations:** any fixed quantity moved after an IS number is seen; a second IS run
with tweaked parameters presented as the verdict (the N1 lesson); any holdout statistic
computed before the gate look.
