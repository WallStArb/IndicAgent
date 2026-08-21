# 328 - Confirmed dead code found investigating todo 327 (timeframe vocabulary) - separate cleanup, not consolidation

**Filed:** 2026-08-15
**Source:** Investigation for [[327]] (timeframe CVR consolidation). Before writing that plan, checked
actual liveness of every one of the originally-listed 9 `timeframe`-tuple call sites rather than
assuming all 9 needed fixing. 4 turned out to be dead code, one of them a whole misidentified file.
Out of scope for 327 (which is about consolidating *live* scatter into CVR) - filed separately per
[[feedback_simplify_scope_discipline]] ("leave known out-of-scope tech debt alone... note don't fix").

## Confirmed dead

1. **`src/intelligence/pipeline/feature_pipeline_executor.py` - whole file, not just its
   `_STANDARD_TFS` constant.** Originally assumed live because its name resembles the genuinely-live
   `services/feature_vector_pipeline.py` (v3.0). It is not the same system: its own docstring says
   "Extracted from `IntelligencePipeline._run_i1_to_i6` as part of Phase 089 DAG decomposition" -
   this is v2.x I1-I7 architecture, archived per root `CLAUDE.md`
   (`indicagent-intelligence-pipeline.service` is `failed`, `ExecStart` points at a deleted file).
   Confirmed zero live instantiation: `grep -rln "FeaturePipelineExecutor(" src/ services/` returns
   nothing; every other reference is a sibling module in the same dead `src/intelligence/pipeline/`
   package or its own isolated unit test (`tests/unit/pipeline/test_feature_pipeline_executor_seed.py`).
   Its `_STANDARD_TFS` (6 tfs, matching the live orchestrator's set) is therefore also dead - the
   "collision" with `bar_history.py`'s `_STANDARD_TFS` I originally flagged in 327 was two dead
   constants, not one live + one dead.
2. **`src/core/bar_history.py::_STANDARD_TFS`** - defined at line 27, referenced nowhere else in the
   file or anywhere in the repo (only `BarHistory` the class is imported; the module-level constant
   never is). Vulture didn't flag it - worth checking vulture's confidence threshold/whitelist
   separately, since a genuinely dead module-level constant slipping past it is itself a small gap.
3. **`src/core/service_utils.py::CROSS_ASSET_VALID_TFS`** - defined, zero importers anywhere.
4. **`src/intelligence/utils.py`** - the whole bare file, not just its `INTRADAY_ONLY_TFS` copy.
   Confirmed unreachable by Python's own import resolver: `import src.intelligence.utils` resolves
   to the *package* `src/intelligence/utils/__init__.py` (verified live:
   `.venv/bin/python -c "import src.intelligence.utils as u; print(u.__file__)"` →
   `.../utils/__init__.py`), because Python's `PathFinder` prefers a package over a same-named
   module file in the same directory. Last commit touching `utils.py` (`c1ebc240f`) predates the
   commit that created the `utils/` package (`7047c5df4`, "promote composites/common.py to
   utils/common.py") - it should have been `git rm`'d as part of that refactor and wasn't.
5. **`src/intelligence/utils/core.py::INTRADAY_ONLY_TFS` + `guard_intraday_only()`** - the *live*
   package copy (reachable, unlike #4), but its only callers are
   `src/intelligence/trading/anchored_vwap_reversion.py` and its archived twin. Checked
   `register_plugins.py`: it imports `anchored_vwap_reversion` from `.archive.trading_i7.*`, not
   from `src.intelligence.trading.*` - the same pattern found for every I7 plugin file during 327's
   investigation (the non-archive copies under `src/intelligence/trading/` are never actually wired
   into the plugin registry; `archive/trading_i7/` is). Since the whole I1-I7 pipeline this feeds is
   itself archived (`indicagent-intelligence-pipeline.service` failed), `guard_intraday_only` is
   unreachable from any live path.

## Fix

Standard dead-code removal: delete `feature_pipeline_executor.py` + its isolated unit test (confirm
one more time nothing else references it immediately before deleting - a repo this size can hide a
late import), delete `bar_history.py::_STANDARD_TFS` and `service_utils.py::CROSS_ASSET_VALID_TFS`
(single-line removals), delete `utils.py` (whole file), and either delete `guard_intraday_only`/
`INTRADAY_ONLY_TFS` from `utils/core.py` or leave them (harmless dead code, lower priority - check
whether `src/intelligence/trading/anchored_vwap_reversion.py` itself is worth deleting too, since
it's apparently *also* an orphaned non-wired copy, same as its 6 sibling files found live during
327 - that's a bigger sweep, possibly its own todo).

Not urgent - genuinely dead code, zero runtime impact either way. Batch with a future `/simplify`
pass rather than a dedicated session.

## Closed 2026-08-21

Re-verified all 4 original claims live before deleting anything (not trusted from the
filing text) -- all still true, 6 days later. Executed items 1-4; left item 5
(`guard_intraday_only`/`INTRADAY_ONLY_TFS` in the live-but-unreachable `utils/core.py`
package copy) untouched exactly as the todo's own text said, lower priority, its own
possible future todo.

**Scope expanded beyond the original filing's 4 items -- found live, not assumed:**

1. **`src/intelligence/pipeline/__init__.py` imported and re-exported
   `FeaturePipelineExecutor`/`FeaturePipelineResult`** from the file being deleted --
   the original filing didn't check this. Deleting the file without fixing this would
   have broken `import src.intelligence.pipeline` outright. Verified the one live
   importer of this package (`services/feature_vector_pipeline.py`) only uses
   `CacheManager`/`OutputQueue`/`PerKeyWorkerManager`/`PluginStateManager` -- confirmed
   safe to drop the two names from the import list and `__all__`.
2. **A second, previously-unmentioned test file**
   (`tests/unit/pipeline/test_feature_pipeline_executor.py`, distinct from the filing's
   `..._seed.py`) directly reads `feature_pipeline_executor.py`'s source via
   `pathlib.Path(...).read_text()` in one of its 3 tests (`ast`-parsing to count
   `build_flat_features` call sites) -- would have hit `FileNotFoundError` post-deletion.
   Its other 2 tests document a "PERF-05" behavioral-equivalence decision specific to
   the module being deleted, meaningless without it. Deleted the whole file, not just
   patched the one test that would literally break.
3. **`utils.py`'s package-shadowing was re-verified with an extra step** beyond the
   original investigation: confirmed live via direct import that every name the many
   `from src.intelligence.utils import X` call sites need (`clamp`/`find_peaks`/
   `find_troughs`/`safe_corr`/`is_num`/`linreg_slope`/`utc_datetime_from_df`,
   including from genuinely-live `src/intelligence/feature_factory.py`) resolves
   correctly through the package (`utils/__init__.py` → `utils/core.py`), independent
   of the bare file's existence -- the broad grep for `from src.intelligence.utils
   import` initially looked alarming (dozens of hits, including live files) before
   confirming they all transparently resolve to the package, not the file being deleted.

**Deletions:** `src/intelligence/pipeline/feature_pipeline_executor.py`,
`tests/unit/pipeline/test_feature_pipeline_executor_seed.py`,
`tests/unit/pipeline/test_feature_pipeline_executor.py`, `src/intelligence/utils.py`.
**Single-line removals:** `src/core/bar_history.py::_STANDARD_TFS`,
`src/core/service_utils.py::CROSS_ASSET_VALID_TFS` (+ its now-obsolete
`tools/vulture_whitelist.py` entry, since the code it whitelisted no longer exists).

**Cascading dead-code discovery, whitelisted not fixed:** deleting
`feature_pipeline_executor.py` exposed 12 new vulture findings in sibling files
(`signal_processor.py`, `state_manager.py`, `executor.py`, `bar_history.py`,
`vix_context.py`, `feature_repository.py`, `feature_vector_pipeline.py`) --
functions/methods that were only reachable through call chains running through the
now-deleted file, invisible to vulture's static analysis until that entry point was
gone. This is real evidence the broader `src/intelligence/pipeline/` package likely
has more dead code than todo 328 ever scoped to find -- exactly the shape of question
todo 223 (the 153-file/30k-line I1-I7 dead-code audit) already exists to answer, not
a re-litigation to do here. Whitelisted all 12 with an explicit note pointing at todo
223, matching this project's established "grandfather existing, block new" vulture
discipline (todo 309) rather than either leaving CI red or scope-creeping into that
much bigger audit mid-cleanup.

**Left alone, per the original filing's own comments:** stale references to
`feature_pipeline_executor.py` by name in `feature_flattening.py`/`signal_processor.py`/
`macro_context.py` docstrings/comments (describing the dead architecture historically,
still roughly accurate) -- not present-tense claims, no fix needed.

Full `tests/unit/` suite green (no regressions), ruff/black clean, `vulture` exit 0.
