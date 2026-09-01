---
status: pending
priority: P3
filed: 2026-09-01
source: reuse/architecture check before writing statistical_factor_residual's Stage 3 --
  verified Stage 3 itself doesn't repeat this, but found it already happened twice in
  DEAD candidates
---

# `ic_math.py`'s circular-block bootstrap has 2 independent hand-rolled duplicates for the partial-IC case

## What

`src/intelligence/statistics/ic_math.py::_circular_block_bootstrap_ic` is the shared production
bootstrap-CI primitive (raw X/Y pairs -> percentile CI on Spearman IC). It has no variant for a
bootstrap CI on a *partial* IC (controlling for covariates via `partial_spearman_ic`, also in
`ic_math.py`). Two independent DEAD-candidate scripts each needed exactly that and each
hand-rolled their own copy instead of extending the shared one:

- `scripts/analysis/cointegrated_pairs_residual_pilot.py::_circular_block_bootstrap_ic_1d` --
  docstring: "Same circular block-index mechanic as `ic_math._circular_block_bootstrap_ic`,
  re-ranking..."
- `scripts/analysis/jump_diffusion_decomposition_spy_pilot.py::_circular_block_bootstrap_partial_ic`
  -- docstring: "re-implemented... the exact correctness property
  `_circular_block_bootstrap_ic`'s docstring documents"

Both authors clearly knew about the shared primitive and chose to duplicate rather than
generalize it -- correct call at the time (each was a scoped, one-off pilot script; premature
to generalize for a single caller), but now that it's happened twice, a third occurrence would
be a real "we should have generalized this" moment, per Musk's mandate (simplify before you
accelerate a second/third time).

## Why not fixed now

Checked 2026-09-01 whether `statistical_factor_residual`'s unwritten Stage 3 would become a
third instance -- it doesn't. Its pre-registered design (`docs/research/measurement-
statistical-factor-residual.md`) computes IC directly on a residual return series (a
transformed Y, not a covariate-controlled partial correlation) and explicitly reuses
`_circular_block_bootstrap_ic` as-is, same harness as every other candidate. No live task
currently needs the partial-IC-under-bootstrap shape.

Both duplicating scripts belong to CONFIRMED DEAD candidates -- fixing this doesn't change any
research verdict, purely a code-hygiene/future-proofing question. Not worth touching working,
closed research code without a live reason to run it again.

## What to do, if/when a third real need for bootstrapped partial-IC shows up

Generalize `_circular_block_bootstrap_ic` (or add a sibling taking a pluggable per-block
statistic function, e.g. `_circular_block_bootstrap_stat(X, Y, stat_fn, ...)`) so
`partial_spearman_ic` can be bootstrapped through the same shared, tested mechanic instead of a
third hand-rolled copy. Then optionally backport `cointegrated_pairs_residual_pilot.py`/
`jump_diffusion_decomposition_spy_pilot.py` to call it too, for reference-implementation
consistency (not required -- they're closed and correct as written).

## References

- `src/intelligence/statistics/ic_math.py` -- `_circular_block_bootstrap_ic`, `partial_spearman_ic`
- `scripts/analysis/cointegrated_pairs_residual_pilot.py`
- `scripts/analysis/jump_diffusion_decomposition_spy_pilot.py`
- `docs/research/measurement-statistical-factor-residual.md` -- Stage 3's design, confirmed clean
