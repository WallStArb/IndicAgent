---
status: pending
priority: P3
filed: 2026-08-05
source: /simplify altitude review of todo 266's fix (_informed_flow/_range_vs_atr
  consolidation onto _is_valid_atr)
---

## What

`_dist_from_high`/`_dist_from_low` (`src/intelligence/feature_factory.py:1545`/`:1558`,
scalar/live path) and their vectorized batch counterparts `_dist_from_high_series_full`/
`_dist_from_low_series_full` (`:2648`/`:2658`) are the same ATR-ratio shape as the 14 features
already consolidated onto `_is_valid_atr` by todos 237 and 266 -- `(rolling_high - close) / atr`
and `(close - rolling_low) / atr` -- but still gate on their own absolute `eps=1e-10` epsilon
(`atr > eps` scalar / `np.where(atr_padded > eps, ...)` vectorized), not the shared relative
`min_atr_pct * close_` floor.

These back 4 live "quant"-tier `FeatureVector` fields: `dist_from_high_fast`, `dist_from_high_slow`,
`dist_from_low_fast`, `dist_from_low_slow` (`feature_factory.py:3555-3565`, both `compute()`'s
scalar path and `compute_batch()`'s vectorized path via `atr_padded`).

Same BIL-style blast radius as todo 237/266: a legitimately-positive but numerically-tiny ATR
relative to close_ passes the absolute-epsilon gate uncaught and these 4 columns can explode to
an implausible magnitude during a genuinely flat period.

## Why not fixed in the same diff as todo 266

Found during `/simplify`'s altitude review of todo 266's diff -- out of that diff's scoped call
graph (different functions, and the vectorized `_series_full` variants operate on
`atr_padded: np.ndarray` via `np.where`, not a per-bar scalar `_is_valid_atr(atr_val, close_,
min_atr_pct)` call -- routing them through the shared guard needs either a vectorized
`_is_valid_atr_series`-style equivalent or an inline `np.where` reimplementation of the same
relative-floor logic). Fixing this would change live output for every bar for all 4 columns --
a real behavior change, not a same-diff cleanup, same caution todo 266 itself gave for
`_informed_flow`/`_range_vs_atr`.

## Fix

1. Scalar path: route `_dist_from_high`/`_dist_from_low` through `_is_valid_atr(atr, close,
   min_atr_pct)` in place of their own `atr > eps`, same pattern as todo 266.
2. Vectorized path: `_dist_from_high_series_full`/`_dist_from_low_series_full` need a vectorized
   equivalent of the relative floor -- `np.where(atr_padded >= min_atr_pct * np.abs(closes),
   atr_padded, np.nan)` (or similar), not a scalar-per-element Python loop calling
   `_is_valid_atr` (`compute_batch()` runs across the full multi-million-row historical corpus,
   this is a hot path -- see CLAUDE.md's efficiency notes on `compute_batch()`).
3. Thread `config.atr_normalization_min_pct` through both call sites (`feature_factory.py:3555-3565`),
   same as todo 266's 4 call sites.
4. Update `_is_valid_atr`'s docstring once this lands (currently notes these 4 columns as the
   last known gap, added when todo 266 closed).

## Constraint

Batch into the next full corpus rebuild (todo 259's backfill -> Phase 151 waves 6-7), same as
todo 266 -- this is a real compute-output change that should land before, not after, the
recompute so it doesn't need its own separate re-run.
