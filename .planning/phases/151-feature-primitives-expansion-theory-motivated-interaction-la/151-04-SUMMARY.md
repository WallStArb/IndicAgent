---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 04
subsystem: feature-factory
tags: [feature-factory, feature-vectors, apr, concept-registry, timescaledb, cross-asset, feature-engineering]

# Dependency graph
requires:
  - phase: 151-03
    provides: live FeatureVector baseline (270 fields after wave 2), the _PHASE151_RECENCY_FIELD_NAMES derived-slice persistence pattern this plan extends
  - phase: 170-feature-domain-concept-registry-migration
    provides: concept_registry/concept_gate schema + ic_engine.py's PARITY PRECONDITION gate
provides:
  - 7 new FeatureVector fields (277 total) -- tip_tlt_ret_z, hyg_lqd_ret_z, sb_corr_fast/slow/z (symbol-independent) + equity_beta_z/rate_beta_z (per-symbol, nullable for the factor proxy's own self-regression)
  - migration 289 (feature_vectors columns, feature_registry rows, APR keys under feature.* (not macro.*), concept_registry/concept_gate parity rows)
  - 7 new APR keys -- feature.tip_tlt.zscore_window, feature.hyg_lqd.zscore_window, feature.sb_corr.window_fast/window_slow/zscore_window, feature.factor_beta.window/zscore_window
  - CrossAssetRecord -- single shared NamedTuple contract (src/intelligence/features/cross_asset_series.py) replacing the old bare 3-tuple, keyword-construction only
  - _build_symbol_beta_series -- new O(D) per-symbol factor-beta builder in backfill_feature_factory.py
  - Live-data measurement (Task 4) proving the plan's original live-path cross-asset contamination premise is now partially stale -- see key-decisions
  - todo 258 (P3) -- residual v3 cross-asset Kafka dead-code question
affects: [151-09, 151-05, 151-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CrossAssetRecord NamedTuple (keyword-construction-only) replacing a bare positional tuple for a payload that keeps growing across phases -- Codex review precedent, generalizes to any future multi-field broadcast-state payload"
    - "Structural-copy-of-existing-block pattern applied a third time (after 151-03's autocorr/vol-spike pairs): tip_tlt_ret_z/hyg_lqd_ret_z are literal structural copies of yield_slope_z's compute block, same z-score-a-log-return-spread shape"
    - "Coverage-guarded date loop: TIP/HYG/LQD's later universe-entry date no longer skips the whole date the way SPY/TLT/SHY's absence does -- only the affected spread field zeros out, preserving vix_z/yield_slope_z for pre-listing dates"

key-files:
  created:
    - production/migrations/289_cross_asset_spread_beta_atomics.sql
    - src/intelligence/features/cross_asset_series.py
    - .planning/todos/pending/258-v3-cross-asset-kafka-route-dead-code.md
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/feature_cache.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/backfill_feature_factory.py
    - services/feature_vector_pipeline.py
    - .planning/todos/PRIORITIES.md
    - 15 test files (FeatureFactoryConfig construction sites, FeatureVector hand-typed sentinel constructors, update_cross_asset call sites, hardcoded field-count assertions)

key-decisions:
  - "Live codebase baseline was 270 fields at execution time, not the plan's stale 182/192/193 assumption (written 2026-07-24) -- 151-01/02/03 landed 88 intervening fields since. Scaled every downstream number (docstring tallies, migration numbering, INSERT SQL column count 279->286, test assertions) to the live 270->277 baseline throughout, matching 151-01/151-03's own documented correction pattern."
  - "Migration renumbered 262 (plan's provisional target) -> 289 (actual next-free number, re-verified against both `ls production/migrations/` and a live config_history query for any prior migration_289 row before applying)."
  - "CrossAssetValues (the plan's literal name) renamed to CrossAssetRecord: the repo's pre-commit hook enforces a Plugin-class-naming convention across all src/intelligence/*.py files requiring one of ~40 allow-listed suffixes ('Values' is not one; 'Record' is, matching the existing FeatureVectorRecord precedent in schemas.py). Sed-renamed project-wide (4 files) after the hook blocked the first commit attempt."
  - "CRITICAL FINDING (Task 4): the live-path cross-asset gap this plan's Interfaces section (and plan 151-09 in full) is scoped against -- vix_z/flight_quality/yield_slope_z frozen at 0.0 on the live path -- was independently fixed by todo 221/222 (commits 32f1cf0a, c83b2bdc, landed 2026-07-31), predating today's execution (2026-08-05) but postdating the plan's 2026-07-24 authoring and even 151-01/02/03's own execution. The live fix uses a FOURTH mechanism, distinct from all three the plan's Interfaces section names: `CrossAssetState` + `FeatureVectorPipeline._cross_asset_state_for_bar()`/`_refresh_cross_asset_state()`/`_warm_cross_asset_state()`, wired directly into `_process_bar_compute()` (`cache.vix_z = cross_state.vix_z`, etc.), computed incrementally from real bar history, never through Kafka. Confirmed via direct git log + source read, not assumed. See Task 4 section below for full detail and consequences for plan 151-09."
  - "CrossAssetState (todo 222's minimal 3-field sibling class) deliberately NOT extended with this plan's 5 new symbol-independent fields. Its own update_cross_asset() keeps the original 3-bar-list signature; only FeatureCache's signature grew to 6 bar lists. Reasoning: CrossAssetState exists specifically for callers needing only the original 3 fields (its own class docstring); extending it for fields the live path can't yet populate (equity_beta_z/rate_beta_z are per-symbol, and the 5 new symbol-independent fields have no live writer until 151-09) would be premature. This is an explicit scope boundary, not an oversight -- documented for whoever scopes 151-09 next."
  - "sb_corr_fast/slow/z's rolling correlation needs 2 more private deques (_sb_spy_log_ret_history, _sb_tlt_log_ret_history) beyond the plan's literal 5-deque list (_tip_tlt_ratio_history, _hyg_lqd_ratio_history, _sb_corr_history, _equity_beta_history, _rate_beta_history) -- the correlation is structurally uncomputable without persisting the raw SPY/TLT return series somewhere. Rule 2 addition (missing critical functionality), documented as a deviation below."
  - "equity_beta_z/rate_beta_z computed at DAILY grain, broadcast to all timeframes by date -- same cadence contract as vix_z/flight_quality/yield_slope_z. Computing per-tf would require broadcasting a 25.4M-row per-tf SPY array into every ProcessPoolExecutor worker; this script already OOM-killed twice at --workers 12 (151-RESEARCH.md Pitfall 6). Costs one extra _fetch_bars_from_db(conn, symbol, '1d') per (symbol, tf) call -- rebuilt per tf rather than once per symbol, mirroring the existing per-(symbol,tf) CTF-build precedent's own acceptable inefficiency."
  - "FEATURE_VECTOR_INSERT_SQL_PSYCOPG2 (the plan's literal name) does not exist in the codebase -- the real constant is FEATURE_VECTOR_INSERT_SQL_PSYCOPG (no '2' suffix). Used the correct name throughout; plan text was stale on this point (written before the constant's actual final name settled)."

requirements-completed: []

# Metrics
duration: 47min
completed: 2026-08-05
---

# Phase 151 Plan 04: Cross-Asset Spread/Beta Atomics Summary

**7 new tier-0 atomic FeatureVector fields (TIP/TLT and HYG/LQD spread z-scores, SPY/TLT rolling correlation fast/slow/z, per-symbol equity/rate factor betas) live in the batch compute path with matching feature_registry/concept_registry/concept_gate rows via migration 289 -- plus a Task 4 finding that the plan's own live-path-contamination premise (and plan 151-09's entire scope) is now partially stale, independently resolved by unrelated work that landed 2026-07-31.**

## Performance

- **Duration:** ~47 min
- **Started:** 2026-08-05T08:29:27-04:00 (approx, base commit)
- **Completed:** 2026-08-05T13:16:46Z
- **Tasks:** 4
- **Files modified:** 27 (2 created: cross_asset_series.py, migration 289; 1 new todo file)

## Accomplishments

- `FeatureVector` grew from 270 to 277 fields: `tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast`, `sb_corr_slow`, `sb_corr_z` (symbol-independent, `float`), `equity_beta_z`, `rate_beta_z` (per-symbol, `float | None`, nullable for the factor proxy's own self-regression) -- declared as one contiguous block immediately after 151-03's `abs_ret_autocorr_1`.
- New Ring-1 module `src/intelligence/features/cross_asset_series.py` defines `CrossAssetRecord` (renamed from the plan's `CrossAssetValues` -- see Deviations), a `NamedTuple` carrying the 8 symbol-independent cross-asset values with `0.0` defaults; every construction site uses keyword arguments, `grep -rl "class CrossAssetRecord"` returns exactly 1 file project-wide.
- `FeatureCache.update_cross_asset()`'s signature extended from 3 to 6 bar-list parameters (`+ tip_bars, hyg_bars, lqd_bars`); the 3 legacy fields still delegate to the unchanged `_compute_cross_asset()`, the 5 new symbol-independent fields computed inline as structural copies of the `yield_slope_z` block pattern. `CrossAssetState` (todo 222's minimal sibling) deliberately left untouched -- see key-decisions.
- `services/backfill_feature_factory.py`: 3 new symbol constants (`_TIP`, `_HYG`, `_LQD`), 3 new `_fetch_bars_from_db` calls (confirmed reading `market_data_ohlcv_tradeable`, per todo-124), `_build_cross_asset_series` extended to accept TIP/HYG/LQD bars and return `dict[date, CrossAssetRecord]` with a coverage guard (TIP/HYG/LQD's later universe-entry date zeros only the affected spread, never skips the whole date), a new `_build_symbol_beta_series` O(D) per-symbol builder for `equity_beta_z`/`rate_beta_z` at daily grain, `beta_by_date` threaded through `_compute_symbol_tf` into `FeatureFactory.compute_batch()`.
- `feature_vector_persistence.py`'s INSERT contract closed: new `_PHASE151_CROSS_ASSET_FIELD_NAMES` derived slice, 286 total columns/placeholders (was 279).
- Migration 289 applied to the live DB: 7 `feature_vectors` columns, 7 `feature_registry` rows (`tier='0_atomic'`, `added_phase='151'`, `group_name='macro'`), 7 APR key triplets under the sanctioned `feature.*` namespace (correcting todo 123's originally-proposed unsanctioned `macro.*` prefix), and 7 matching `concept_registry`/`concept_gate` rows satisfying Phase 170's `ic_engine.py` PARITY PRECONDITION gate.
- `feature_registry` row count verified live: 277, matching `FeatureVector`'s 277 dataclass fields; 28/28 Phase 151 tier-0 atomic candidates now registered.
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after every task's commit; `ruff check` clean on all touched Python.
- Task 4's live-data contamination measurement (see below) surfaced a significant correction to the plan's own premise, recorded in full with git evidence rather than asserted.

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2 (combined -- schema/config/cache + batch-path wiring, tightly coupled like 151-03's own Tasks 1+2)** - `302a47cd` (feat)
2. **Task 3: Migration 289 and unit tests** - `85d74202` (feat)
3. **Task 4: Contamination measurement + dead-code todo** - `6a0ab475` (docs)

_No separate plan-metadata commit -- this is a parallel worktree execution; SUMMARY.md is committed by the orchestrator's post-wave merge step per `parallel_execution` instructions._

## Files Created/Modified

- `production/migrations/289_cross_asset_spread_beta_atomics.sql` - 7 columns, 7 feature_registry rows, 7 APR triplets, 7 concept_registry/concept_gate parity rows
- `src/intelligence/features/cross_asset_series.py` (new) - `CrossAssetRecord` NamedTuple, the single shared cross-asset contract
- `src/intelligence/schemas.py` - `FeatureVector` +7 fields, docstring tally 270->277
- `src/intelligence/feature_factory.py` - 7 new `FeatureFactoryConfig` fields, `FEATURE_VECTOR_DOMAIN` +7 entries (all `"macro"`), `_build_feature_vector` signature/body +7 params, `compute()`/`compute_batch()` both read/thread the new fields (batch via `cross_asset_by_date`/`beta_by_date`, live via `cache.*` + SPY/TLT None special-case), `_cold_start_vector` +7 (5 literal `0.0`, 2 `None`)
- `src/intelligence/feature_cache.py` - 7 new cache fields + 7 new private deques (5 from the plan + 2 Rule-2 additions), `update_cross_asset()` extended to 6-bar-list signature, new `_safe_corr()` helper
- `src/intelligence/features/feature_vector_persistence.py` - `_PHASE151_CROSS_ASSET_FIELD_NAMES` slice, INSERT contract closed (279->286 columns)
- `services/backfill_feature_factory.py` - TIP/HYG/LQD constants + fetches, extended `_build_cross_asset_series`, new `_build_symbol_beta_series`, `beta_by_date` threaded through `_compute_symbol_tf`
- `services/feature_vector_pipeline.py` - 7 new APR keys wired into `_THRESHOLD_KEYS` + `FeatureFactoryConfig` construction (CrossAssetState/live-path wiring for the 5 new fields explicitly NOT touched -- 151-09's job)
- `tests/unit/test_feature_factory.py` - `_make_config` +7 fields, 4 `update_cross_asset` call sites extended to 6-bar-list signature, 2 new tests (tip/hyg/lqd finiteness, sb_corr bounded/extremes via incremental calls), field-count assertion 270->277
- `tests/unit/services/test_backfill_feature_factory.py` - `_make_config`/`_make_zero_vector` +7 fields each, `_build_cross_asset_series`/`_reference_cross_asset_series` extended to 6-bar-list + `CrossAssetRecord` return type, new `TestBuildSymbolBetaSeries` class (SPY/TLT None special-cases, non-proxy finite betas), new TIP/HYG/LQD partial-coverage test, `test_cross_asset_from_dict_not_cache` updated to construct `CrossAssetRecord`
- 15 other test files (`test_canary_predictors.py`, `pipeline_helpers.py`, `test_feature_vector_writer.py`, `test_feature_vector_writer_column_mapping.py`, `test_feature_factory_p7.py`, `test_feature_factory_batch_parity.py`, 9 SMC/structure/volume-profile test files) - added the 7 new `FeatureFactoryConfig`/`FeatureVector` kwargs, fixed hardcoded field-count assertions
- `.planning/todos/pending/258-v3-cross-asset-kafka-route-dead-code.md` (new) - the residual P3 dead-code question
- `.planning/todos/PRIORITIES.md` - new row for todo 258

## Task 4: Live-Path Contamination Measurement (verbatim)

**Part A -- quantified against live data, all 4 timeframes:**

| tf | zero-valued rows (`vix_z=0.0`) | non-zero rows | zero window (min/max `bar_ts`) | symbols affected |
|---|---|---|---|---|
| 5m | 12,036 | 229,108 | 2026-06-23 -> 2026-07-07 | 80 |
| 15m | 4,030 | 77,979 | 2026-06-23 -> 2026-07-07 | 80 |
| 1h | 1,000 | 20,538 | 2026-06-23 -> 2026-07-07 | 80 |
| 1d | 114 | 2,947 | 2026-06-23 -> 2026-07-07 | 62 |

`systemctl is-active`: `indicagent-feature-vector-pipeline` = **active**, `indicagent-cross-asset` = **inactive** (unchanged from the plan's original 2026-07-24 finding -- no new Kafka producer has appeared).

**Corrections to the plan's original framing, established with evidence:**

1. **The contamination is NOT "growing every trading day"** as the plan's Interfaces section states. The zero-valued window is capped at 2026-06-23 -> 2026-07-07 across all 4 timeframes -- it stopped growing because live IBKR ingestion has been intentionally halted since 2026-07-27 (confirmed separately, `project_ingestion_intentionally_paused` in memory; also visible directly: `MAX(bar_ts)` across the entire `feature_vectors` corpus is 2026-07-28, three days after the ingestion halt and four days before the fix below landed).
2. **The underlying live-path bug is already fixed**, independently of this plan and of plan 151-09 (which exists specifically to fix it). `git log` confirms two commits landed 2026-07-31: `32f1cf0a` ("fix(feature-vector-pipeline): actually land todo 221's code changes") and `c83b2bdc` ("refactor(feature-cache): extract CrossAssetState, close todo 222"). Direct source read confirms `services/feature_vector_pipeline.py`'s `_process_bar_compute()` now does `cross_state = self._cross_asset_state_for_bar(bar); cache.vix_z = cross_state.vix_z; cache.flight_quality = cross_state.flight_quality; cache.yield_slope_z = cross_state.yield_slope_z` -- a genuinely live, working mechanism (`CrossAssetState.update_cross_asset()` called incrementally per new bar, with a buffered-history warm-up replay on cache creation, mirroring todo-159's precedent). This is a FOURTH mechanism, distinct from the three the plan's own Interfaces section names as broken/dead (the Kafka `CacheManager` route, `FeatureCache.update_cross_asset()`'s prior no-caller state, and the archived `feature_pipeline_executor.py` reader).
3. **This fix cannot yet be empirically confirmed against fresh live data** -- ingestion has been paused since 2026-07-27, four days before the 2026-07-31 fix landed, so zero new `feature_vectors` rows exist to check `vix_z != 0.0` against. The fix is confirmed correct by source read and by the pre-existing unit test suite (`test_feature_vector_pipeline_cross_asset.py`'s docstring, unrelated to this plan, already documents the same mechanism), not yet by a live-data spot-check.

**Consequence for plan 151-09**, stated plainly rather than left implicit: 151-09's Task 2 (as currently written in `151-09-PLAN.md`) assumes `vix_z`/`flight_quality`/`yield_slope_z` are STILL broken on the live path and proposes building an entirely new `build_cross_asset_series`-based live loader (`_load_cross_asset_series`, `_cross_asset_by_date`, a fresh once-per-UTC-day refresh mechanism) from scratch. That premise is false for the 3 legacy fields as of 2026-07-31. **151-09 needs re-scoping before it executes** -- most likely narrowed to extending the ALREADY-LIVE `CrossAssetState`/`_cross_asset_state_for_bar()` mechanism with this plan's 7 new fields, rather than replacing a mechanism that already works. This plan does not re-scope 151-09 (out of this plan's task boundaries) -- flagging it here, in `.planning/todos/pending/258-...md`, and will need to be read before 151-09 is next picked up.

**Part B -- residual dead-code todo filed:** `.planning/todos/pending/258-v3-cross-asset-kafka-route-dead-code.md` (P3, area `intelligence`), documenting the still-genuinely-dead `services/cross_asset_analyzer.py` -> `topic_cross_asset` -> `CacheManager.update_cross_asset()` route (unrelated fields, `es_nq_spread_z`/`corr_z`/`active_pair`, unit `inactive`), the same-named-but-unrelated hazard this creates against `FeatureCache.update_cross_asset()`, cites todo 158 (same bug class) and todo 159 (adjacent warm-up precedent) by number, and poses the open v2.x-revival question rather than answering it unilaterally. `.planning/todos/PRIORITIES.md` updated in the same commit.

## Decisions Made

See `key-decisions` in frontmatter for the full list. Most consequential: the Task 4 finding that this plan's (and plan 151-09's) scoping premise about the live-path cross-asset gap is now partially stale, resolved by unrelated work (todo 221/222) that landed 2026-07-31 -- between this plan's 2026-07-24 authoring and today's 2026-08-05 execution.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's stale field-count baseline (182/192/193) corrected to the live baseline (270/277)**
- **Found during:** Task 1, before writing any code (verified live baseline via direct Python check)
- **Issue:** The plan's `<interfaces>` section (written 2026-07-24) asserts "After plan 151-01, `len(dataclasses.fields(FeatureVector))` == 182... This plan takes them to 200 / 200 / 209" -- factually false for the live codebase, which already carries 270 fields after 151-01/02/03 landed.
- **Fix:** Scaled every arithmetic reference (docstring "Total: N" tally, migration header comments, `feature_registry` row-count math, all hardcoded test assertions, `FEATURE_VECTOR_INSERT_SQL_PSYCOPG` column count) to the live 270->277 baseline instead of the plan's stale 193->200.
- **Files modified:** `src/intelligence/schemas.py`, `production/migrations/289_cross_asset_spread_beta_atomics.sql`, all touched test files, `feature_vector_persistence.py`
- **Verification:** `len(dataclasses.fields(FeatureVector))` -> 277; live `feature_registry` count -> 277 (post-migration); full `tests/unit/` suite green.
- **Committed in:** `302a47cd`, `85d74202`

**2. [Rule 3 - Blocking] Migration number collision with intervening work landed since plan authoring**
- **Found during:** Task 3, before writing the migration file
- **Issue:** The plan's provisional migration number (262) was long taken -- `ls production/migrations/` showed the sequence had advanced through 288 (151-03's own migration in this same phase).
- **Fix:** Used 289 (verified next-free via both `ls` and a live `config_history` query for `changed_by='migration_289'`), updated every internal reference consistently.
- **Files modified:** `production/migrations/289_cross_asset_spread_beta_atomics.sql`, `services/feature_vector_pipeline.py`, `feature_vector_persistence.py`, test docstrings
- **Verification:** Migration applied cleanly; `config_history` shows exactly the expected 7 `migration_289` rows.
- **Committed in:** `85d74202`

**3. [Rule 3 - Blocking] Pre-commit hook's Plugin-naming convention required renaming CrossAssetValues to CrossAssetRecord**
- **Found during:** Task 1+2's commit attempt (first `git commit` was BLOCKED by the repo's `tools/pre-commit.hook`)
- **Issue:** The hook enforces a class-naming convention across all `src/intelligence/*.py` files: every class must end in one of ~40 allow-listed suffixes (Plugin, Agent, State, Record, Vector, etc.). The plan's literal name `CrossAssetValues` doesn't match any of them ("Values" is not allow-listed).
- **Fix:** Renamed to `CrossAssetRecord` (matching the existing `FeatureVectorRecord` precedent in `schemas.py`) via a project-wide sed across all 4 referencing files, then re-verified the full test suite.
- **Files modified:** `src/intelligence/features/cross_asset_series.py`, `src/intelligence/feature_factory.py`, `services/backfill_feature_factory.py`, `tests/unit/services/test_backfill_feature_factory.py`
- **Verification:** `grep -rl "CrossAssetValues"` returns nothing; `grep -rl "class CrossAssetRecord"` returns exactly 1 file; full `tests/unit/` suite green; pre-commit hook passes.
- **Committed in:** `302a47cd`

**4. [Rule 2 - Missing Critical] 2 additional private deques needed for sb_corr's rolling correlation, beyond the plan's literal 5-deque list**
- **Found during:** Task 1, implementing the `sb_corr_fast`/`sb_corr_slow` compute block
- **Issue:** The plan's action text lists exactly 5 new deques (`_tip_tlt_ratio_history`, `_hyg_lqd_ratio_history`, `_sb_corr_history`, `_equity_beta_history`, `_rate_beta_history`). None of these can hold the raw SPY/TLT log-return HISTORY a rolling Pearson correlation structurally requires -- `_sb_corr_history` only accumulates the already-computed `sb_corr_fast` scalar per the plan's own z-scoring instruction.
- **Fix:** Added `_sb_spy_log_ret_history`/`_sb_tlt_log_ret_history` (same `deque(maxlen=500)` convention as every sibling), used only inside the `sb_corr` compute block.
- **Files modified:** `src/intelligence/feature_cache.py`
- **Verification:** `test_sb_corr_fast_bounded_and_extremes` confirms exact +1.0/-1.0 correlation on synthetic perfectly-co-moving/opposed SPY/TLT series (via a pure multiplicative/inverse price relationship, which yields exact log-return correlation -- an earlier additive-affine version of this test failed at ~0.9999, corrected during implementation, see Issues Encountered).
- **Committed in:** `302a47cd`

**5. [Rule 1 - Bug] FEATURE_VECTOR_INSERT_SQL_PSYCOPG2 (plan's literal name) doesn't exist -- real constant is FEATURE_VECTOR_INSERT_SQL_PSYCOPG**
- **Found during:** Task 1, reading `feature_vector_persistence.py` before editing
- **Issue:** Plan's acceptance criteria reference `FEATURE_VECTOR_INSERT_SQL_PSYCOPG2` (with a "2" suffix); the actual exported name has no "2".
- **Fix:** Used the correct name throughout (SUMMARY and all verification commands).
- **Files modified:** N/A (verification-only correction, no source change needed)
- **Verification:** `python -c "from src.intelligence.features.feature_vector_persistence import FEATURE_VECTOR_INSERT_SQL_PSYCOPG as s; print(s.count('%s'))"` prints 286.
- **Committed in:** N/A (no code change, documentation-only correction)

---

**Total deviations:** 5 auto-fixed (2 bug fixes, 2 blocking-issue fixes, 1 missing-critical-functionality addition)
**Impact on plan:** All five were necessary for correctness, for the plan's own stated success criteria (full unit suite green, migration applies cleanly, no numbering collision, `feature_registry` row count matches the dataclass field count, pre-commit hooks pass), or for the sb_corr feature to be computable at all. No scope creep beyond what was required to keep the plan's own deliverable internally consistent against a codebase that grew 88 fields between the plan's authoring (2026-07-24) and this plan's own execution (2026-08-05), plus the pre-commit hook's naming requirement discovered mid-execution.

## Issues Encountered

- **Test math bug, self-caught and fixed within Task 1's own commit:** the first version of `test_sb_corr_fast_bounded_and_extremes` used an additive-affine SPY->TLT price transform (`close = 50.0 + 0.5*(spy_close - anchor)`) expecting exact +1.0/-1.0 correlation. Log returns of an affine (non-multiplicative) transform are NOT exactly proportional to the underlying series' log returns, so the test failed at 0.9999 / -0.99989 rather than exactly ±1.0. Corrected to a pure multiplicative (`close = k * spy_close`) / inverse (`close = C / spy_close`) relationship, which DOES yield exact log-return correlation (`log(k*a/k*b) == log(a/b)`), confirmed exact to `abs=1e-6`.
- **Second test bug, also self-caught:** the same test initially called `cache.update_cross_asset(...)` only ONCE over the full 60-bar array, expecting a populated rolling-correlation window. `update_cross_asset()` appends only the LAST bar's return per call (matching the live incremental-append semantics of `vix_z`/`yield_slope_z`), so a single call produces a correlation over 1 data point (`_safe_corr` correctly returns 0.0 for `len < 2`). Corrected to call `update_cross_asset()` incrementally, once per bar, matching the pattern already established in `TestBuildCrossAssetSeries`'s own reference-implementation test.

Both were caught and fixed during Task 1's own execution, before that task's commit -- not deferred, not left as a known-broken test.

## User Setup Required

None - no external service configuration required. The migration was applied directly to the live DB as part of Task 3 (`PGPASSWORD=postgres psql ... -f production/migrations/289_cross_asset_spread_beta_atomics.sql`).

## Known Stubs

None. All 7 new fields have real compute logic wired into the batch path from day one (matching Plans 01/03's precedent, not the SMC/Swing-block None-placeholder pattern). The one genuine gap -- these 7 fields are NOT yet computed on the live path -- is not a stub in the silent-wrong-answer sense: `equity_beta_z`/`rate_beta_z` stay at their explicit cache defaults (`0.0`, matching the plan's own design), and the 5 symbol-independent fields will inherit real values automatically once plan 151-09 (re-scoped per Task 4's finding) extends the already-live `CrossAssetState` broadcast mechanism.

## Threat Flags

None beyond what the plan's own `<threat_model>` already covers (T-151-06 through T-151-09, all mitigated as designed -- `market_data_ohlcv_tradeable` used for all 3 new symbol fetches, confirmed no new raw-table reads; `equity_beta_z`/`rate_beta_z` typed `float | None` with the SPY/TLT null special-case asserted by unit test; Task 4's contamination measurement satisfies T-151-09's mitigation plan).

## Next Phase Readiness

- Plans 151-05/151-06 (interaction layer) can proceed against the now-277-field `FeatureVector` baseline.
- Plan 151-09 (wave 5, live-path cross-asset wiring) has a **changed precondition**: its Task 2 needs re-scoping before execution, per Task 4's finding above. This is the single most important handoff from this plan -- do not execute 151-09 as currently written without first re-reading `151-04-SUMMARY.md`'s Task 4 section and `.planning/todos/pending/258-...md`.
- `_PHASE151_CROSS_ASSET_FIELD_NAMES` derived-slice pattern and migration 289's `concept_registry`/`concept_gate` parity block are direct templates for any subsequent Phase 151 plan's own migration (same Phase 170 parity requirement applies to every wave).
- No blockers to 151-05/06. Full `tests/unit/` suite green; live DB migration applied and verified (`feature_registry`=277 rows, `concept_registry`/`concept_gate` parity clean 7/7, row-count alignment gate holds).
- Reminder for the next migration in this phase: re-verify the next-free migration number against BOTH `ls production/migrations/` AND `config_history` before applying -- confirmed necessary again this plan (262->289), same discipline as every prior Phase 151 plan.

## Self-Check: PASSED

- FOUND: `production/migrations/289_cross_asset_spread_beta_atomics.sql`
- FOUND: `src/intelligence/features/cross_asset_series.py`
- FOUND: `.planning/todos/pending/258-v3-cross-asset-kafka-route-dead-code.md`
- FOUND: commit `302a47cd` (Tasks 1+2)
- FOUND: commit `85d74202` (Task 3)
- FOUND: commit `6a0ab475` (Task 4)
- Verified live: `SELECT count(*) FROM feature_registry` = 277 (matches `FeatureVector` field count)
- Verified live: `concept_registry`/`concept_gate` parity = 7/7 for this plan's rows
- Verified live: `config_schema` has exactly 7 rows matching `feature.tip_tlt.%`/`feature.hyg_lqd.%`/`feature.sb_corr.%`/`feature.factor_beta.%`, 0 rows matching `macro.%` seeded by this migration

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
