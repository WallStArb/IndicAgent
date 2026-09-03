---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 03
subsystem: feature-factory
tags: [feature-factory, feature-vectors, apr, concept-registry, timescaledb, feature-engineering]

# Dependency graph
requires:
  - phase: 151-01
    provides: live FeatureVector baseline (259 fields after wave 1), the calendar/velocity contiguous-block + derived-slice persistence pattern this plan reuses
  - phase: 170-feature-domain-concept-registry-migration
    provides: concept_registry/concept_gate schema + ic_engine.py's PARITY PRECONDITION gate
provides:
  - 11 new FeatureVector fields (270 total): 10 bars_since_* bounded rolling-window recency primitives + abs_ret_autocorr_1 (volatility-clustering)
  - migration 288 (feature_vectors columns, feature_registry rows, APR keys, concept_registry/concept_gate parity rows)
  - 2 new APR keys: feature.bars_since_extreme_move.sigma_threshold, feature.bars_since_vol_spike.threshold
  - 2 new shared O(n) helpers: _bars_since_rolling_extreme_series_full (monotonic-deque rolling-extreme recency), _bars_since_event_series_full (bars-since-most-recent-True with saturation)
affects: [151-04, 151-05, 151-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Monotonic-deque O(n) rolling-extreme-recency helper, generic over max/min via a mode string, shared by all 6 bars_since_high/low_fast/slow/52w_high/low fields"
    - "Bars-since-most-recent-event helper with an explicit saturating convention (window-1, never 0.0/NaN) for 'no qualifying event in the trailing window' -- distinct from the boundedness convention of the rolling-extreme helper above"
    - "_ret_autocorr_series_full generalized with an optional use_abs parameter (byte-identical for existing use_abs=False callers) instead of writing a near-duplicate function body for the |return| variant"

key-files:
  created:
    - production/migrations/288_recency_statistical_atomics.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_batch.py
    - 17 test/service FeatureFactoryConfig(...) construction sites (2 new required kwargs)
    - 4 hand-typed FeatureVector(...) sentinel constructors (11 new required kwargs)

key-decisions:
  - "Live codebase baseline was 259 fields at execution time, not the plan's stale 182/192/193 assumption (written 2026-07-24) -- 151-01 and 151-02 landed 77 intervening fields since. Scaled all arithmetic (docstring tallies, migration numbering, test assertions, acceptance criteria) to the live baseline throughout, matching the identical correction pattern already documented in 151-01's own SUMMARY."
  - "Migration renumbered 261 (plan's provisional target) -> 288 (actual next-free number, re-verified against both `ls production/migrations/` and a live config_history query for any prior migration_288 row before applying, per 151-01/151-02's own documented numbering-collision precedent under concurrent worktree execution)."
  - "_cold_start_vector has no config parameter (called only when len(bars) < 2), so the true per-window saturating value (window-1) cannot be read from live APR there. Used each field's seeded APR default window (dist_window_fast=20, dist_window_slow=50, high_52w_window=252) as a literal -- the same bare-literal convention every other field in that function already follows for the identical reason, and the same class of deviation 151-01 already documented for its own cold-start fields."

requirements-completed: []

# Metrics
duration: 28min
completed: 2026-08-05
---

# Phase 151 Plan 03: Recency/Statistical Atomics Summary

**11 new tier-0 atomic FeatureVector fields (10 bounded rolling-window bars_since_* recency primitives + abs_ret_autocorr_1 volatility-clustering) live in both compute paths, persisted end-to-end, with matching feature_registry and concept_registry/concept_gate rows (Phase 170 parity) via migration 288.**

## Performance

- **Duration:** ~28 min
- **Started:** 2026-08-05T07:54:25-04:00 (approx, base commit)
- **Completed:** 2026-08-05T08:22:30-04:00
- **Tasks:** 3
- **Files modified:** 24 (1 created: migration 288)

## Accomplishments

- `FeatureVector` grew from 259 to 270 fields: `bars_since_high_fast/slow`, `bars_since_low_fast/slow`, `bars_since_52w_high/low`, `bars_since_extreme_move_fast/slow`, `bars_since_vol_spike_fast/slow` (Task 1), immediately followed by `abs_ret_autocorr_1` (Task 2) -- declared as one contiguous 11-field run in `schemas.py` specifically so `feature_vector_persistence.py`'s new derived slice covers the whole block with a single index range.
- 2 new shared O(n) helpers (`_bars_since_rolling_extreme_series_full` via a monotonic deque, `_bars_since_event_series_full` for the event-indicator families) instead of 10 near-duplicate per-feature bodies; `_ret_autocorr_series_full` generalized with an optional `use_abs` parameter rather than a copy-pasted magnitude-autocorrelation function.
- All 11 fields wired into `FEATURE_VECTOR_DOMAIN`, `_PrecomputedSeries`/`_precompute_series`, `FeatureFactory.compute()`, `FeatureFactory.compute_batch()`, `_build_feature_vector`, and `_cold_start_vector` -- both live and batch paths produce identical values (parity-tested via both a direct synthetic-data smoke check before committing and the extended unit-test harness).
- 2 new APR-backed `FeatureFactoryConfig` fields (`extreme_move_sigma_threshold`, `vol_spike_threshold`), wired into both real production entrypoints (`feature_vector_pipeline.py`, `backfill_feature_factory.py`) and every one of the 17 project-wide `FeatureFactoryConfig(...)` test/service construction sites.
- `feature_vector_persistence.py`'s INSERT contract closed in the same Task 2 commit: `_PHASE151_RECENCY_FIELD_NAMES` derived slice, 279 total columns/placeholders (was 268).
- Migration 288 applied to the live DB: 11 `feature_vectors` columns, 11 `feature_registry` rows (`tier='0_atomic'`, `added_phase='151'`), 2 APR key triplets, and 11 matching `concept_registry`/`concept_gate` rows satisfying Phase 170's `ic_engine.py` PARITY PRECONDITION gate.
- `feature_registry_service.py`'s row-count alignment gate verified live (`n_features=270`, matches `FeatureVector` field count); `feature_registry`/`concept_registry`/`concept_gate` parity all confirmed 11/11 via direct SQL.
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after both task commits.

## Task Commits

Each task was committed atomically:

1. **Tasks 1+2 (combined -- see Deviations): 10 bars_since_* recency primitives + abs_ret_autocorr_1 and the persistence contract** - `40509ace` (feat)
2. **Task 3: Migration 288 and unit tests** - `8198f194` (feat)

_No separate plan-metadata commit -- this is a parallel worktree execution; SUMMARY.md is committed by the orchestrator's post-wave merge step per `parallel_execution` instructions._

## Files Created/Modified

- `production/migrations/288_recency_statistical_atomics.sql` - 11 columns, 11 feature_registry rows, 2 APR triplets, 11 concept_registry/concept_gate parity rows
- `src/intelligence/schemas.py` - `FeatureVector` +11 fields, docstring tally 259→270
- `src/intelligence/feature_factory.py` - 2 new shared helpers, `_ret_autocorr_series_full` `use_abs` generalization, `FeatureFactoryConfig` +2 fields, wired into `compute()`/`compute_batch()`/`_cold_start_vector`/`_build_feature_vector`/`_precompute_series`
- `src/intelligence/features/feature_vector_persistence.py` - `_PHASE151_RECENCY_FIELD_NAMES` slice, INSERT contract closed (268→279 columns)
- `services/feature_vector_pipeline.py` - 2 new APR keys wired into `_THRESHOLD_KEYS` + `FeatureFactoryConfig` construction
- `services/backfill_feature_factory.py` - same 2 APR keys wired into `_build_feature_factory_config`
- `tests/unit/intelligence/test_feature_factory_batch.py` - new test classes: `_bars_since_rolling_extreme_series_full` boundedness/saturation/recency, `_bars_since_event_series_full` boundedness/saturation/recency, `abs_ret_autocorr_1` sign behavior + byte-identical-refactor regression, extended batch/live parity for all 11 new fields
- 17 test/service `FeatureFactoryConfig(...)` builder files - added `extreme_move_sigma_threshold=2.0, vol_spike_threshold=2.0`
- 4 hand-typed `FeatureVector(...)` sentinel constructors (`test_feature_vector_writer_column_mapping.py`, `test_feature_vector_writer.py`, `test_backfill_feature_factory.py`, `test_feature_factory_batch_parity.py`) - added the 11 new required kwargs
- `tests/unit/test_feature_factory.py`, `tests/unit/test_canary_predictors.py`, `tests/unit/intelligence/test_feature_factory_p7.py` - fixed hardcoded field-count assertions (259→270)

## Decisions Made

- **Live baseline was 259 fields, not the plan's stale 182/192/193:** the plan's `<interfaces>` section states "After plan 151-01, `len(dataclasses.fields(FeatureVector))` == 182" and "This plan takes both to 193" -- both factually wrong for the live codebase at execution time (151-01's own SUMMARY confirms 259 after wave 1, itself already corrected from the plan's stale 172 assumption). Verified the live count directly (`python -c "..."` → 259) before writing any code and scaled every downstream number (migration comments, docstring tallies, test assertions, acceptance-criteria arithmetic) to 259→270 throughout.
- **Migration renumbered 261→288:** re-verified the next-free number per the plan's own instruction (`ls production/migrations/ | sort -t_ -k1 -n | tail -5`) and found the sequence had advanced through 287 (151-01's own migration). Also checked `config_history` for any `changed_by='migration_288'` row from a concurrent worktree session (none found) before applying -- the exact collision-detection discipline 151-02's SUMMARY explicitly recommended for this phase's subsequent migrations.
- **`_cold_start_vector` cold-start defaults use literal seeded-APR-default window sizes, not a true saturating read:** `_cold_start_vector(cache, tf)` has no `config` parameter (only called when `len(bars) < 2`), so the real per-window saturating value (`window-1`) cannot be read from live APR there. Used each field's seeded default window as a bare literal (`dist_window_fast=20` → `19.0`, `dist_window_slow=50` → `49.0`, `high_52w_window=252` → `251.0`) -- the same bare-literal convention every other cold-start field in that function already follows for the identical structural reason, and the same deviation class 151-01's SUMMARY already documented for its own cold-start fields.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's stale field-count baseline (182/192/193) corrected to the live baseline (259/270)**
- **Found during:** Task 1, before writing any code (verified live baseline via direct Python check)
- **Issue:** The plan's `<interfaces>` section (written 2026-07-24) asserts "currently 182 fields... this plan takes both to 193" -- factually false for the live codebase, which already carries 259 fields after 151-01/151-02 landed. Following the plan's literal numbers would have produced incorrect docstring tallies, wrong migration acceptance-criteria row counts, and field-count assertions that immediately fail against the real dataclass.
- **Fix:** Scaled every arithmetic reference (docstring "Total: N" tally, migration header comments, `feature_registry` row-count acceptance criteria, all hardcoded test assertions) to the live 259→270 baseline instead of the plan's stale 182→193.
- **Files modified:** `src/intelligence/schemas.py`, `production/migrations/288_recency_statistical_atomics.sql`, all touched test files
- **Verification:** `python -c "...len(dataclasses.fields(FeatureVector))"` → 270; live `feature_registry` count → 270 (post-migration); full `tests/unit/` suite green.
- **Committed in:** `40509ace`, `8198f194`

