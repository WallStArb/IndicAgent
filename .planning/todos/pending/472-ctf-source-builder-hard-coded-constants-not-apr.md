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

## Fix

Seed `alpha.ctf.*` keys (window, cold-start volatility) with the current values in a migration,
read them through `FeatureFactoryConfig`, and let the golden stay byte-identical because the seeds
equal today's numbers. Decide the `1e-10` floors with the other numerical guards
(`EPS` in `_primitives.py`) rather than as tunables. Migration number above the highest file in
`production/migrations` at the time.
