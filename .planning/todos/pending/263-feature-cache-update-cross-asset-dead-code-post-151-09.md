---
status: pending
priority: P3
found_during: phase-151-post-execution-simplify
found_date: 2026-08-05
---

# FeatureCache.update_cross_asset()/CrossAssetState now dead code in production, but carry real test investment -- needs an explicit keep-or-delete decision

## What

Confirmed by direct grep (2026-08-05), corroborated independently by a /simplify reuse-review
agent: `FeatureCache.update_cross_asset()` (`src/intelligence/feature_cache.py:558`, extended
by Phase 151 Plan 04 with tip_tlt_ret_z/hyg_lqd_ret_z/sb_corr_fast/slow/z -- ~90 new lines) and
`CrossAssetState` (`src/intelligence/feature_cache.py:762`, todo 222's original class) have
**zero production call sites** as of Plan 09's merge:

```
grep -rn "\.update_cross_asset(" --include="*.py" src/ services/ | grep -v tests/
# only matches inside feature_cache.py's own docstrings/comments -- no live caller
grep -rn "CrossAssetState(" --include="*.py" src/ services/
# zero matches outside tests/
```

Root cause: Plan 09 (same phase, merged after Plan 04) replaced the live pipeline's cross-asset
mechanism entirely -- `services/feature_vector_pipeline.py` now calls
`build_cross_asset_series()` (the new shared Ring-1 module,
`src/intelligence/features/cross_asset_series.py`) via a daily-grain, bisect-lookup mechanism,
not `FeatureCache.update_cross_asset()`. Plan 09's own SUMMARY.md documents this as deliberate
("CrossAssetState the CLASS stays in feature_cache.py... only its live CALLER was removed") but
does not address whether the method/class itself should eventually be deleted.

## Why this needs a decision, not a unilateral delete

This is NOT a small "delete 5 unused lines" case. `tests/unit/test_feature_factory.py` has ~9
dedicated tests exercising this exact code (`test_update_cross_asset_populates_vix_z`,
`_flight_quality`, `_yield_slope_z`, `_tip_tlt_and_hyg_lqd`, plus a parity test asserting
`CrossAssetState.update_cross_asset()` and `FeatureCache.update_cross_asset()` produce
byte-identical output -- todo 222's original design contract). Deleting the production code
means also deleting real test coverage that documents a genuine historical design decision, not
just removing dead weight. A code-cleanup pass alone shouldn't make that call unilaterally.

## Impact

None on correctness or performance today -- confirmed this dead code has ZERO bearing on
`services/backfill_feature_factory.py`'s corpus recompute (Phase 151-07), since the batch path
never used `FeatureCache.update_cross_asset()`/`CrossAssetState` in the first place (it has its
own independent `build_cross_asset_series()` implementation, now the shared one both live and
batch use post-Plan-09). This is pure dead-weight in the live-daemon code path, not a
correctness risk.

## Recommended options, in order of least-to-most invasive

1. **Leave as-is** -- keep as a documented historical reference / fallback implementation. Low
   cost (a few hundred lines + tests), zero risk.
2. **Delete the production methods, keep the parity test as a golden-master regression** against
   `build_cross_asset_series()` instead (repurpose rather than delete the test intent).
3. **Delete both the production code and its dedicated tests entirely** -- cleanest, but throws
   away the todo-222 design documentation the parity test currently encodes.

## References

- `src/intelligence/features/cross_asset_series.py` -- the mechanism that superseded this
- `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-SUMMARY.md` -- Plan 09's own "deliberately NOT extended" framing
- `.planning/todos/completed/222-cross-asset-state-reuses-full-featurecache.md` -- CrossAssetState's original design intent
