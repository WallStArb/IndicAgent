# Personal-Scale Edge Determination — Program Plan (pre-registered)

**Status:** Active program. Pre-registered 2026-09-02 before any workstream number exists.
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

### 2 — Todo 278's 15m diagnostic (the one ready falsification)

The residual-stripping construction's pre-registered diagnostic-tier test
(day-clustered bootstrap / shuffled-null / BH-FDR at 15m), per todo 278's closed design.
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

What remains unresolved (and is now the program's critical path): (1) the annualized
breadth/IR question — 0a's per-period IR ceiling understates annualized IR by ignoring
periods/year, and 0c must compute the autocorrelation-adjusted annual number before any
verdict; (2) whether a real construction on the range/vol family survives falsification
(decision rule 2).

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
- **Result: 208 FDR-passing (feature, H) cells at 1d; all 208 clear the worst-case
  standalone personal hurdle; 87 with per-symbol support ≥ 10 symbols.** Margins 1.25x to
  29x. The deliberate look-ahead canary tops the raw margin list (validating the screen's
  mechanics; excluded from candidacy). H=5-10 dominates high margins; H=1-2 clusters near
  1.3x — the turnover-drag story in one table.
- **Selection rule (pre-registered): margin AND cross-symbol sign consistency.** The sign
  check eliminates several high-margin names (`range_vs_atr`, `efficiency_ratio_slow`,
  `realized_var_ratio_fast`: ~50/50 per-symbol sign splits — their pooled numbers are
  regime-mix artifacts).
- **Selected: `range_pct_fast` @ H=5.** 210/60 positive per-symbol cells (78% sign
  consistency), per-symbol avg IC +0.057, 27/85 symbols with their own CI>0, robust 30-cell
  pooled measurement (avg pooled IC 0.027), worst-case hurdle margin ~1.8x at the broadest
  measurement. A pure bar-range primitive, theory-free per the program's stance.
- Stated caveat, not hidden: these measured ICs come from `feature_ic_scores` at a single
  training window (2025-12-24). The screen SHORTLISTS; it does not verdict. Decision rule
  2's construction gets a fresh falsification (day-clustered bootstrap, shuffled-null,
  BH-FDR) before anything is claimed.

**Decision rule 2 fires: exactly ONE construction will be designed and pre-registered —
`range_pct_fast` cross-sectional LS at H=5** (sign inherited from the pre-registered
screen; the falsification run is the fresh test). Per the program's approval discipline,
the pre-registration is written and reviewed before that run executes.
