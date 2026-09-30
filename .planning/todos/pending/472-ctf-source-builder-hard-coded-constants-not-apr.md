---
status: pending
priority: P3
filed: 2026-09-30
source: plan 186-15 task 2 (moved code kept byte-identical)
---

# The CTF source builder holds hard-coded numbers that belong in APR

## What

`_build_ctf_series` (`src/intelligence/features/kernels/cross_tf.py`, moved unchanged from
`services/backfill_feature_factory.py` by 186-15) carries numeric values that CLAUDE.md's APR
mandate says must be `config_state` keys: the rolling window of the HMM observation's volatility
term (`deque(maxlen=20)`), the volatility it uses before two returns exist (`0.005`), and the
guards `1e-10` on the VWAP, price and log floors. `ctf_regime_align` is 0.0 or 1.0 from the state
the forward pass picks, so a change to any of them moves stored CTF values.

The 186-15 move was held byte-identical against the golden fixture, so the constants were not
migrated there. `_HMM_K` and the forward step live in `feature_cache.py` and have the same
question.

## More hard-coded numbers found by the 186-15 altitude review

Same mandate, same byte-identical seeding rule:

- `cross_tf.py`: `deque(maxlen=20)` and the cold-start volatility `0.005` (above), plus the `1e-10`
  guards.
- `vp_sr.py`: the S/R strength cap `2.0` and the default S/R lookback `_SR_DEFAULT_LOOKBACK = 120`
  (one constant since 186-15 review; it is the fallback for a tf missing from
  `sr_lookback_by_tf`, so it belongs next to that key).
- `feature_cache.py` (legacy, frozen): the `_HMM_*` transition, emission and prior tables that
  `_hmm_forward_step` reads; `ctf_regime_align` inherits them. They move with the helpers in
  todo 476 and become APR JSON (a behavioral list with a warning that changing it invalidates
  stored `ctf_regime_align`).

## Fix

Seed `alpha.ctf.*` keys (window, cold-start volatility) with the current values in a migration,
read them through `FeatureFactoryConfig`, and let the golden stay byte-identical because the seeds
equal today's numbers. Decide the `1e-10` floors with the other numerical guards
(`EPS` in `_primitives.py`) rather than as tunables. Migration number above the highest file in
`production/migrations` at the time.
