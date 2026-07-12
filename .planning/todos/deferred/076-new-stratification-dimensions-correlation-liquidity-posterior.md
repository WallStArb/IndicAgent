# 076 — New/refined stratification dimensions: correlation regime, liquidity regime, posterior-weighted IC

**Status (moved to deferred/, 2026-07-10):** Hard gate stated in the todo itself: Phase 144 (`regime_group` dispatcher) must ship first. Revive when Phase 144 is planned.


**Source:** `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` §5 (L2-1, L2-2, L2-3).
**Priority:** medium-high; these are new candidate `StratificationDimension` entries for the
v3.15/`regime-multi-regime-layer.md` unification, entering through the same substitution-test +
orthogonality gate as every other candidate — not a bespoke build.
**Gate:** Phase 144 (`regime_group` dispatcher) must ship first; L2-3 additionally sequenced
behind Phase 144's widened Step 1 verdicts (see
`docs/research/fable-2026-07-07-phase144-conditioning-decision.md`) since demoted-to-shadow HMM
groups won't consume it.

## L2-1 — Realized-correlation regime (co-movement structure, not vol level)

**Cross-reference (2026-07-12, housekeeping audit):** `.planning/todos/pending/038-cross-sectional-collinearity-diagnostic.md`
computes a related rolling cross-sectional correlation/co-movement structure over the same
universe for a different end-use (collinearity-risk diagnostic vs. this stratification
dimension). Not a duplicate, but check it before building either.

Cross-sectional mean pairwise correlation of universe returns (rolling window, expanding
percentile rank). VIX×breadth measures fear level and participation; average pairwise
correlation measures whether the universe is *one trade or many* — precisely the condition under
which the cross-sectional features (todo 073) should gain or lose IC, and the documented
precursor of momentum crashes. This is the stratification-shaped descendant of the archived
`comomentum-crowding-metric.md` (whose own recommendation was to decompose crowding into
primitives, not build the paper's bespoke index) — a conditioning axis through the standard gate
instead. Sharpest pre-registered prediction: the cross-sectional features (todo 073) show
materially lower IC in the top correlation decile. Computed from the same close series
`equity_regime_model.py._fetch_spy_bars` already generalizes from; one more provider under the
Phase 144 dispatcher.

## L2-2 — Liquidity regime (participation percentile)

Expanding percentile rank of universe median dollar volume per bar. Distinct axis from vol and
correlation; directly tests T1 (small-scale immediacy provision), whose falsification condition
is "edge concentrates in less-liquid conditions." Same mechanics/gate as L2-1.

## L2-3 — Soft stratification: posterior-weighted IC (variance-reduction refinement, not a new dimension)

`feature_vectors` already stores full HMM posteriors (`hmm_prob_*`, `hmm_entropy`). Hard-label
stratification throws boundary observations into one cell at full weight; a fractional-membership
IC (each observation contributes to each stratum weighted by posterior) uses the same data with
strictly more information, shrinking cell-estimate variance exactly where labels are least
certain. A weighted-rank variant inside `ic_math.py`, measurable on the existing corpus with no
schema change — zero new parameters (posteriors already exist).