**2. [Rule 3 - Blocking] Migration number collision with intervening work landed since plan authoring**
- **Found during:** Task 3, before writing the migration file
- **Issue:** The plan's provisional migration number (261, itself an estimate from the plan's 2026-07-24 authoring date) was long taken -- `ls production/migrations/` showed the sequence had advanced through 287 (151-01's own migration in this same phase).
- **Fix:** Used 288 (verified next-free via both `ls` and a live `config_history` query for any `changed_by='migration_288'` row from a concurrent worktree session, per 151-01/151-02's own documented collision-detection discipline), and updated every internal reference (filename, `changed_by` strings, `feature_vector_pipeline.py`'s threshold-key comment, `feature_vector_persistence.py`'s docstring/column-index comments, all touched test docstrings) consistently.
- **Files modified:** `production/migrations/288_recency_statistical_atomics.sql`, `services/feature_vector_pipeline.py`, `src/intelligence/features/feature_vector_persistence.py`, test docstrings
- **Verification:** Migration applied cleanly to the live DB; `config_history` shows exactly the expected 2 `migration_288` rows.
- **Committed in:** `8198f194`

**3. [Rule 3 - Blocking] 21 test/service construction sites broken by 2 new non-defaulted config fields and 11 new non-defaulted dataclass fields**
- **Found during:** Task 1/2 (broad sanity sweep, same discipline 151-01 documented)
- **Issue:** `extreme_move_sigma_threshold`/`vol_spike_threshold` are non-defaulted `FeatureFactoryConfig` fields (matching `momentum_velocity_window`/`vwap_velocity_window`'s own 151-01 precedent) -- all 17 project-wide `FeatureFactoryConfig(...)` construction sites needed the 2 new kwargs or would `TypeError`. 4 files hand-construct `FeatureVector(...)`/call `_build_feature_vector(...)` directly with a fully hardcoded kwarg list and needed the 11 new required kwargs.
- **Fix:** Added `extreme_move_sigma_threshold=2.0, vol_spike_threshold=2.0` to all 17 config builders; added the 11 new fields with sentinel/neutral values to the 4 hand-typed constructors.
- **Files modified:** 17 `FeatureFactoryConfig` construction sites, `test_feature_vector_writer_column_mapping.py`, `test_feature_vector_writer.py`, `test_backfill_feature_factory.py`, `test_feature_factory_batch_parity.py`
- **Verification:** `pytest tests/unit/ -q` green (0 failures).
- **Committed in:** `40509ace`

---

**Total deviations:** 3 auto-fixed (1 bug fix, 2 blocking-issue fixes)
**Impact on plan:** All three were necessary for correctness and for the plan's own stated success criteria (full unit suite green, migration applies cleanly, no numbering collision, `feature_registry` row count matches the dataclass field count). No scope creep beyond what was required to keep the plan's own deliverable internally consistent against a codebase that grew from 172→259 fields between the plan's authoring (2026-07-24) and 151-01's execution, then 259→270 within this plan itself.

## Issues Encountered

None beyond the deviations documented above -- all were resolved within the same task they were discovered in.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 151-04 through 151-06 (interaction layer, per ROADMAP.md's phase entry) can proceed against the now-270-field `FeatureVector` baseline.
- The `_PHASE151_RECENCY_FIELD_NAMES` derived-slice pattern and migration-288's `concept_registry`/`concept_gate` parity block are direct templates for any subsequent Phase 151 plan's own migration (same Phase 170 parity requirement applies to every wave).
- No blockers. Full `tests/unit/` suite green; live DB migration applied and verified (`feature_registry`=270 rows, `concept_registry`/`concept_gate` parity clean 11/11, `feature_registry_service.py`'s alignment gate holds).
- Reminder for the next migration in this phase: re-verify the next-free migration number against BOTH `ls production/migrations/` AND `config_history` before applying -- this plan's own migration-numbering correction (deviation 2) is exactly the failure mode a disk-only check misses under concurrent worktree execution, same as 151-01's own documented incident.

## Self-Check: PASSED

- FOUND: `production/migrations/288_recency_statistical_atomics.sql`
- FOUND: `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-03-SUMMARY.md`
- FOUND: commit `40509ace` (Tasks 1+2)
- FOUND: commit `8198f194` (Task 3)
- Verified live: `SELECT count(*) FROM feature_registry` = 270 (matches `FeatureVector` field count)
- Verified live: `concept_registry`/`concept_gate` parity = 11/11 for this plan's rows

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
