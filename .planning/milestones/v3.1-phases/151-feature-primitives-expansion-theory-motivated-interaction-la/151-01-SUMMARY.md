---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
plan: 01
subsystem: feature-factory
tags: [feature-factory, feature-vectors, apr, concept-registry, timescaledb, feature-engineering]

# Dependency graph
requires:
  - phase: 170-feature-domain-concept-registry-migration
    provides: concept_registry/concept_gate schema + ic_engine.py's PARITY PRECONDITION gate
provides:
  - 10 new FeatureVector fields (259 total): 6 calendar cycle/TDOM/minute-of-hour coordinates + 4 velocity primitives
  - migration 287 (feature_vectors columns, feature_registry rows, APR keys, concept_registry/concept_gate parity rows)
  - 2 new APR keys: feature.momentum_velocity.window, feature.vwap_velocity.window
affects: [151-03, 151-04, 151-05, 151-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Generic velocity-of-a-z-score-series helper (_vol_velocity_z_series_full, param renamed atr_z -> series) reused across 4 unrelated feature families instead of 4 near-duplicate bodies"
    - "Contiguous dataclass field-block declaration purpose-built for a single derived index-range persistence slice spanning two logically-distinct sub-groups (calendar + velocity)"

key-files:
  created:
    - production/migrations/287_calendar_velocity_atomics.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/intelligence/test_feature_factory_batch.py

key-decisions:
  - "_cold_start_vector has no bar_ts parameter (contradicts the plan's literal instruction to compute real values there); used the codebase's own established neutral angle=0 convention (sin=0.0, cos=1.0) instead, matching dow_sin/cos and hour_of_day_sin/cos precedent in the same function"
  - "Migration renumbered 286 -> 287 after discovering a live collision with a concurrent sibling worktree's own migration (286_cluster_regime_conditioned.sql, Phase 151 Plan 04); corrected the file, all code/test references, and the 2 already-applied config_history rows via UPDATE"
  - "Codebase field-count baseline was 249 at execution time (not 172 as the plan's <interfaces> section assumed, written 2026-07-24) -- 77 fields' worth of intervening phases (163/164/165/170) landed since; scaled all arithmetic to the live baseline throughout"

requirements-completed: []

# Metrics
duration: 35min
completed: 2026-08-05
---

# Phase 151 Plan 01: Calendar Coordinate + Velocity Atomics Summary

**10 new tier-0 atomic FeatureVector fields (6 calendar cycle/TDOM/minute coordinates + 4 first-difference velocity primitives) live in both compute paths, persisted end-to-end, with matching feature_registry and concept_registry/concept_gate rows (Phase 170 parity) via migration 287.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-08-05T05:50:00-04:00 (approx)
- **Completed:** 2026-08-05T06:25:11-04:00
- **Tasks:** 3
- **Files modified:** 24 (1 created: migration 287)

## Accomplishments

- `FeatureVector` grew from 249 to 259 fields: `quarter_cycle_sin/cos`, `tdom_sin/cos`, `minute_of_hour_sin/cos` (Task 1), immediately followed by `momentum_z_velocity_fast/mid/slow`, `vwap_dev_sigma_velocity` (Task 2) — declared as one contiguous 10-field run in `schemas.py` specifically so `feature_vector_persistence.py`'s new derived slice covers both sub-blocks with a single index range.
- 3 new pure calendar helpers (`_quarter_cycle_encoding`, `_tdom_encoding`, `_minute_of_hour_encoding`) and a generalized `_vol_velocity_z_series_full` (param renamed `atr_z` → `series`) reused byte-identically for 4 different feature families instead of 4 near-duplicate function bodies.
- All 10 fields wired into `FEATURE_VECTOR_DOMAIN`, `_build_feature_vector`, `FeatureFactory.compute()`, `FeatureFactory.compute_batch()`, and `_cold_start_vector` — both live and batch paths produce identical values (parity-tested).
- `feature_vector_persistence.py`'s INSERT contract closed in one Task 2 commit: `_PHASE151_CALENDAR_VELOCITY_FIELD_NAMES` derived slice, 268 total columns/placeholders (was 258).
- Migration 287 applied to the live DB: 10 `feature_vectors` columns, 10 `feature_registry` rows (`tier='0_atomic'`, `added_phase='151'`), 2 APR key triplets, and 10 matching `concept_registry`/`concept_gate` rows satisfying Phase 170's `ic_engine.py` PARITY PRECONDITION gate.
- `feature_registry_service.py`'s row-count alignment gate verified live (`load_sync()` succeeds, `n_features=259`); `ic_engine.py`'s registry/concept status-parity check verified clean (zero mismatches across all 259 features).
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after all three task commits.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 6 calendar coordinate primitives** - `b54bf7cc` (feat)
2. **Task 2: Add 4 velocity primitives and close the persistence contract** - `cffe30e0` (feat)
3. **Task 3: Migration 287 and unit tests** - `9e8605a0` (feat)

_No separate plan-metadata commit — this is a parallel worktree execution; SUMMARY.md is committed by the orchestrator's post-wave merge step per `parallel_execution` instructions._

## Files Created/Modified

- `production/migrations/287_calendar_velocity_atomics.sql` - 10 columns, 10 feature_registry rows, 2 APR triplets, 10 concept_registry/concept_gate parity rows
- `src/intelligence/schemas.py` - `FeatureVector` +10 fields, docstring tally 249→259
- `src/intelligence/feature_factory.py` - 3 new calendar helpers, generalized velocity helper, `FeatureFactoryConfig` +2 fields, wired into `compute()`/`compute_batch()`/`_cold_start_vector`/`_build_feature_vector`
- `src/intelligence/features/feature_vector_persistence.py` - `_PHASE151_CALENDAR_VELOCITY_FIELD_NAMES` slice, INSERT contract closed (258→268 columns)
- `services/feature_vector_pipeline.py` - 2 new APR keys wired into `_THRESHOLD_KEYS` + `FeatureFactoryConfig` construction
- `services/backfill_feature_factory.py` - same 2 APR keys wired into `_build_feature_factory_config`
- `tests/unit/intelligence/test_feature_factory_batch.py` - new test classes: minute-of-hour, TDOM, quarter-cycle equivalence, velocity family, batch/live parity for all 10 fields
- 15 test `FeatureFactoryConfig(...)` builder files - added `momentum_velocity_window=20, vwap_velocity_window=20`
- 3 hand-typed `FeatureVector(...)` sentinel constructors (`test_feature_vector_writer_column_mapping.py`, `test_feature_vector_writer.py`, `test_backfill_feature_factory.py`) - added the 10 new required kwargs
- `tests/unit/test_feature_factory.py`, `tests/unit/test_canary_predictors.py`, `tests/unit/intelligence/test_feature_factory_p7.py` - fixed hardcoded field-count assertions (249→259)

## Decisions Made

- **`_cold_start_vector` cold-start defaults for the 6 calendar fields:** the plan assumed `bar_ts` is available there ("compute the real value there rather than defaulting to 0.0"), but the live function signature is `_cold_start_vector(cache, tf)` — no `bar_ts` at all, and this is not new drift, every other calendar field in that same function (`dow_sin=0.0, dow_cos=1.0`, `hour_of_day_sin=0.0, hour_of_day_cos=1.0`, etc.) already uses a static neutral angle=0 default. Followed that established precedent instead of the plan's factually-incorrect assumption.
- **Migration renumbering 286→287:** the plan's own text anticipated a numbering collision ("If 259 is taken by a concurrent session, use the actual next-free number") but assumed the collision would be visible via `ls production/migrations/`. It wasn't — the collision was with a concurrent sibling worktree (`151-02`/`151-04`, different git branch, not yet merged) whose migration file is invisible to `ls` from this worktree. Detected via `config_history.changed_by='migration_286'` carrying a timestamp ~29 minutes before this migration's own first apply. Corrected the file, every reference, and used `UPDATE` (not a second `INSERT`) to fix the 2 already-applied `config_history` rows' `changed_by` value.
- **Codebase field-count baseline (249, not 172):** the plan's `<interfaces>` section states "currently 172 fields" as "verified 2026-07-24, do not re-derive" — actual live baseline at execution time was 249 (Phases 163/164/165/170 landed 77 more fields in the interim). All arithmetic (docstring tallies, test assertions, acceptance criteria) was scaled to the live baseline throughout rather than the stale plan snapshot.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_cold_start_vector` cold-start defaults follow established neutral-angle convention, not the plan's bar_ts-based instruction**
- **Found during:** Task 1
- **Issue:** Plan text says "Cold start still has a valid `bar_ts`, so compute the real value there rather than defaulting to 0.0" — false for the live codebase; `_cold_start_vector(cache, tf)` has no `bar_ts` parameter and is only called when `len(bars) < 2` (0 or 1 bars).
- **Fix:** Used the same `sin=0.0, cos=1.0` neutral convention already established for every other calendar field in that function.
- **Files modified:** `src/intelligence/feature_factory.py`
- **Verification:** `_cold_start_vector` constructs without `TypeError`; explicit test coverage confirms `quarter_cycle_sin == 0.0`.
- **Committed in:** `b54bf7cc` (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed 7 hardcoded FeatureVector/FEATURE_VECTOR_DOMAIN field-count assertions stale since the codebase grew from 172→249 fields**
- **Found during:** Task 1 (broad sanity sweep beyond the plan's own narrow `<verify>` command)
- **Issue:** `tests/unit/test_feature_factory.py`, `tests/unit/test_canary_predictors.py` (x2 assertions), `tests/unit/intelligence/test_feature_factory_p7.py` all hardcoded `== 249`/`== 249` for field/domain counts, which would fail the moment 6 new fields landed regardless of correctness elsewhere.
- **Fix:** Updated all hardcoded counts to the correct new totals (255 after Task 1, 259 after Task 2).
- **Files modified:** `tests/unit/test_feature_factory.py`, `tests/unit/test_canary_predictors.py`, `tests/unit/intelligence/test_feature_factory_p7.py`
- **Verification:** `pytest tests/unit/ -q` green.
- **Committed in:** `b54bf7cc`, `cffe30e0`

**3. [Rule 3 - Blocking] Fixed 15 test `FeatureFactoryConfig(...)` builders + 3 hand-typed `FeatureVector(...)` sentinel constructors broken by the 2 new non-defaulted config fields and 10 new non-defaulted dataclass fields**
- **Found during:** Task 2 (broad sanity sweep)
- **Issue:** `momentum_velocity_window`/`vwap_velocity_window` are non-defaulted `FeatureFactoryConfig` fields (matching `vol_velocity_window`'s own precedent) — every one of the 17 project-wide `FeatureFactoryConfig(...)` construction sites needed the 2 new kwargs or would `TypeError`. Similarly, 3 files hand-construct `FeatureVector(...)` directly with a fully hardcoded kwarg list.
- **Fix:** Added `momentum_velocity_window=20, vwap_velocity_window=20` to all 15 test config builders (2 production entrypoints already covered by the plan's own Task 2 instructions); added the 10 new fields with sentinel/neutral values to the 3 hand-typed `FeatureVector(...)` constructors, including a stale "gap_filled is the true last element" invariant in `test_feature_vector_writer_column_mapping.py` that is no longer true (superseded by `vwap_dev_sigma_velocity`, fixed with a new test + a corrected old one).
- **Files modified:** 15 `FeatureFactoryConfig` test builders, `test_feature_vector_writer_column_mapping.py`, `test_feature_vector_writer.py`, `test_backfill_feature_factory.py`
- **Verification:** `pytest tests/unit/ -q` green (0 failures).
- **Committed in:** `b54bf7cc` (calendar-field portion), `cffe30e0` (velocity-field portion + APR-config portion)

**4. [Rule 3 - Blocking] Migration number collision with a concurrent sibling worktree**
- **Found during:** Task 3, after applying `286_calendar_velocity_atomics.sql`
- **Issue:** `production/migrations/286_cluster_regime_conditioned.sql` already existed on a concurrent, not-yet-merged sibling worktree branch (`worktree-agent-ae9b0514832842af8`, Phase 151 Plan 04/Wave 4) — invisible to this worktree's own `ls production/migrations/` check, but real in the shared live DB (`config_history.changed_by='migration_286'` for `alpha.ensemble.cluster_regime_conditioned`, timestamped ~29 min before this migration's own apply).
- **Fix:** Renamed the file to `287_calendar_velocity_atomics.sql`, updated every internal/external reference (migration file header, `feature_vector_persistence.py` docstrings/comments, `feature_vector_pipeline.py` comment, 3 test-file comments), and corrected the 2 already-applied `config_history` rows via `UPDATE ... WHERE changed_by='migration_286' AND config_key IN (...)` (scoped precisely to avoid touching the sibling's genuine `migration_286` row).
- **Files modified:** `production/migrations/287_calendar_velocity_atomics.sql`, `src/intelligence/features/feature_vector_persistence.py`, `services/feature_vector_pipeline.py`, 3 test files, live `config_history` table (2 rows)
- **Verification:** `config_history` now shows exactly 1 `migration_286` row (the sibling's, untouched) and 2 `migration_287` rows (this plan's own).
- **Committed in:** `9e8605a0` (Task 3 commit)

---

**Total deviations:** 4 auto-fixed (1 bug fix, 3 blocking-issue fixes)
**Impact on plan:** All four were necessary for correctness and for the plan's own stated success criteria (full unit suite green, migration applies cleanly, no numbering collision). No scope creep beyond what was required to keep the plan's own deliverable internally consistent against a codebase that grew substantially (172→249 fields, 258→285 migrations) between the plan's authoring (2026-07-24) and its execution (2026-08-05).

## Issues Encountered

None beyond the deviations documented above — all were resolved within the same task they were discovered in, with the migration-number collision (deviation 4) being the most consequential (required a live-DB correction, not just a code fix).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plans 151-03 through 151-06 (interaction layer, per ROADMAP.md's phase entry) can proceed against the now-259-field `FeatureVector` baseline.
- The `_PHASE151_CALENDAR_VELOCITY_FIELD_NAMES` derived-slice pattern and the migration-287 concept_registry/concept_gate parity block are direct templates for any subsequent Phase 151 plan's own migration (same Phase 170 parity requirement applies to every wave).
- No blockers. Full `tests/unit/` suite green; live DB migration applied and verified (`feature_registry`=259 rows, `concept_registry`/`concept_gate` parity clean, `feature_registry_service.py`'s alignment gate holds).
- Reminder for the next migration in this phase: re-verify the next-free migration number against BOTH `ls production/migrations/` AND `config_history` (or sibling worktree branches directly, if known) before applying — this plan's own migration-numbering collision (deviation 4) is exactly the failure mode a disk-only check misses under concurrent worktree execution.

## Self-Check: PASSED

- FOUND: `production/migrations/287_calendar_velocity_atomics.sql`
- FOUND: `.planning/milestones/v3.1-phases/151-feature-primitives-expansion-theory-motivated-interaction-la/151-01-SUMMARY.md`
- FOUND: commit `b54bf7cc` (Task 1)
- FOUND: commit `cffe30e0` (Task 2)
- FOUND: commit `9e8605a0` (Task 3)
- FOUND: commit `1070c7f4` (SUMMARY.md)
- Verified live: `SELECT count(*) FROM feature_registry` = 259 (matches `FeatureVector` field count)

---
*Phase: 151-feature-primitives-expansion-theory-motivated-interaction-la*
*Completed: 2026-08-05*
