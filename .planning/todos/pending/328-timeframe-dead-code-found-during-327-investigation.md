# 328 - Confirmed dead code found investigating todo 327 (timeframe vocabulary) — separate cleanup, not consolidation

**Filed:** 2026-08-15
**Source:** Investigation for [[327]] (timeframe CVR consolidation). Before writing that plan, checked
actual liveness of every one of the originally-listed 9 `timeframe`-tuple call sites rather than
assuming all 9 needed fixing. 4 turned out to be dead code, one of them a whole misidentified file.
Out of scope for 327 (which is about consolidating *live* scatter into CVR) — filed separately per
[[feedback_simplify_scope_discipline]] ("leave known out-of-scope tech debt alone... note don't fix").

## Confirmed dead

1. **`src/intelligence/pipeline/feature_pipeline_executor.py` — whole file, not just its
   `_STANDARD_TFS` constant.** Originally assumed live because its name resembles the genuinely-live
   `services/feature_vector_pipeline.py` (v3.0). It is not the same system: its own docstring says
   "Extracted from `IntelligencePipeline._run_i1_to_i6` as part of Phase 089 DAG decomposition" —
   this is v2.x I1-I7 architecture, archived per root `CLAUDE.md`
   (`indicagent-intelligence-pipeline.service` is `failed`, `ExecStart` points at a deleted file).
   Confirmed zero live instantiation: `grep -rln "FeaturePipelineExecutor(" src/ services/` returns
   nothing; every other reference is a sibling module in the same dead `src/intelligence/pipeline/`
   package or its own isolated unit test (`tests/unit/pipeline/test_feature_pipeline_executor_seed.py`).
   Its `_STANDARD_TFS` (6 tfs, matching the live orchestrator's set) is therefore also dead — the
   "collision" with `bar_history.py`'s `_STANDARD_TFS` I originally flagged in 327 was two dead
   constants, not one live + one dead.
2. **`src/core/bar_history.py::_STANDARD_TFS`** — defined at line 27, referenced nowhere else in the
   file or anywhere in the repo (only `BarHistory` the class is imported; the module-level constant
   never is). Vulture didn't flag it — worth checking vulture's confidence threshold/whitelist
   separately, since a genuinely dead module-level constant slipping past it is itself a small gap.
3. **`src/core/service_utils.py::CROSS_ASSET_VALID_TFS`** — defined, zero importers anywhere.
4. **`src/intelligence/utils.py`** — the whole bare file, not just its `INTRADAY_ONLY_TFS` copy.
   Confirmed unreachable by Python's own import resolver: `import src.intelligence.utils` resolves
   to the *package* `src/intelligence/utils/__init__.py` (verified live:
   `.venv/bin/python -c "import src.intelligence.utils as u; print(u.__file__)"` →
   `.../utils/__init__.py`), because Python's `PathFinder` prefers a package over a same-named
   module file in the same directory. Last commit touching `utils.py` (`c1ebc240f`) predates the
   commit that created the `utils/` package (`7047c5df4`, "promote composites/common.py to
   utils/common.py") — it should have been `git rm`'d as part of that refactor and wasn't.
5. **`src/intelligence/utils/core.py::INTRADAY_ONLY_TFS` + `guard_intraday_only()`** — the *live*
   package copy (reachable, unlike #4), but its only callers are
   `src/intelligence/trading/anchored_vwap_reversion.py` and its archived twin. Checked
   `register_plugins.py`: it imports `anchored_vwap_reversion` from `.archive.trading_i7.*`, not
   from `src.intelligence.trading.*` — the same pattern found for every I7 plugin file during 327's
   investigation (the non-archive copies under `src/intelligence/trading/` are never actually wired
   into the plugin registry; `archive/trading_i7/` is). Since the whole I1-I7 pipeline this feeds is
   itself archived (`indicagent-intelligence-pipeline.service` failed), `guard_intraday_only` is
   unreachable from any live path.

## Fix

Standard dead-code removal: delete `feature_pipeline_executor.py` + its isolated unit test (confirm
one more time nothing else references it immediately before deleting — a repo this size can hide a
late import), delete `bar_history.py::_STANDARD_TFS` and `service_utils.py::CROSS_ASSET_VALID_TFS`
(single-line removals), delete `utils.py` (whole file), and either delete `guard_intraday_only`/
`INTRADAY_ONLY_TFS` from `utils/core.py` or leave them (harmless dead code, lower priority — check
whether `src/intelligence/trading/anchored_vwap_reversion.py` itself is worth deleting too, since
it's apparently *also* an orphaned non-wired copy, same as its 6 sibling files found live during
327 — that's a bigger sweep, possibly its own todo).

Not urgent — genuinely dead code, zero runtime impact either way. Batch with a future `/simplify`
pass rather than a dedicated session.
