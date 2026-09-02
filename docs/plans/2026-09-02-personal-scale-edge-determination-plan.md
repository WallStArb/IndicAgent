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

(Appended as workstreams complete; every number lands here with its script and date,
per the verdict-registry rule.)
