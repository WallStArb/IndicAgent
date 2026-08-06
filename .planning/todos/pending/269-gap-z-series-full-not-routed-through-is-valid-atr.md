---
status: pending
priority: P3
filed: 2026-08-05
source: /simplify reuse-angle review of todo 268's fix (_dist_from_high_series_full/
  _dist_from_low_series_full consolidation onto _is_valid_atr_series)
---

## What

`_gap_z_series_full` (`src/intelligence/feature_factory.py:2283`) computes `gap_z`
(ATR-normalized open gap, rolling z-scored) via `gap_raw = (opens[...] - closes[...]) /
atr_for_gap`, gated by its own absolute-epsilon guard: `np.where(atr_for_gap[:gap_high] >
1e-10, atr_for_gap[:gap_high], 1.0)` (line 2311-2313). Same ATR-ratio shape as the 14+2
features already consolidated onto `_is_valid_atr`/`_is_valid_atr_series` by todos 237, 266,
and 268 -- a legitimately-positive but numerically-tiny ATR relative to the gapping close_
passes uncaught and `gap_z` can explode the same BIL-style way.

## Why not fixed as part of todo 268

Found during `/simplify`'s reuse-angle review of todo 268's diff. Not a drop-in reuse of
`_is_valid_atr_series(atr_padded, closes, min_atr_pct)`: `_gap_z_series_full` computes its own
local ATR series (`atr_core = _atr_series_full(highs, lows, closes, period)`, independent of
the shared `atr_padded` other `_series_full` functions read from `_precompute_series`) with a
shifted/offset alignment (`atr_for_gap = atr_core[:-1]`, indexed against `opens[2:2+gap_high]`/
`closes[1:1+gap_high]` -- gap at position i normalized by ATR at position i-1, not i). Routing
this through `_is_valid_atr_series` needs the *close being gapped from* (`closes[1:1+gap_high]`,
not the padded array's own alignment) as the relative-floor reference, so it's a real, scoped
fix -- not a same-diff bolt-on -- and changes `gap_z`'s live output for every bar, same caution
todo 266/268 gave their own functions.

## Fix

Route `_gap_z_series_full`'s ATR guard through `_is_valid_atr_series(atr_for_gap[:gap_high],
closes[1:1+gap_high], config.atr_normalization_min_pct)` (correct close_ reference is the
pre-gap close, matching what the ratio is normalized against) in place of the inline
`atr_for_gap[:gap_high] > 1e-10`. Thread `config.atr_normalization_min_pct` into the function's
signature (currently takes `period`/`zscore_window` only, no `config`/`min_atr_pct` -- check its
one call site, `feature_factory.py:3490`-ish `gap_z=_gap_z_series_full(...)`, for what's already
in scope there). Same TDD/BIL-regression-test discipline as todos 266/268.

## Constraint

Batch into the next full corpus rebuild (todo 259's backfill -> Phase 151 waves 6-7), same as
todos 266/268 -- a real compute-output change that should land before, not after, the recompute.
