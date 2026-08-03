---
status: pending
priority: P1
filed: 2026-08-03
source: rigor review of `docs/research/data-edge-source-thesis.md` -- checking each result
  against the falsification criterion that was pre-registered for it
---

# `nonlinear_interaction_combiner` has never been tested against the baseline its own falsification criterion names

## Status (2026-08-03)

Code fix landed: commit `816032e2` adds `fit_linear_ensemble_weights()` +
`score_linear_ensemble()` to `scripts/analysis/_nonlinear_interaction_combiner_shared.py` -- a
fold-local, causally-fit linear ensemble reusing `ensemble_trainer.py`'s own weighting
primitives (`compute_shrinkage_covariance`, `mean_variance_weights`, `derive_weights`,
`cluster_deflate_weights`, plus a new `covariance_to_correlation()` extracted into
`covariance.py`). Wired into `run_nonlinear_interaction_combiner_check()` as a third
`linear_score` arm; `ctf_momentum` kept as the secondary arm per this todo's own ask. The
PRIMARY VERDICT is decided via a paired bootstrap of the IC difference
(`paired_bootstrap_ic_difference`, same file) rather than comparing two marginal CIs for
non-overlap -- tree and linear score identical rows, so a non-overlap test is systematically
underpowered there.

Peer-reviewed (independent agent, verified against the live corpus, not just read-through) and
two blocking issues from that review are already fixed in the same commit: features are now
z-scored before weighting/covariance (unstandardized raw `feature_vectors` columns span a
~150x scale range, so weights were dominated by whichever column had the largest raw variance
regardless of IC -- confirmed empirically pre-fix, pooled IC roughly doubled once standardized),
and `max_fit_rows` default lowered 1M -> 200K after the same review measured ~8.1GB transient
memory at 1M rows against this module's prior documented OOM history at 15m/5m scale.

**Still open:** the actual re-run across 1h/1d/15m/5m and reading the new PRIMARY VERDICT this
todo was written to get -- hasn't happened yet (multi-hour, DB-heavy job, deliberately not
started opportunistically). Leaving `status: pending` until that re-run lands; the 5 new
Signal-Extraction candidates and todo 238 both still wait behind this per the doc's own
sequencing note.

## What

The pre-registered falsification bar, written in `docs/research/data-edge-source-thesis.md`
before any of the runs (verbatim):

> a non-linear combiner (gradient-boosted trees or a shallow net) over the identical
> `feature_vectors`/`forward_returns` corpus ... must show a statistically significant
> Sharpe/IC uplift **over the existing linear ensemble** on the *same* features.

Every run actually performed (1h 2026-07-26, 1d 2026-07-27, both re-verified 2026-08-02, 15m
2026-08-03, 5m in flight) compares the tree against **`ctf_momentum` alone**:

```python
# scripts/analysis/_nonlinear_interaction_combiner_shared.py:516
baseline_feature: str = "ctf_momentum",
```

No script in `scripts/analysis/` compares the tree to `ensemble_trainer.py`'s shrunk-IC-weighted
linear combination. So the thesis -- "the combiner's *linearity* is the bottleneck" -- has not
been tested. What has been tested is the much weaker and largely uninteresting claim that a
263-column gradient-boosted model beats one hand-picked column.

This matters directly for how the result gets read. "Tree 0.2506 vs baseline 0.0610 at 15m" is
currently cited as a 4x uplift attributable to non-linearity. Any part of that gap that comes
from *using 263 features instead of 1* belongs to breadth of inputs, not to the linear/non-linear
distinction, and the existing linear ensemble already has that breadth.

## Fix

Add the linear-ensemble arm to `_nonlinear_interaction_combiner_shared.py`'s comparison, evaluated on the
identical OOS rows through the identical `per_symbol_ic_ci` / BH-FDR / cross-sectional-neutral
path:

1. **Primary arm (the pre-registered test):** tree vs. a shrunk-IC-weighted *linear* combination
   over the same feature columns, weights fit causally inside each walk-forward fold's training
   slice using the same shrinkage `ensemble_trainer.py` applies. This is the number the doc's
   criterion asks for.
2. **Keep `ctf_momentum` as a secondary arm** -- it is still the right reference for
   [todo 238](238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md),
   since `ctf_momentum` is what `services/cross_sectional_spread_tracker.py` actually ranks by
   today. The two arms answer different questions and both should be reported.

Pre-register the pass rule before running (per this project's standing discipline): the tree
must beat the *linear* arm's cross-sectional-neutral `point_ic` with a non-overlapping
day-clustered bootstrap CI, not merely beat `ctf_momentum`.

## Cross-refs

- `docs/research/data-edge-source-thesis.md` -- nonlinear_interaction_combiner section (caveat recorded there
  2026-08-03, pointing here)
- [todo 239](239-nonlinear-interaction-combiner-embargo-passed-in-pooled-panel-rows-not-bars.md) -- the other gap found in
  the same review
- [todo 238](238-nonlinear-interaction-combiner-ranked-cross-sectional-relative-value-pre-registration.md) -- gated on this, since a
  tree-vs-linear-ensemble result may change whether the tree score is the right ranking signal
