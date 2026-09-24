---
status: pending
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
