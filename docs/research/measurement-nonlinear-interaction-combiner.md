# Non-Linear Interaction Combiner — Idea (Edge Source Thesis nonlinear_interaction_combiner)

**Status:** Un-archived 2026-08-03 (same day it was archived) — this thread is active again, not
historical, and is currently the most promising open Signal-Extraction thread on
`docs/research/data-edge-source-thesis.md` (see that doc's Scorecard). What changed since
archival: todo 243/245 found the tree's headline 1h uplift was 90.6% driven by a CTF batch-join
lookahead leak, not genuine non-linear structure (small real residual survives, ~15x smaller
than published). That finding, plus the tree's demonstrated lack of a per-feature contribution
cap (unlike the linear ensemble's 20% cap), is an open question against this doc's own design:
whether an unconstrained gradient-boosted tree is the right model for interaction discovery here
at all, versus a regime-conditional linear approach using the same per-feature-cap discipline.
Do not treat this doc's original "Proposed test" section below as the recommended design — the
"Pre-registered test designs" section (N1/N2) below supersedes it.

**Corrected 2026-08-24: N1/N2 are READY TO RUN, not blocked — all 3 shared preconditions are now
met.** This status block previously said the path-forward verdict was "pending the in-flight
15m/5m CTF-leak diagnostics (todo 245)" — todo 245 closed 2026-08-04 with 1h/15m/5m all measured
(see the main doc's Scorecard/§nonlinear_interaction_combiner), which was precondition 2's exact
blocker. Precondition 1 (todo 243's join fix) and precondition 3 (todo 240's linear-ensemble
baseline) are also both already landed. **Neither N1 nor N2 has actually been run** — this is
the next concrete step on this thread, not still-blocked design work.
**Author:** Claude (Sonnet 5), interactive session, 2026-07-25 — not a Fable dispatch. Originally
written as a design proposal, nothing tested yet; that's no longer true, see "What was actually
built and measured" below (added 2026-08-03).
**Origin:** Raised in conversation while resolving the fork in `.planning/STATE.md` ("invest in
better features/signal (Phase 164/165) ... or accept this branch has no OOS-detectable edge")
— specifically, the question "what other signal construction approaches exist, if this is how
Renaissance/Jane Street-style quant systems work at their core."
**Companion to:** `docs/research/data-edge-source-thesis.md` (this is candidate thesis **nonlinear_interaction_combiner**)
and `docs/research/trade-construction-layer.md` (nonlinear_interaction_combiner's sibling candidate — cross_sectional_relative_value changes the
*construction*, nonlinear_interaction_combiner changes the *combiner*; both are cheaper to test than Phase 164/165's
feature expansion and both attack the current champion population directly).

---

## The core point

`ensemble_trainer.py` combines the 150 `feature_vectors` features into `ensemble_alpha` via a
linear, shrunk-IC-weighted sum: each feature's weight is a function of that feature's own
marginal IC, computed independently of every other feature. This can express "feature X
predicts returns." It cannot express "feature X predicts returns only when feature Y is above
its 70th percentile" — any conditional or interaction structure across features is invisible to
a linear combiner by construction, not by omission. Nothing in the roadmap currently tests
whether that structure exists.

This isn't hypothetical: it already happened once, in miniature. `regime` (the per-symbol HMM
state) is the one interaction axis the system explicitly models — every IC measurement is
already stratified by it, precisely because "feature X's effect depends on regime Y" was
considered important enough to build first-class stratification for. Todo 179 (2026-07-24)
tested that one axis exhaustively — 234 cells across all 9 cross-sectional regimes × 6
symbol_hmm states × 3 lookahead scales — and found nothing that survives OOS replication (see
`docs/research/data-edge-source-thesis.md`, T2, now falsified). If the one interaction the
system already builds explicit machinery for shows nothing, the open question is whether the
other ~11,000 pairwise combinations among the remaining 149 features (that the linear combiner
never gets to evaluate at all) contain anything — not "are our features good enough," but "is
our combiner even capable of seeing the answer."

## Why this is a *specific* processing thesis, not "our ML is better"

`docs/research/data-edge-source-thesis.md` explicitly rules out generic claims of model
superiority — "our ML is better" is not an edge thesis, it's marketing. The claim here is
narrower and falsifiable: **the current combiner is linear; a non-linear combiner over the
identical inputs can express a specific class of structure (interactions/thresholds) that the
linear one structurally cannot; if that structure exists in this data, a non-linear combiner
will show a measurable, significant uplift; if it doesn't, it won't.** That's a testable
processing-advantage claim in the same sense T2 (regime-conditional structure) was — it just
turned out T2's specific instance was empty.

## Proposed test (v1, deliberately small)

Renaissance principle applied: prove the effect exists before building any production
infrastructure around it. This is a measurement experiment, not a new service.

1. **Model:** gradient-boosted trees (LightGBM or XGBoost — shallow depth, strong
   regularization) over the same `feature_vectors` corpus `ic_engine`/`ensemble_trainer`
   already read, predicting the same `forward_returns.return_type = 'executable_open_to_open'`
   target. A shallow neural net is a secondary option; trees are preferred first because
   feature importance / SHAP interaction values are directly interpretable and this project's
   "silent wrong answers are worse than loud crashes" principle favors an inspectable model
   over a black box for a first pass.
2. **Same corpus, same target, same OOS windows** as the linear ensemble — no new data, no
   new features. This is purely a combiner swap, isolating the variable under test.
3. **Same evaluation discipline as everything else in this project:** walk-forward CV (never
   k-fold on IID rows — bars are autocorrelated, exactly the trap the day-clustered bootstrap
   in todo 179 was built to avoid), day-clustered bootstrap CI on the OOS Sharpe/IC uplift,
   BH-FDR correction if multiple model variants are tried.
4. **Comparison metric:** OOS Sharpe/IC of the tree-based combiner vs. the existing linear
   shrunk-IC ensemble, on identical folds, identical cost assumptions. The question is the
   *delta*, not the tree model's absolute performance.
5. **Byproduct, not the primary goal:** SHAP interaction values (or gain-based feature
   interaction importance) would show *which* feature pairs the tree model leans on, if any.
   This is directly useful for the 164/165 decision even if the tree combiner itself is never
   promoted to production — if the tool finds strong interactions only among features that
   *already exist*, that's evidence the bottleneck was the combiner, not a missing primitive,
   and reframes what Phase 164/165 should even be built to capture.

## What was actually built and measured (added 2026-08-03)

This proposal's "not yet tested" framing (Author line above) is stale — it was built and run
repeatedly between 2026-07-26 and 2026-08-03. Recorded here so this doc is a real implementation
record, not just the original pitch; `docs/research/data-edge-source-thesis.md`
§nonlinear_interaction_combiner remains the source of truth for the full narrative and every
number as it evolved.

**Model actually used (`scripts/analysis/_nonlinear_interaction_combiner_shared.py`,
`fit_and_score_tree()`), close to but more specific than the proposal's "shallow depth, strong
regularization":** LightGBM (`lgb.LGBMRegressor`) with `n_estimators=200`, `max_depth=4`,
`num_leaves=15`, `min_child_samples=200`, `learning_rate=0.05`, `reg_alpha=1.0`, `reg_lambda=1.0`,
`subsample=0.8`, `colsample_bytree=0.8`. Walk-forward folds via `build_walk_forward_folds()`
(`_pooled_panel_folds()` after todo 239's fix), day-clustered bootstrap CI via
`circular_block_bootstrap_ic_serial`, BH-FDR correction corpus-wide -- all matching the proposal's
evaluation-discipline requirement (item 3 above).

**Scripts, in the order they were actually run:**
`nonlinear_interaction_combiner_lightgbm_check.py` (1h, 2026-07-26, first result) ->
`_replication_1d.py` (2026-07-26) -> `_replication_15m.py` (2026-08-01, after an OOM root-cause
fix to the shared matrix-fetch code) -> `_replication_5m.py` (2026-08-03, two OOM attempts, one a
real LightGBM float16-upcast bug, one host-wide memory contention, both root-caused not
guess-fixed) -> `nonlinear_interaction_combiner_ctf_leak_diagnostic_1h.py`/`_15m.py`/`_5m.py`
(2026-08-03, the with/without-CTF-columns diagnostic below).

**Linear-ensemble baseline arm added late (todos 239/240, commit `816032e2`), closing the gap
between item 4 above ("vs. the existing linear ensemble") and what every run had actually
compared against (`ctf_momentum` alone):** `fit_linear_ensemble_weights()`/
`score_linear_ensemble()`, a fold-local linear combiner reusing `ensemble_trainer.py`'s own
shrunk-IC weighting, **capped at `_LINEAR_MAX_FEATURE_WEIGHT = 0.20` per feature** -- the same
20% ceiling production's `alpha.ensemble.max_feature_weight` enforces. The tree has no equivalent
cap. That asymmetry turned out to be load-bearing, not cosmetic (see next section).

**Results by tf (tree vs. `ctf_momentum`, cross-sectional-neutral point_ic, pre-CTF-leak-fix):**
1h 0.1822, 15m 0.2506 (80/80 symbols clear CI and BH-FDR), 1d 0.0127 (small; 1d's own
`ctf_momentum` baseline separately known-degenerate, todo 189). Read at the time: "substantial at
1h/15m, small at 1d." **That read is now known to be wrong for a reason the SHAP-interaction
byproduct (item 5) never surfaced:** `ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` all
shared a batch-join lookahead bug (todo 243) -- the tree, with no per-feature cap, leaned on
those 3 leaky columns at feature-importance 400+ (one of its most-relied-on inputs). The
with/without-CTF diagnostic at 1h (todo 245, 2026-08-03) found the tree's edge **collapsed 90.6%
(0.1811 -> 0.0171)** once those 3 columns were excluded from training; `n_pass_fdr_positive` fell
80/80 -> 21/80. A small, real, statistically significant residual survives (tree-linear
diff=0.0106, ci_lower=0.0064) -- ~15x smaller than published, not a total null. Same diagnostic
running now at 15m/5m (1h's result does not auto-generalize).

**Path forward, pending the 15m/5m diagnostics landing:** the tree's core failure mode here --
no per-feature cap, so it over-indexed on whichever input happened to be contaminated -- is a
structural argument against an unconstrained gradient-boosted tree for interaction discovery,
not just a bug to patch around. Leaning toward: retire this track once 15m/5m confirm the same
pattern, and pursue interaction structure instead through regime-conditional linear models (the
existing per-symbol HMM regime / cross-sectional `regime_group` stratification, already
production-proven in Phase 144/167) with the same 20%-per-feature cap discipline the linear arm
already has -- bounded, interpretable, and structurally unable to quietly overfit to one
contaminated column the way the tree just did, twice now (this and the original 2026-07-26
canary-leakage near-miss, item below).

## Overfitting risk — the load-bearing caveat

`docs/research/data-edge-source-thesis.md`'s "Breadth Is the Binding Constraint" section
originally assumed this universe's effective breadth at ~8-15 (58 correlated ETFs); actually
measured 2026-08-07 at ~4.5 (80-ETF-only) to ~8.4 (full post-expansion universe) via
`scripts/analysis/effective_breadth_diagnostic.py` -- same order of magnitude, real number now.
A tree model with
access to 150 features over a modest-breadth, autocorrelated-bar universe is exactly the
overfitting setup this project's principles explicitly warn against ("resist overfitting,"
"earn promotion through proof p<0.05, sufficient N"). Controls, non-negotiable before any
result here is trusted:

- **Walk-forward CV only** — never a random/IID split. Bars within a day are highly correlated;
  todo 179's day-clustered bootstrap discipline is the template.
- **Strict regularization** — shallow trees (max_depth 2-4), high min-samples-per-leaf relative
  to effective breadth, L1/L2 leaf-weight penalties. The goal is a model that can express
  interactions, not one that memorizes noise across 150 dimensions.
- **The uplift itself must clear a bootstrap CI + BH-FDR bar**, exactly like every other result
  in this project — a tree model beating the linear ensemble on a single fold is not evidence,
  it's the multiple-comparisons trap this project has been burned by before (`low_bull`×
  `trending_down`'s two initially-promising cells, todo 179).
- **No promotion to production without the same OOS/shadow-mode gates** every other component
  in this pipeline goes through (Phase 142B frame simulation, `gate_evaluations`, cost hurdle).
  A promising tree-based uplift is a research finding, not a green light to swap the live
  combiner.

## Is an unconstrained tree the right instrument at all? (critique, added 2026-08-03)

Extends the "Overfitting risk" section above with what the CTF-leak finding (todo 245, table in
"What was actually built and measured") actually teaches. The claim here is stronger than "there
was a bug": **even with a perfectly clean corpus, an unconstrained depth-4 GBM over ~250 raw
columns is a poor instrument for the specific hypothesis this doc states**, for four reasons that
are properties of the algorithm and this corpus, not of the leak.

### 1. The naive capacity objection is weaker than it looks; run the arithmetic before using it

Worth doing honestly, because "trees overfit" is the lazy version of this argument and it is not
the real problem. `n_estimators=200` x `num_leaves=15` bounds the model at 3,000 leaf values.
Effective sample is not the raw row count (2,254,176 at 1h, 8,824,030 at 15m, 25,443,790 at 5m,
counted live 2026-08-03): rows are a pooled ~80-symbol panel whose cross-section carries
effective breadth ~8-15 per `data-edge-source-thesis.md`'s "Breadth Is the Binding Constraint,"
so 1h's ~28,000 distinct `bar_ts` x ~10 effective independent bets is on the order of 280,000
effective observations, not 2.25M. Against 3,000 leaves that is still roughly 90 effective
observations per parameter. **Raw capacity is not the binding problem.**

What *is* binding is the signal-to-noise budget. At the IC magnitudes this corpus actually
produces (0.01-0.05), true explained variance is on the order of IC^2, i.e. 1e-4 to 2.5e-3. The
standard in-sample-inflation rule of thumb (a heuristic, not a theorem: fitted R^2 inflates by
roughly p_effective / n_effective) puts the tree's overfit term at ~3,000/280,000 ≈ 1.1e-2,
**one to two orders of magnitude larger than the effect being searched for**. Walk-forward CV
still gives an honest OOS number, so this does not invalidate the measured ICs. What it means is
subtler and worse: the tree's *choice of which structure to encode* is made almost entirely off
noise. Whatever it carries into the held-out fold is close to an arbitrary draw from an enormous
hypothesis space, except where one input has anomalously high apparent SNR. Which is exactly what
happened.

### 2. The observed failure mode is the algorithm working as designed, not a bug it happened to hit

Gradient boosting is a greedy variance-reduction search. Given ~250 columns whose true ICs are
near-uniformly tiny and one column family with anomalously high apparent SNR, the split criterion
will allocate a disproportionate share of its 3,000 leaves to that family. That is the intended
behavior of the estimator. It was measured directly here: `ctf_momentum` at gain importance 400+
across all 5 folds of the 1h run, against a median real feature's gain importance of 2.0
(the latter recorded during todo 184's canary work, quoted in
`data-edge-source-thesis.md` §nonlinear_interaction_combiner). Removing the three contaminated
columns collapsed the tree 0.1811 -> 0.0171 (90.6%) while the capped linear arm moved only
0.0163 -> 0.0065.

Generalize the mechanism, because the specific bug is now fixed and the mechanism is not: **any**
column with anomalously high apparent SNR gets the same treatment. This corpus has produced at
least four distinct classes of such column in about six weeks, all documented:

1. lookahead contamination (the CTF batch-join, todo 243);
2. fixed-membership factor exposure (each ETF's own persistent drift, caught 2026-07-26 and
   fixed by causal per-symbol demeaning);
3. silently degenerate computation under a parameter change (`ctf_momentum` at 1d collapsing to
   a same-tf RSI, todo 189);
4. stale values from deleted code paths (`hmm_duration`'s K3 residue, todo 236).

The relevant number is therefore not "is the corpus clean today" but "what is this corpus's
defect base rate, and what is the combiner's worst-case exposure to a single defective column."
The linear arm answers the second question by construction: `_LINEAR_MAX_FEATURE_WEIGHT = 0.20`
plus cluster deflation (`_LINEAR_MAX_CLUSTER_CORR = 0.80`, `_LINEAR_MAX_CLUSTER_WEIGHT = 0.40`,
`_nonlinear_interaction_combiner_shared.py:68-72`) bounds any one column at 20% of the score.
The tree has no answer at all; `colsample_bytree=0.8` is not one, since a column withheld from
one tree remains available to the other 199. On a corpus with a nonzero, empirically confirmed
defect rate and 249 registered features still under active expansion (Phase 164/165 added ~100
columns in the week before these runs), **an unbounded-exposure combiner is mis-specified as a
matter of risk management, independent of whether today's specific leak is patched.**

### 3. The instrument searches a space ~4,500x larger than the hypothesis, with no multiplicity control on the search

The thesis as stated in "The core point" is about *pairwise* conditional structure: at 249
trained columns that is C(249,2) ≈ 30,900 slots. A depth-4 tree expresses up to 4-way
interactions: C(249,4) ≈ 1.56e8 tuples. The model is searching a space roughly 4,500x larger
than the hypothesis it is meant to test, and the BH-FDR correction in the harness is applied to
the ~80 per-symbol tests of the *final score*, not to the interaction search that produced it.
This is the multiple-comparisons trap the "Overfitting risk" section names, relocated one level
up: it is not in the reported statistics, it is in the model-selection step that feeds them.

Compounding this: **item 5 of the original proposal was never executed.** No SHAP interaction
values, no gain-based pair attribution, was ever computed on any run. So the design as built had
no mechanism for converting a positive result into a *named* interaction. That is not a cosmetic
gap. `data-edge-source-thesis.md`'s "deliberately NOT on this list" rule requires any
signal-extraction claim to name the specific processing advantage; a tree that wins but cannot
say which feature pair it won with produces precisely the unqualified "our ML is better" claim
the parent doc forbids. Note also which mechanism actually caught the leak: an unrelated
concurrent session's join audit (todo 243), then an ablation. Not the CI, not the FDR
correction, not the canary controls, and not model interpretation. The design's own
error-detection surface never fired.

### 4. The one interaction axis this project has first-class machinery for was excluded from the tree's inputs

`feature_vectors.regime` (the per-symbol K=5 HMM label) and `regime_rolling` are both in
`EXCLUDE_COLS` (`_nonlinear_interaction_combiner_shared.py:81-82`), and `regime` is text-typed so
`_select_feature_columns`'s `float4`/`float8` filter would have dropped it regardless. The
cross-sectional label (`market_regimes.regime_label`, 9 values, confirmed live: `{low,mid,high}`
x `{bear,neutral,bull}`) was never joined into the training matrix at all. So the tree spent its
entire search budget on ~249 continuous columns with **both** conditioning variables withheld,
forced to rediscover any regime-conditional structure from proxies. Given that the doc's own
motivating argument is "regime is the one interaction axis the system explicitly models," this is
an odd allocation. It is also directly fixable and points at the alternatives below.

### Verdict of the critique

The evaluation discipline is sound and should be kept verbatim: walk-forward folds, circular-block
bootstrap CI, BH-FDR, causal per-symbol demeaning, the cross-sectional-neutral decomposition. The
surviving 1h residual (tree-linear diff 0.0106, `ci_lower` 0.0064) is real evidence that *some*
structure exists beyond capped linear combination. What is mis-matched is the estimator: unbounded
per-feature exposure on a corpus with a live defect rate, a search space three orders of magnitude
wider than the hypothesis, and no path from a win to a nameable mechanism. All three are fixable
without abandoning the question.

## Alternative methodologies, grounded in what already exists here (added 2026-08-03)

Ordered by how much existing machinery they reuse. None of these is proposed as proven; the two
judged most promising are pre-registered in the next section.

### (a) Constrain the tree the way the linear arm is already constrained

LightGBM 4.7.0 (the installed version, checked) accepts both `monotone_constraints` and
`interaction_constraints` through `LGBMRegressor`'s `**kwargs`. **Neither appears anywhere in this
repository today** (grepped repo-wide, zero hits), so this is new work, not a config flip.

- **A1, group-scoped interaction constraints.** `feature_registry` already partitions features
  into 11 `group_name` values (live counts 2026-08-03: structure 64, session 62, volatility 31,
  volume 30, calendar 21, momentum 14, regime 10, oscillator 6, control 5, cross_tf 3, macro 3;
  249 rows total). Passing `interaction_constraints` built from those groups, capped at two groups
  per tree, collapses the search from "any 4-tuple of 249 columns" to "pairwise cross-group
  structure," which is roughly the hypothesis actually stated, and makes a positive result
  nameable ("momentum x volatility," not "the tree won"). Implementation caveat: the registry's
  249 rows and the trained column list (derived at runtime from the live table schema, minus
  `EXCLUDE_COLS`) are two different sets and must be reconciled explicitly rather than assumed
  identical.
- **A2, bounding single-feature exposure.** LightGBM has no native analogue of
  `_LINEAR_MAX_FEATURE_WEIGHT`. Three honest substitutes, in increasing cost:
  (i) **post-hoc gain-concentration audit** - compute each feature's share of total split gain per
  fold and fail the run loud if any single feature or feature-family exceeds a stated ceiling. This
  changes nothing about the model, costs almost nothing, and would have fired on the CTF trio on
  2026-07-26 rather than 2026-08-03. It should be a permanent guardrail on any future run here
  regardless of which methodology wins;
  (ii) **random-subspace bagging** - fit K models each with a disjoint 1/K of columns held out and
  average, bounding any one column's influence to ~1/K by construction;
  (iii) explicit per-feature gain penalties, which LightGBM does not expose directly and would
  require a custom objective. Not recommended.
- **Honest limitation.** A constrained tree is still uninterpretable without a separate SHAP or
  gain-attribution pass, so A1/A2 must ship *with* item 5 of the original proposal, not instead
  of it.

### (b) Regime-conditional capped linear ensemble

This is the closest fit to machinery that already exists and is already production-proven.

**What production already does, stated precisely because it is easy to get wrong.**
`services/ensemble_trainer.py` already fits one weight vector per `(tf, regime)` stratum. Its
"regime" is the **cross-sectional** label: it reads `feature_ic_scores` rows with
`symbol='POOLED' AND is_pooled = true AND regime != '_pooled'`, and its feature-matrix query joins
`market_regimes mr ON mr.regime_group = 'equity' AND mr.tf = fv.tf AND mr.ts = fv.bar_ts WHERE
mr.regime_label = $2` (`ensemble_trainer.py:897-899`, with `regime_group` hardcoded to `'equity'`).
So one of the two regime axes is already a live stratification dimension in the production
combiner.

**What is not conditioned on anywhere.** `feature_vectors.regime`, the per-symbol K=5 HMM label
(`trending_down`, `transition_down`, `ranging`, `transition_up`, `trending_up`, written by
`services/regime_writer.py`), is a second, structurally different axis. It is idiosyncratic and
per-symbol where `market_regimes` is systematic and universe-wide; the two are orthogonal by
construction, which is what the Dual Regime System vocabulary in CLAUDE.md is there to keep
straight. The tree never saw it and `ensemble_trainer` does not stratify on it.

**Proposal B.** Inside each existing walk-forward fold, fit `fit_linear_ensemble_weights()` once
per `(market_regimes.regime_label, feature_vectors.regime)` cell on that fold's training slice
only, score each held-out row with its own cell's weight vector, and compare pooled OOS
cross-sectional-neutral IC against the single-weight-vector linear arm already in the harness.
This is a conditional-linear model. It can express "feature X predicts only in regime Y," which is
the interaction class the thesis names, while keeping the 20% cap, cluster deflation, and
empirical-Bayes IC shrinkage per cell. Its output is 45 to 54 readable weight vectors, so a win is
automatically nameable and directly promotable into `ensemble_trainer.py`'s existing per-stratum
structure with no new serving component.

**Why it is a better-matched estimator than the tree for this corpus:** exposure per feature per
cell is bounded; the hypothesis space is ~54 cells x ~249 features rather than 1.56e8 tuples; and
critically, **the conditioning variables are pre-registered and externally computed rather than
selected by the model off the training target**, so there is no selection-on-noise in the
conditioning step at all.

**The honest prior is against it, and the reason is specific.** Todo 179 exhaustively tested this
grid and found nothing surviving OOS replication (recorded as the falsification of
`regime_conditional_persistence`). The distinction that makes B a different question is real but
narrow: todo 179 tested whether an *individual feature's marginal IC* differs by cell; B tests
whether the *joint weight vector* should differ by cell, which can improve even when no single
feature's cell-conditional IC clears significance, because weights depend on the full IC vector
and covariance structure jointly. That is a genuine difference, but it is not a large one, and B's
prior should be set only modestly above todo 179's null.

**B has value under both outcomes, which is the strongest argument for running it.** A FAIL is not
merely another null: it is direct evidence that `ensemble_trainer.py`'s own existing per-regime
stratification does not earn its complexity, which is an actionable deletion under the 5-step
mandate rather than an unexplained negative result.

### (c) Pre-registered pairwise interaction terms inside the linear ensemble

Take a small, explicitly enumerated set of hypothesis-driven feature pairs, construct each as the
product of the two z-scored parents (or as "feature X conditioned on Y's tercile"), and append
them as ordinary columns to `fit_linear_ensemble_weights`'s `X`. The 20% cap, cluster deflation,
and shrinkage then apply to them identically, with no new model class at all.

Schema support already exists: `feature_registry` carries `parent_features text[]` and
`linear_ready boolean`, plus the evidence gates (`status`, `min_ic_sharpe`, `min_ic_n`,
`fdr_required`, `fdr_alpha`), so a derived interaction column has a registry home and an
evidence-based promotion path without new tables.

**This is the right confirmation instrument and the wrong search instrument.** It can only test
interactions someone thought of first, so it should be the promotion path for whatever (a) or (b)
surfaces, not the primary search. Its multiplicity is small and known in advance, which is
precisely what makes BH-FDR honest here rather than nominal.

### (d) Techniques from the wider quant literature that actually fit this corpus's constraints

Filtered hard for this project's real limits (effective breadth 8-15, autocorrelated bars,
walk-forward only, APR-governed parameters, evidence-gated promotion). Generic ML advice that
ignores those is omitted deliberately.

- **Within-`bar_ts` rank normalization of every feature, not just the target.** The harness already
  does causal per-symbol demeaning of the target and reports a cross-sectional-neutral
  decomposition as the number to quote. The stronger form is to rank-transform every *feature*
  within each `bar_ts` before fitting, so the model is structurally incapable of learning any
  time-series or common-market-factor effect and can only learn cross-sectional structure. This
  deletes an entire class of failure by construction, including the fixed-membership drift leak
  already caught here once, and it materially reduces the CTF leak's channel (much of that
  lookahead is a common-timing artifact shared across symbols within a bar). One transform in
  `fetch_training_matrix`. **Recommended as the default for any future combiner run of any model
  class**, and it is the natural companion to `cross_sectional_relative_value`, the sibling thesis
  that already passed.
- **Residual-form (two-stage) modeling: fit the non-linear model on the linear ensemble's
  residual, not in parallel to it.** Currently two independent models are fit on identical inputs
  and their OOS ICs are compared. Under a residual form, the capped linear ensemble is fit first
  on the fold's training slice, then the tree is fit on `y - linear_score` on the same slice. The
  tree can then only be credited with structure the capped linear combination did not already
  capture, which is a literal restatement of the thesis ("a non-linear combiner can express a
  class of structure the linear one structurally cannot"). This converts the thesis from an
  inference about the gap between two numbers into a direct estimand, and it removes the confound
  todo 245 identified, where the tree's advantage partly reflected its freedom to over-weight a
  single input rather than any non-linear structure. Small change to `train_and_predict_oos`.
- **Explicitly rejected, with reasons.** Deep nets: worse on all three critique axes (no breadth
  to support the capacity, no interpretability, no exposure bound). Additional CV schemes beyond
  walk-forward: the existing scheme is already correct for autocorrelated bars and
  `_pooled_panel_folds` now handles fold boundaries in bar units. LightGBM hyperparameter search:
  would introduce a model-selection multiplicity the current design has no correction for, and the
  critique above says the problem is structure, not tuning. More features before the combiner
  question is settled: the doc's own "Sequencing" section already rules this out.

## Pre-registered test designs (written 2026-08-03, before any run)

Two tests, in the pattern used by todo 179 and todo 238: falsification bar, magnitude floor,
guardrails, and the meaning of each outcome all fixed **before** execution. Nothing below is a
result. No number in this section has been measured.

Both tests inherit the existing harness verbatim: `run_nonlinear_interaction_combiner_check()`,
`_pooled_panel_folds()` (bar-unit folds, todo 239's fix), `circular_block_bootstrap_ic_serial`,
`paired_bootstrap_ic_difference`, `apply_bh_fdr`, causal per-symbol demeaning, and the
cross-sectional-neutral decomposition as the reported statistic.

### Shared preconditions (both tests are blocked until all three hold)

1. Todo 243's CTF join fix has landed **and** the affected `ctf_momentum` / `ctf_vwap_align` /
   `ctf_regime_align` values are recomputed for the tf under test; **or** all three columns are
   excluded via `fetch_training_matrix`'s existing `extra_exclude_cols` parameter (no code change
   required).
2. The in-flight 15m and 5m CTF-leak diagnostics (todo 245) have completed, so the leak's
   tf-generality is known rather than extrapolated from 1h.
3. Todo 240's linear-ensemble arm is the baseline in every comparison. `ctf_momentum` alone is
   never the baseline in either test.

### Shared guardrails (any breach voids the run; the number is not reported)

- **G1, gain concentration.** No single trained feature exceeds 15% of total split gain in any
  fold (chosen with margin below the linear arm's 20% cap; a judgment call fixed in advance, not
  derived). Breach means the run is void and the offending column is investigated first. Applies
  to tree arms only.
- **G2, shuffled null.** Rerun each arm with the target shuffled **within `bar_ts`**, which
  destroys cross-sectional signal while preserving autocorrelation, panel structure, and feature
  distributions. No arm may show `ci_lower > 0` under the null. Precedent:
  `cross_sectional_relative_value`'s shuffled-null control.
- **G3, canary re-inclusion.** Run one arm with the five `canary_*` columns re-added. If any
  negative-control canary (`canary_constant`, `canary_near_constant`, `canary_noise_gaussian`,
  `canary_noise_uniform`) lands in the top decile of gain importance, the run is void.
- **G4, no post-hoc arms.** The arm list is fixed below. Any arm added after seeing a number is a
  new pre-registration with its own family-wise correction, recorded as such.

### Test N1 (recommended first): residual-form combiner with bounded exposure

**Hypothesis (as an estimand, not a comparison of two independent numbers).** Let `L` be the
capped linear ensemble fit causally on a fold's training slice. Fit the tree on the residual
`y - L(X)` on that same slice. Form the composite `S = z_train(L) + z_train(T)`, where both scores
are standardized using the *training* fold's own mean and standard deviation and the combination
coefficient is fixed at 1 (deliberately not tuned: any coefficient fit on held-out data is a leak,
and any coefficient fit in-fold adds a free parameter this test does not need). The estimand is
`IC(S, y) - IC(L, y)` on held-out rows. If the linear combiner's linearity is genuinely the
bottleneck, this difference is positive; if it is not, the tree has nothing to add to `L` by
construction and the difference is zero.

**Arms, fixed in advance (2 arms x 3 timeframes = 6 tests in the BH-FDR family):**
- **N1-a:** residual tree, current hyperparameters unchanged (`n_estimators=200`, `max_depth=4`,
  `num_leaves=15`, `min_child_samples=200`, `learning_rate=0.05`, `reg_alpha=1.0`,
  `reg_lambda=1.0`, `subsample=0.8`, `colsample_bytree=0.8`).
- **N1-b:** identical, plus `interaction_constraints` built from `feature_registry.group_name`
  (proposal A1), capped at two groups per tree.
- Timeframes: 15m, 1h, 1d. 5m is excluded on economic grounds already settled in
  `data-edge-source-thesis.md`'s cost-hurdle verdict (short-horizon directional cells are
  net-negative against a 1-10bp cost floor), not on statistical grounds.
- All arms run on within-`bar_ts` rank-normalized features (proposal (d)) so the reported number
  cannot be a common-factor artifact. This is a fixed property of the test, not an arm.

**Falsification criterion, stated before any run. N1 PASSES only if ALL of the following hold:**
1. The paired circular-block bootstrap CI on the cross-sectional-neutral `point_ic` difference
   `IC(S) - IC(L)` has `ci_lower > 0` at 95%;
2. that difference is at least **0.005** in cross-sectional-neutral `point_ic`. This floor is a
   judgment call fixed in advance, set at roughly half the clean 1h residual already measured
   under the parallel form (0.0106, todo 245), on the reasoning that an effect smaller than that
   cannot survive downstream IC shrinkage and the cost hurdle. It is not derived from theory and
   should not be relitigated after seeing a number;
3. it holds with the same sign at **at least 2 of the 3 timeframes**;
4. it survives BH-FDR at alpha=0.05 across the 6-test family;
5. guardrails G1 through G4 are all clean.

**Outcome semantics, fixed in advance:**
- **PASS:** genuine non-linear structure exists beyond capped linear combination. Next step is not
  promotion; it is a SHAP or gain-attribution pass (the original proposal's item 5, never run) to
  name the interacting pairs, then proposal (c) to re-express them as explicit capped linear
  interaction terms with `feature_registry` promotion gates. A tree that cannot name its own
  mechanism does not get promoted regardless of its number.
- **FAIL:** the combiner's linearity is not the binding constraint. `nonlinear_interaction_combiner`
  is dead as stated, this doc closes with that verdict, and
  `data-edge-source-thesis.md` plus `catalog.md` are updated (todo 247 already tracks their stale
  "substantial at 1h/15m" text). Effort redirects to construction
  (`trade-construction-layer.md`) and to breadth, which the parent doc already argues is the
  larger lever.
- **AMBIGUOUS** (clears criterion 1 but not criterion 2): recorded as "real but economically
  inert," the same category as the existing 1d result. Not a reason to run more variants.

**Cost.** Reuses the existing pipeline; new code is a residual target, the fixed-coefficient
composite, the G1 gain-concentration audit, the within-`bar_ts` rank transform, and the N1-b
constraint list. Runtime should be comparable to the existing runs (the 1h CTF-leak diagnostic
took ~85 minutes).

### Test N2: regime-conditional capped linear ensemble

**Hypothesis.** The ensemble's *weight vector*, not any individual feature's IC, is
regime-dependent. A per-cell capped linear ensemble beats a single pooled capped linear ensemble
on held-out cross-sectional-neutral IC.

**Cell scheme, fixed in advance.** `market_regimes.regime_label` (9 values, `regime_group='equity'`,
joined on `(regime_group, tf, ts)` exactly as `ensemble_trainer.py:897-899` does) x
`feature_vectors.regime` (5 HMM labels plus an explicit `unlabeled` cell). At 1h, 530,219 of
2,254,176 rows (~23.5%, counted live 2026-08-03) have a NULL HMM label; those rows go to the
`unlabeled` cell and are **never dropped**, per this project's data-retention rule. Any cell with
fewer than 20,000 training rows in a given fold falls back to that fold's pooled weight vector.
The 20,000 floor is borrowed from `stratification-dimension-unification.md`'s substitution-test
gate, which uses the same threshold for the same "below this a cell is data-starved" reason.

**Arms, fixed in advance (3 arms x 3 timeframes = 9 tests in the BH-FDR family):**
- **N2-a:** pooled capped linear (the existing `fit_linear_ensemble_weights` arm, unchanged).
- **N2-b:** cross-sectional-regime-conditional only, 9 cells. This arm doubles as an audit of
  whether `ensemble_trainer.py`'s existing production stratification earns its complexity.
- **N2-c:** joint 9 x 6 cells.
- Timeframes 15m, 1h, 1d, same exclusion of 5m for the same economic reason.

**Falsification criterion, stated before any run. N2 PASSES only if ALL of:**
1. paired bootstrap `ci_lower > 0` on `IC(N2-c) - IC(N2-a)` (or `IC(N2-b) - IC(N2-a)`, evaluated
   as separate members of the same corrected family);
2. the difference is at least 0.005 cross-sectional-neutral `point_ic`, same floor and same
   rationale as N1;
3. same sign at at least 2 of 3 timeframes;
4. survives BH-FDR at alpha=0.05 across the 9-test family;
5. guardrails G2 and G4 clean (G1 and G3 are tree-specific and do not apply).

**One additional guardrail specific to N2, and it is load-bearing. G5, conditioning-variable
causality.** `regime_writer.py` fits each `(symbol, tf)` HMM **on the full series** (its own
comment at the held-out-log-likelihood block states this explicitly), then decodes causally: the
forward alpha-pass uses only information up to bar t, and `_smooth_states` is documented and
verified causal ("Requires min_hold consecutive bars of the same new state before confirming a
transition. Causal, no look-ahead"). So the *decoding* is clean but the *emission means, covariances
and transition matrix* are estimated using data from after bar t. Using `feature_vectors.regime`
as a walk-forward conditioning variable therefore carries a real, if narrow, lookahead channel:
roughly 5 emission means x 5 observation dimensions plus a 5x5 transition matrix, estimated over
millions of bars. This is orders of magnitude weaker than a per-bar future-price leak, but this
doc exists partly because a leak was assumed bounded and was not. **Not a new finding** -- this is
the same gap tracked since 2026-06-28 as `.planning/todos/deferred/026-hmm-regime-audit-optimization.md`'s
P4a (rolling/expanding HMM refit), still gated on an unmet empirical-impact decision; restated
here only because N2 depends on it directly. **N2 is not reportable until
one of:** (i) the HMM is refit per fold on training-slice data only, which is the correct fix and
the more expensive one; or (ii) a stated sensitivity check runs N2-c with the HMM axis replaced by
its causally-computed cross-sectional counterpart alone (that is, N2-b, whose `market_regimes`
inputs are causal expanding ranks by construction, see `breadth_vol.py`'s `_causal_expanding_rank`)
and the pass/fail verdict does not depend on the HMM axis. `market_regimes` itself needs no such
caveat. Do not treat option (ii) as equivalent to option (i); it bounds the confound, it does not
remove it.

**Outcome semantics, fixed in advance:**
- **PASS on N2-c but not N2-b:** the per-symbol HMM axis carries weight-level structure the
  cross-sectional axis does not. Promotion path is adding the HMM axis to `ensemble_trainer.py`'s
  existing stratum key, subject to G5 being resolved by option (i), never option (ii).
- **PASS on N2-b:** production's existing stratification is empirically justified. Useful
  confirmation of a live design decision that has never been tested this way.
- **FAIL on both:** regime-conditional *weighting* is empty, matching todo 179's null on
  regime-conditional *feature IC*. This is directly actionable, not merely negative:
  `ensemble_trainer.py`'s per-regime stratification becomes a deletion candidate under the 5-step
  mandate, which removes real complexity from the live combiner.

### Recommended order

Run **N1** first. It tests the doc's actual thesis with a strictly better estimator, its
guardrail G1 is the check that should have existed since July regardless of which methodology
wins, and it is blocked on nothing that N2 is not also blocked on. Run **N2** second, or in
parallel if host memory allows (the existing runs already contend for a 29GB host; check real
CPU/RAM contention before launching both). Neither test's result is promotable to production
without the usual OOS and shadow-mode gates named in "Overfitting risk" above.

## Sequencing

Cheap to run — no new data, no new features, no new infrastructure. Reuses `feature_vectors`/
`forward_returns` exactly like `ic_engine.py`/`ensemble_trainer.py` already do; this could run
as an offline/shadow experiment (a single analysis script, similar in shape to todo 179's
sweep scripts) before committing to Phase 164/165's multi-week feature-build effort. Recommend
running this alongside `docs/research/trade-construction-layer.md`'s cross_sectional_relative_value (cross-sectional
long-short) before deciding whether Phase 164/165 is warranted — both test the *existing* 150
features under a different construction or model, which is strictly cheaper than adding
features under the linear/absolute-direction construction T2 just falsified.

## What this explicitly does not claim

- Not a claim that gradient-boosted trees will find real signal — this is a falsifiable test,
  and per the edge-source-thesis doc's default posture, the honest prior is skepticism until
  evidence lands.
- Not a proposal to replace `ensemble_trainer.py`'s linear combiner in production. That
  decision, if nonlinear_interaction_combiner's test result warrants it, is a separate, later phase with its own gates.
- Not a substitute for cross_sectional_relative_value (cross-sectional construction) — they test different hypotheses
  (combiner linearity vs. absolute-vs-relative construction) and both are worth running; a
  positive nonlinear_interaction_combiner result and a positive cross_sectional_relative_value result are not mutually exclusive.

## References

- `docs/research/data-edge-source-thesis.md` — nonlinear_interaction_combiner's parent doc; T2's falsification is the
  motivating finding
- `docs/research/trade-construction-layer.md` — cross_sectional_relative_value, the sibling candidate construction change
- `.planning/todos/completed/179-gate166-concurrent-exposure-diagnostic.md` — T2's falsification
  evidence and the day-clustered bootstrap / BH-FDR methodology this test should reuse
- `docs/research/measurement-ic-engine.md` — existing IC measurement methodology (`ic_math.py`)
  this test's evaluation discipline should stay consistent with
- `.planning/STATE.md` — the Phase 164/165-vs-reprioritize fork this doc is meant to inform

Added 2026-08-03, for the critique / alternatives / pre-registration sections:

- `.planning/todos/pending/243-ctf-momentum-batch-join-lookahead-bias.md` and
  `.planning/todos/pending/245-nonlinear-interaction-combiner-trains-on-lookahead-contaminated-ctf-momentum.md`
  - the leak and its blast radius into this test; todo 245 carries the 1h with/without-CTF table
- `.planning/todos/pending/239-...-embargo-passed-in-pooled-panel-rows-not-bars.md`,
  `.planning/todos/pending/240-...-baseline-is-single-feature-not-the-linear-ensemble.md` - the
  two methodology fixes whose corrected re-run both pre-registered tests depend on
- `.planning/todos/pending/238-...-ranked-cross-sectional-relative-value-pre-registration.md` -
  the pre-registration pattern both test designs above follow
- `docs/research/stratification-dimension-unification.md` - the governance gates and the
  N > 20,000 per-cell floor test N2 borrows
- `services/ensemble_trainer.py` - the production per-`(tf, regime)` weighting and its
  `market_regimes` join (lines ~897-899); the arm test N2 is auditing
- `services/regime_writer.py` - per-symbol K=5 HMM labels; full-series parameter fit with causal
  decoding, which is the source of guardrail G5
- `.planning/todos/deferred/026-hmm-regime-audit-optimization.md` - G5 is not a new finding; this
  is where the full-series-fit-vs-causal-decode gap (its P4a) has been tracked since 2026-06-28,
  gated on an unmet empirical-impact decision
- `services/cross_sectional_regime_model.py` and `src/intelligence/regime_signals/breadth_vol.py`
  - the 9-value cross-sectional `regime_label` vocabulary and its causal expanding-rank
  construction
