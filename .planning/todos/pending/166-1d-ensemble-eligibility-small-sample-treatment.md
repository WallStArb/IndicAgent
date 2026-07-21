---
status: pending
priority: P2
filed: 2026-07-21
source: split out of todo 164 -- the 1h portion (population-scarcity, mechanical per-tf
  APR fix) shipped separately; this is 1d's genuinely different failure mode (real
  statistical power problem), explicitly scoped by todo 164 as needing its own plan
  rather than a threshold tweak.
---

# 1d ensemble eligibility needs a real small-sample statistical treatment, not a threshold tweak

## What's wrong

`1d`'s median effective-N (`n_independent`) is 1,222 (min observed: 143) -- ~32x fewer than
`15m`'s 39,776. Average CI width is 0.166, over 3x wider than every other timeframe. With
~20 years of history fragmenting to ~5,000-7,500 daily bars total, further split across
regime cells, `1d`'s `ic_ci_lower > 0` significance test runs with an order of magnitude
less statistical power than 5m/15m/1h. A real IC effect that would easily clear the bar at
higher frequencies can fail here purely from estimation noise (wide CI), not a weak point
estimate -- a Type II error risk, not evidence of absent signal.

This is a genuinely different failure mode than `1h`'s (population-scarcity, fixed via
per-timeframe APR threshold overrides -- see `alpha.ensemble.min_passing_features.1h` /
`max_feature_weight.1h`, migration 245, plus the emergent `meta_fdr_min_cells.1h` fix,
migration 246). Do not apply the same fix here: `1d`'s problem is real estimation noise from
too few independent observations, not a miscalibrated count threshold, and a threshold nudge
would either manufacture false coverage or do nothing.

## Fix direction (needs real design, not a parameter tweak)

A properly small-sample-appropriate statistical treatment -- e.g. a Bayesian shrinkage IC
estimator that correctly widens its own uncertainty bounds rather than a frequentist CI too
wide to ever exclude zero with confidence at N~1,000-2,000, or a day-clustered bootstrap
calibrated for `1d`'s achievable cell count (mirrors FRAME-04's own day-clustered bootstrap
CI machinery in `services/counterfactual_tracker.py`, already built and reused for todo
165's regime-stratified OOS gate). This is real methodology work -- scope it as its own
plan, not a same-session follow-on to todo 164.

## References

- `services/ic_engine.py` -- where `1d`'s IC scores are computed
- `services/ensemble_trainer.py`: `_meta_eligible()`, `_process_stratum()` -- the
  eligibility gates that consume `1d`'s (thin) IC scores
- `docs/superpowers/specs/2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility-design.md`
  -- design doc that split this out of todo 164
- Live numbers above from direct queries against `feature_ic_scores`, 2026-07-21
