---
status: completed
priority: P1
filed: 2026-09-24
source: Phase 179 pre-registration code read (docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md, section 2)
---

# ensemble_trainer ages weights by wall clock; the champion silently became uniform 1/n

## What

`_process_stratum` computes `days_since = now() - max(training_window_end)` and, past
`alpha.ensemble.weight_stale_max_days` (90), replaces the IC-quality weights with uniform
`1/n`. The champion `run_2025122405150000` was trained 2026-09-22, 272 days after its
2025-12-24 window end. Verified live 2026-09-24: every 1d stratum's `raw_weight` and `weight`
are exactly `1/n` (e.g. mid_neutral 18 features at 0.0556). So the weights depend on the date
the trainer happens to run, not only on its inputs, and the stale fallback fires without a
warning. Todo 378's diagnostic therefore measured a uniform blend of in-sample-selected
features, not the IC-weighted method.

## Fix direction

Make the aging reference an explicit input (the scoring date or the window end), never
`datetime.now()`. Decide separately whether staleness should block training loudly instead of
flattening weights. Phase 179's `fit_stratum` takes `days_since` as an argument, so the policy
lives in one caller.

## Resolved 2026-09-24 (c6750d700, migration 360)

Aging deleted, not made explicit: the exponential decay was a no-op (`derive_weights`
renormalizes a uniformly scaled vector), so the only live behavior was the 1/n cliff. The fit
now lives in `src/intelligence/ensemble/stratum_fit.py` as a pure function of the IC rows and
the training-window feature matrix, with no clock; migration 360 retired
`alpha.ensemble.weight_half_life_days` and `alpha.ensemble.weight_stale_max_days` (applied live).
Regression test: `tests/unit/services/test_ensemble_trainer_fit_window.py::test_an_old_ic_window_does_not_flatten_weights_to_one_over_n`
(failed at exactly 1/n before the fix). The next trainer run (after the Phase 178 recompute)
produces the first non-uniform champion.
