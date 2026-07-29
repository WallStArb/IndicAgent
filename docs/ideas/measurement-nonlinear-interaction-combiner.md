# Non-Linear Interaction Combiner — Idea (Edge Source Thesis T5)

**Status:** Promoted — see `docs/research/data-edge-source-thesis.md` §T5 (added 2026-07-25) for
the current, actively-maintained version. That doc also covers the post-promotion canary-leakage
check (todo 184, closed) and the empirical 1d replication
(`docs/analysis/t5-replication-1d-per-symbol.csv`). This file is kept as the original idea
record, not the live reference.
**Author:** Claude (Sonnet 5), interactive session, 2026-07-25 — not a Fable dispatch. This doc
is a design proposal; nothing here has been empirically tested yet.
**Origin:** Raised in conversation while resolving the fork in `.planning/STATE.md` ("invest in
better features/signal (Phase 164/165) ... or accept this branch has no OOS-detectable edge")
— specifically, the question "what other signal construction approaches exist, if this is how
Renaissance/Jane Street-style quant systems work at their core."
**Companion to:** `docs/research/data-edge-source-thesis.md` (this is candidate thesis **T5**)
and `docs/research/trade-construction-layer.md` (T5's sibling candidate — T3 changes the
*construction*, T5 changes the *combiner*; both are cheaper to test than Phase 164/165's
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

## Overfitting risk — the load-bearing caveat

`docs/research/data-edge-source-thesis.md`'s "Breadth Is the Binding Constraint" section
measured this universe's effective breadth at ~8-15 (58 correlated ETFs). A tree model with
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

## Sequencing

Cheap to run — no new data, no new features, no new infrastructure. Reuses `feature_vectors`/
`forward_returns` exactly like `ic_engine.py`/`ensemble_trainer.py` already do; this could run
as an offline/shadow experiment (a single analysis script, similar in shape to todo 179's
sweep scripts) before committing to Phase 164/165's multi-week feature-build effort. Recommend
running this alongside `docs/research/trade-construction-layer.md`'s T3 (cross-sectional
long-short) before deciding whether Phase 164/165 is warranted — both test the *existing* 150
features under a different construction or model, which is strictly cheaper than adding
features under the linear/absolute-direction construction T2 just falsified.

## What this explicitly does not claim

- Not a claim that gradient-boosted trees will find real signal — this is a falsifiable test,
  and per the edge-source-thesis doc's default posture, the honest prior is skepticism until
  evidence lands.
- Not a proposal to replace `ensemble_trainer.py`'s linear combiner in production. That
  decision, if T5's test result warrants it, is a separate, later phase with its own gates.
- Not a substitute for T3 (cross-sectional construction) — they test different hypotheses
  (combiner linearity vs. absolute-vs-relative construction) and both are worth running; a
  positive T5 result and a positive T3 result are not mutually exclusive.

## References

- `docs/research/data-edge-source-thesis.md` — T5's parent doc; T2's falsification is the
  motivating finding
- `docs/research/trade-construction-layer.md` — T3, the sibling candidate construction change
- `.planning/todos/pending/179-gate166-concurrent-exposure-diagnostic.md` — T2's falsification
  evidence and the day-clustered bootstrap / BH-FDR methodology this test should reuse
- `docs/research/measurement-ic-engine.md` — existing IC measurement methodology (`ic_math.py`)
  this test's evaluation discipline should stay consistent with
- `.planning/STATE.md` — the Phase 164/165-vs-reprioritize fork this doc is meant to inform
