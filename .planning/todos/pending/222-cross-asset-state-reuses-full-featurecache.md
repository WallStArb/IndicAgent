---
status: pending
priority: P3
filed: 2026-07-31
source: /simplify altitude review of todo 221's cross-asset broadcast fix
  (commit 577b4137/e42f19d5) -- flagged by an independent altitude-focused review
  agent, cross-checked against backfill_feature_factory.py before filing.
---

# `feature_vector_pipeline.py`'s cross-asset broadcast state reuses the full ~90-field FeatureCache for 3 fields

## Problem

Todo 221's fix (`services/feature_vector_pipeline.py`) introduced
`self._cross_asset_state: dict[str, FeatureCache]` -- a shared per-tf state used purely to
carry `vix_z`/`flight_quality`/`yield_slope_z` (plus 2 internal deques) between SPY/TLT/SHY
bar arrivals and every symbol's own per-bar compute. It instantiates a full `FeatureCache()`
-- the ~90-field dataclass meant to hold one symbol's entire per-bar compute state -- just to
use 3 of those fields.

`services/backfill_feature_factory.py`, which computes the identical 3 fields for the batch
path, deliberately does NOT do this: `_build_cross_asset_series()` (line ~250) builds a
dedicated incremental structure with exactly the 3 raw deques/output floats it needs, keyed
by date, kept separate from the per-symbol `FeatureCache()` instances used for real per-bar
compute. The live pipeline's fix diverges from this established convention.

## Why not fixed inline

Fixing this properly means extracting a small dedicated dataclass (e.g. `CrossAssetState` with
`vix_z`/`flight_quality`/`yield_slope_z` + the 2 internal deques) that both
`feature_cache.py`'s `update_cross_asset()` and `backfill_feature_factory.py`'s
`_build_cross_asset_series()` would share -- which means moving `update_cross_asset()`'s
implementation (or its logic) off `FeatureCache` itself. That's a real, cross-file refactor:

- `FeatureCache.update_cross_asset()` is also called directly in 2 existing test files
  (`tests/unit/test_feature_factory.py`, `tests/unit/services/test_backfill_feature_factory.py`)
  that would need updating regardless of which shape the extraction takes.
- `backfill_feature_factory.py` currently has its own independent, correct, unrelated
  implementation of the same 3 fields -- touching it isn't needed to fix todo 221 and adds risk
  while the corpus rebuild is in flight.
- Scope well beyond a `/simplify` pass on todo 221's diff.

## What needs to happen

1. Design a small shared `CrossAssetState`-shaped structure (dataclass or similar) holding just
   `vix_z`/`flight_quality`/`yield_slope_z` + the 2 realized-vol/yield-ratio deques.
2. Decide whether `FeatureCache.update_cross_asset()` becomes a thin wrapper delegating to a
   free function operating on the new structure, or whether the new structure fully replaces
   the per-symbol `FeatureCache`'s 3 fields (still need to expose them as `cache.vix_z` etc.
   since `_process_bar_compute` copies values onto the per-symbol cache for `compute()` to
   read -- likely still needs a thin per-symbol-cache passthrough regardless of the internal
   representation).
3. Update the 2 existing tests that call `FeatureCache().update_cross_asset(...)` directly.
4. Decide whether `backfill_feature_factory.py`'s `_build_cross_asset_series()` should be
   migrated onto the same shared structure (closing the "two divergent implementations of the
   same 3 fields" gap noted by the review) -- real design call, not mechanical.

## Sizing

Small-to-medium -- mostly a data-structure extraction plus 2 test-file updates, but touches a
shared class 3 files reference, so needs care, not a blind refactor.
