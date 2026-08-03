---
status: pending
priority: P1
filed: 2026-08-03
source: rigor review of `docs/research/data-edge-source-thesis.md` -- checking each result
  against the falsification criterion that was pre-registered for it
---

# `nonlinear_interaction_combiner` has never been tested against the baseline its own falsification criterion names

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
