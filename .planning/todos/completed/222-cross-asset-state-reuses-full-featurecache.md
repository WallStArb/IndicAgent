---
status: completed
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

## Fixed 2026-07-31

Steps 1-3 done, step 4 deliberately NOT done (see below). In `src/intelligence/feature_cache.py`:

1. Extracted `_compute_cross_asset(state, spy_bars, tlt_bars, shy_bars, config)` -- a module-
   level function containing exactly the math `FeatureCache.update_cross_asset()` used to
   have inline. Operates on any object exposing `.vix_z`/`.flight_quality`/`.yield_slope_z`/
   `._spy_realized_vol_history`/`._yield_ratio_history` (duck typing), so it works unmodified
   against either `FeatureCache` or the new `CrossAssetState`.
2. Added `CrossAssetState` -- a small dataclass with exactly those 5 fields plus a thin
   `update_cross_asset()` method delegating to `_compute_cross_asset()`. `FeatureCache.
   update_cross_asset()` was rewritten to delegate to the same function -- one implementation
   of the math, not two, closing the exact duplication risk this todo was filed to prevent.
3. `services/feature_vector_pipeline.py`'s `self._cross_asset_state` is now
   `dict[str, CrossAssetState]`, not `dict[str, FeatureCache]` -- `_get_cross_asset_state()`/
   `_refresh_cross_asset_state()`/`_cross_asset_state_for_bar()` type hints updated to match.
   The shared per-tf broadcast state no longer pays for FeatureCache's other ~87 fields.
4. New regression test `tests/unit/test_feature_factory.py::TestCrossAssetProxies::
   test_cross_asset_state_matches_feature_cache` asserts `CrossAssetState.update_cross_asset()`
   and `FeatureCache.update_cross_asset()` produce byte-identical output given the same
   inputs -- the guard against this shared implementation ever silently diverging again.
5. The 2 existing tests that call `FeatureCache().update_cross_asset(...)` directly needed
   ZERO changes -- `FeatureCache`'s public API/behavior is unchanged, only its internals now
   delegate. Confirmed by running both files unmodified: 97/97 passed.

**Step 4 (migrating `backfill_feature_factory.py`'s `_build_cross_asset_series()` onto the same
shared structure) deliberately NOT done.** Read that function directly before deciding: it's a
genuinely different algorithm, not just a different data structure -- an O(1)-per-date
incremental computation (`flight_quality` as cumulative TLT/SPY divergence from a fixed
period-start anchor) built for processing a full historical date range once, versus the live
path's O(window)-per-tick full-window recompute from a rolling buffered `BarHistory`. Unifying
them would be a behavior-changing algorithmic change to the batch path that computes the
in-flight corpus rebuild's training data -- correctly out of scope for a data-structure
cleanup, and not attempted. `backfill_feature_factory.py` was not touched.

`tests/unit/ -q` full suite green (exit 0) throughout. `ic_engine`'s in-flight corpus rebuild
confirmed still healthy and untouched (this fix only touches `feature_cache.py` and
`feature_vector_pipeline.py`, neither in its dependency chain).
