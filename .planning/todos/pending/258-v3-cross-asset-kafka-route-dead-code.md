---
status: pending
priority: P3
found_during: phase-151-plan-04
found_date: 2026-08-05
---

# v3 cross-asset Kafka route is dead code whose shape actively misleads

## What

The v3 cross-asset Kafka route is dead code that shares a confusingly similar name with a
live, unrelated mechanism -- exactly the shape of ambiguity that let todo 158's class of bug
(a live-path feature silently frozen) survive unnoticed.

`services/cross_asset_analyzer.py:471` is the sole producer on the `topic_cross_asset` topic. It
publishes `es_nq_spread_z`/`corr_z`/`active_pair` -- fields unrelated to
`vix_z`/`flight_quality`/`yield_slope_z` (the v3 `FeatureVector` cross-asset fields) or to Phase
151 Plan 04's 7 new spread/beta fields. Its unit, `indicagent-cross-asset.service`, is
`inactive (dead)` (confirmed live 2026-08-05).

`src/intelligence/pipeline/cache_manager.py:235`, `CacheManager.update_cross_asset(tf, payload)`,
consumes that Kafka payload and stores it into `self._cross_asset[tf]`. The only reader of that
stored state is the archived v2.x `src/intelligence/pipeline/feature_pipeline_executor.py:287-294`
-- never v3's `FeatureVector`.

`FeatureCache.update_cross_asset()` (`src/intelligence/feature_cache.py`) is a **completely
different method on a different object** with the same name and no relationship to the Kafka
route above. Two same-named methods, one live-but-irrelevant-to-v3 (`CacheManager`'s), one
relevant-but-was-uncalled-on-the-live-path (`FeatureCache`'s, until todo 221/222 fixed it via a
third, separate mechanism -- see Disposition below) is precisely how a gap like this survives
unnoticed: a reader searching for "cross-asset" call sites finds the wrong one first.

## Disposition: the correctness half is ALREADY FIXED, independently of this todo

Plan 151-04's original review pass (2026-07-24) found `FeatureCache.update_cross_asset()` had no
live caller at all -- `vix_z`/`flight_quality`/`yield_slope_z` were frozen at `0.0` on every live
bar, contaminating `feature_vectors`, the table this project's entire IC measurement reads. That
review scoped the functional fix to plan 151-09 (wave 5).

**Re-verified during Plan 04's Task 4 execution (2026-08-05): that gap was already closed by todo
221/222, landed 2026-07-31** (commits `32f1cf0a` "fix(feature-vector-pipeline): actually land todo
221's code changes", `c83b2bdc` "refactor(feature-cache): extract CrossAssetState, close todo
222") -- **before** this todo was filed but **after** plan 151-04/151-09 were authored (2026-07-24)
and after Phase 151-01/02/03 ran without surfacing it. The live fix uses a fourth mechanism,
distinct from all three named above: `CrossAssetState` (`src/intelligence/feature_cache.py`) +
`FeatureVectorPipeline._cross_asset_state_for_bar()`/`_refresh_cross_asset_state()`/
`_warm_cross_asset_state()`/`_get_cross_asset_state()` (`services/feature_vector_pipeline.py`),
wired directly into `_process_bar_compute()` (`cache.vix_z = cross_state.vix_z`, etc.) -- computed
incrementally from real bar history via `CrossAssetState.update_cross_asset()`, never through
Kafka. See `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-04-SUMMARY.md`'s
Task 4 for the full measurement (the historical zero-value window is capped at 2026-06-23 ->
2026-07-07 because live IBKR ingestion halted 2026-07-27, three days after the plan's original
2026-07-24 review -- not "growing every trading day" as originally assumed; no post-fix live rows
exist yet to empirically confirm the 2026-07-31 fix in production, since ingestion has been paused
since before it landed).

**Consequence for plan 151-09**: its Task 2 as currently written assumes
`vix_z`/`flight_quality`/`yield_slope_z` are still broken on the live path and proposes building a
NEW `build_cross_asset_series`-based live loader from scratch. That premise is now false for the 3
legacy fields. 151-09 needs re-scoping before it executes -- likely narrowed to extending the
already-live `CrossAssetState`/`_cross_asset_state_for_bar()` mechanism with Plan 04's 7 new fields
(`tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast/slow/z`, `equity_beta_z`/`rate_beta_z`) rather than
replacing a mechanism that already works for the original 3. This re-scoping is NOT done by this
todo -- flagging it here and in 151-04-SUMMARY.md so whoever executes 151-09 doesn't build on the
stale premise.

## What remains (this todo's actual scope)

The dead-code hygiene question, independent of the correctness fix above: **should the v3
pipeline stop subscribing to `topic_cross_asset` altogether, or is that subscription still wanted
for the possible v2.x revival** recorded in `project_i1_i7_parallel_reimplementation_intent`
(memory)? Deleting `CacheManager.update_cross_asset()`/the `topic_cross_asset` subscription would
close the misleading-name hazard permanently, but would also remove infrastructure the project has
stated intent to revive independently. This todo poses the question rather than answering it.

## Why P3

Classified P3 (not P2) precisely because the correctness half (contaminated live `feature_vectors`
rows) is no longer an open risk -- see Disposition above. What remains is naming/dead-code hygiene
plus an open architectural question (v2.x revival) that this todo does not have standing to answer
unilaterally.

## References

- `services/cross_asset_analyzer.py:471` (sole `topic_cross_asset` producer, unit `inactive (dead)`)
- `src/intelligence/pipeline/cache_manager.py:235` (`CacheManager.update_cross_asset`, dead consumer)
- `src/intelligence/pipeline/feature_pipeline_executor.py:287-294` (archived v2.x, sole reader)
- `src/intelligence/feature_cache.py` (`FeatureCache.update_cross_asset` / `CrossAssetState.update_cross_asset` -- the two live, unrelated, same-named methods)
- `services/feature_vector_pipeline.py` (`_cross_asset_state_for_bar` et al. -- the actual live fix, todo 221/222)
- todo 158 (`above_wk_vwap` permanently frozen at 0.0 in the live path) -- same bug class
- todo 159 (`FeatureCache` not warmed from seeded history) -- adjacent live-path warm-up precedent
- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-09-PLAN.md` -- owns the (now partially stale) functional-fix scope, needs re-validation before execution
- `.planning/phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-04-SUMMARY.md` -- Task 4's full contamination measurement and disposition record
