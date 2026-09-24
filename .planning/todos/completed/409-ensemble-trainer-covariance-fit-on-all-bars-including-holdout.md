---
status: completed
priority: P1
filed: 2026-09-24
source: Phase 179 pre-registration code read (docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md, section 2)
---

# ensemble_trainer fits stratum covariance on every bar, holdout included

## What

`EnsembleTrainer._process_stratum` (`services/ensemble_trainer.py`, the `fv_rows` query) reads
`feature_vectors` for the stratum with no `bar_ts` bound, then fits
`compute_shrinkage_covariance(X)` on all of it. That covariance drives cluster deflation
(`ic_proportional`) or the mean-variance solve, so the weights depend on bars at and after
`alpha.validation.oos_start`. The OOS protocol clamps ic_engine's training window but not this
read. The same query also scores every bar, which is fine; the fit is the leak.

## Fix direction

Fit the covariance only on rows with `bar_ts < training_window_end` (the window the IC rows came
from, see todo 405 for pinning that window; todo 408 is the sibling wall-clock finding), keep scoring all rows. Phase 179's
`fit_stratum` extraction is the natural place: the covariance input becomes an explicit argument.

## Resolved 2026-09-24 (c6750d700)

`fit_stratum_weights` fits the covariance on bars up to and including the selection's
`training_window_end` (inclusive, matching ic_engine's `ts <= training_window_end`) via a
bisect on the ORDER BY bar_ts rows; scoring still covers every bar. A selection whose rows span
more than one IC window raises ValueError until todo 405 pins the read. Regression tests:
`test_rows_after_the_training_window_do_not_change_the_weights` (trainer) and
`test_fit_uses_bars_up_to_and_including_the_window_end_only` (module).
