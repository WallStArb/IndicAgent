---
phase: 165-swing-fib-trend-structure-primitives
plan: 01
subsystem: intelligence
tags: [feature-factory, swing, fibonacci, trend-structure, session-levels, apr, timescaledb, feature-vector-persistence]

# Dependency graph
requires:
  - phase: 164-smc-institutional-footprint-primitives
    provides: "_SMC_FIELD_NAMES append-only persistence slice pattern (most recent analog for a contract-only data-contract plan)"
provides:
  - "41 new feature_vectors columns (ATR-distance/bounded/count/categorical only, zero raw price levels or raw bar indices) + matching feature_registry rows"
  - "FeatureVector dataclass with all 41 swing/fib/trend/session fields as float | None (D-01 nullable-field fix), threaded through _build_feature_vector as None placeholders (208 -> 249 total fields)"
  - "_SWING_FIB_TREND_FIELD_NAMES persistence slice, fully wired through INSERT column list, placeholder generator, _TOTAL_COLUMNS, params tuple (217 -> 258 total columns)"
  - "17 feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/feature.fib.*/feature.session_levels.* APR keys covering every hardcoded numeric constant in the 5 archived i3_structure plugins"
  - "FeatureFactoryConfig with 17 new defaulted fields, wired from APR in both feature_vector_pipeline.py (live) and backfill_feature_factory.py (batch)"
affects: ["165-02-swing-detection-trend-structure", "165-03-swing-momentum-fibonacci-zones", "165-04-session-levels"]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-defaulted float | None dataclass block placed BEFORE the defaulted canary block (D-01's nullable-field fix requires no default, unlike Phase 164's SMC block which is defaulted and placed AFTER canary) -- the two placement strategies now coexist in the same dataclass, both documented in schemas.py's docstring"

key-files:
  created:
    - production/migrations/267_swing_fib_trend_structure_primitives.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/feature_factory.py
    - src/intelligence/features/feature_vector_persistence.py
    - services/feature_vector_pipeline.py
    - services/backfill_feature_factory.py
    - tests/unit/test_feature_factory.py
    - tests/unit/test_canary_predictors.py
    - tests/unit/intelligence/test_feature_factory_p7.py
    - tests/unit/services/test_feature_vector_writer.py
    - tests/unit/services/test_feature_vector_writer_column_mapping.py
    - tests/unit/services/test_backfill_feature_factory.py

key-decisions:
  - "Migration number 267 confirmed free at execution time (no renumbering collision, unlike migration 255's 243->255 or migration 266's 259->266) -- 266_smc_institutional_footprint.sql was the prior max"
  - "feature_registry.group_name = 'session' (not 'structure' or 'smart_money') -- matches 165-CONTEXT.md's canonical_refs and the live CHECK constraint's enumerated values"
  - "The 41 new fields are non-defaulted float | None (D-01), placed immediately before the canary block -- the opposite placement from Phase 164's 36 SMC fields (defaulted, placed after canary), because Python dataclass field ordering forbids a non-defaulted field following a defaulted one"
  - "Migration file split into two commits (Task 1: sections 1+2; Task 2: append section 3) by writing an intermediate sections-1-2-only version, verifying its idempotent re-apply, committing, then restoring the full file for Task 2's commit -- honors the plan's own two-task boundary despite implementing the DDL in one continuous pass"

patterns-established:
  - "17-key APR block for a single contract-only plan (Task 2), all [conventional] provenance, defaulted FeatureFactoryConfig fields appended at dataclass end (same avoid-blast-radius rationale as Phase 163/164)"

requirements-completed: ["D-01", "D-02", "D-03", "D-04", "D-06"]

# Metrics
duration: 55min
completed: 2026-07-28
---

# Phase 165 Plan 01: Swing/Fib/Trend/Session Structure Data Contract Summary

**Migration 267 + FeatureVector/domain/persistence contract for 41 swing/fib/trend/session fields, 17 feature.swing.*/feature.trend_structure.*/feature.swing_momentum.*/feature.fib.*/feature.session_levels.* APR keys wired into both live and batch FeatureFactoryConfig sites -- contract-only, zero compute logic, ready for Plans 02-04.**

## Performance

- **Duration:** ~55 min
- **Started:** 2026-07-28T03:20:00-04:00 (approx)
- **Completed:** 2026-07-28T03:37:07-04:00
- **Tasks:** 3 (all `type="auto"`)
- **Files modified:** 12 (1 new migration, 5 source, 6 test)

## Accomplishments
- Wrote migration 267: 41 new `feature_vectors` columns (all `DOUBLE PRECISION`, ATR-distance/bounded/count/categorical only -- zero raw price levels or raw bar indices per D-02/D-04) with `COMMENT ON COLUMN` documenting formula + NULL condition for every field, plus 41 matching `feature_registry` rows (`group_name='session'`, `tier='2_theory'`, `added_phase='165'`)
- Appended 17 `feature.swing.*`/`feature.trend_structure.*`/`feature.swing_momentum.*`/`feature.fib.*`/`feature.session_levels.*` APR keys (Section 3 of the same migration) covering every hardcoded numeric constant found across the 5 archived `i3_structure` plugin files (`swing_detector.py`, `trend_structure.py`, `swing_momentum.py`, `fibonacci_zones.py`, `session_levels.py`), each with `[conventional]` provenance; wired all 17 into `FeatureFactoryConfig` and both real config-build entrypoints (`feature_vector_pipeline.py`, `backfill_feature_factory.py`)
- Added all 41 new `FeatureVector` fields as one contiguous `float | None` block with NO default (D-01's nullable-field fix), placed immediately before the defaulted canary block -- Python dataclass field-ordering forces this placement since a non-defaulted field cannot follow a defaulted one; threaded through `_build_feature_vector`, both `compute()`/`compute_batch()` call sites, and `_cold_start_vector` as `None` placeholders
- Added `_SWING_FIB_TREND_FIELD_NAMES` persistence slice (derive-by-name off `_ALL_FEATURE_VECTOR_FIELD_NAMES`, matching the established convention), appended to `_ALL_COLUMN_NAMES` and the INSERT params tuple; fixed two pre-existing stale comments in `feature_vector_persistence.py` (a "181 columns" header comment and a "181-element tuple" docstring that Phase 164 had left un-updated at 217) while touching the same lines
- Bumped every hardcoded field/param count assertion by 41 across 6 test files (208->249 fields, 217->258 params); added a new `gap_filled`-at-index-257 last-element test while keeping the `sr_level_count`/`manip_strength` boundary-pinning tests from Phases 163/164 intact at their own indices
- Full `tests/unit/` suite green (0 failures, 3 pre-existing unrelated skips); ic_engine startup drift gate verified live against the DB (`feature_registry.feature_name` set == `dataclasses.fields(FeatureVector)` name set, both 249)

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 267 -- 41 columns + COMMENTs + 41 feature_registry rows** - `b56c8273` (feat)
2. **Task 2: Migration 267 Section 3 -- 17 APR keys + FeatureFactoryConfig SMC-analog fields + wire both config sites** - `b741b4fe` (feat)
3. **Task 3: FeatureVector 41 nullable fields + domain registry + _build_feature_vector/_cold_start placeholders + persistence slice + test-count blast radius** - `d21a5ba3` (feat)

_No TDD tasks in this plan; all three are `type="auto"`. Task 1's migration file was written as sections 1-3 in one continuous pass, then temporarily split back to a sections-1-2-only version for Task 1's commit (verified idempotent re-apply against the live DB before committing), restored to the full 3-section file for Task 2's commit -- honoring the plan's own two-task commit boundary._

## Files Created/Modified
- `production/migrations/267_swing_fib_trend_structure_primitives.sql` - 41 columns + 41 registry rows + 17 APR keys (3-section migration, mirrors migration 266's template)
- `src/intelligence/schemas.py` - 41 new `FeatureVector` fields (`float | None`, no default, one contiguous block immediately before the canary block), docstring group table + Total 208->249, updated the "non-optional fields typed float" claim to note this block's exception
- `src/intelligence/feature_factory.py` - 41 `FEATURE_VECTOR_DOMAIN` entries (after the Phase 163 S/R block), `_build_feature_vector` signature + return construction, both `compute()`/`compute_batch()` call sites, `_cold_start_vector`, 17 `swing_*`/`trend_structure_*`/`fib_*`/`session_levels_*` `FeatureFactoryConfig` fields + docstring APR mapping
- `src/intelligence/features/feature_vector_persistence.py` - `_SWING_FIB_TREND_FIELD_NAMES` slice threaded through INSERT SQL, placeholder generator, `_TOTAL_COLUMNS`, params tuple; fixed two stale pre-existing column-count comments while editing adjacent lines
- `services/feature_vector_pipeline.py` - 17 `feature.swing.*`/etc. keys in `_THRESHOLD_KEYS` + `_prewarm_threshold_config()` wiring
- `services/backfill_feature_factory.py` - matching 17-key `cfg.get_sync()` wiring in `_build_feature_factory_config()`
- 6 test files - stale field-count assertions updated (208->249, 217->258); 3 direct `FeatureVector(...)` constructions (`test_feature_vector_writer.py`, `test_feature_vector_writer_column_mapping.py`, `test_backfill_feature_factory.py`) given the 41 new required kwargs; one new last-element test added

## Decisions Made
- Migration number 267 confirmed free via `ls production/migrations/ | sort -V | tail -3` (266 was the prior max, no renumbering collision this time)
- `feature_registry.group_name = 'session'` (matches 165-CONTEXT.md's canonical_refs and the live CHECK constraint)
- The 41 new fields are placed BEFORE the canary block (opposite of Phase 164's SMC placement) because D-01 requires them non-defaulted; documented explicitly in both the migration header and the schemas.py docstring so a future reader isn't confused by the two different placement strategies coexisting in the same dataclass
- Fixed two stale column-count comments in `feature_vector_persistence.py` left un-updated by Phase 164 (said "181"/"181-element" when the live count was actually 217) while touching the same lines for my own edit -- Rule 1 (bug fix), in-scope since I was already modifying those exact comments

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale column-count comments in feature_vector_persistence.py**
- **Found during:** Task 3, while updating the module docstring changelog and the `_STRUCTURAL_PREFIX_COLUMN_NAMES` header comment
- **Issue:** Two pre-existing comments (`# 181 columns (as of 2026-07-23)` header, and `feature_vector_to_insert_params`'s `"""Serialize ... to the canonical 181-element INSERT tuple."""` docstring) still said "181" even though Phase 164 had already landed 217 real columns -- Phase 164's SUMMARY didn't call this out, so it silently drifted stale for one phase
- **Fix:** Updated both to state the correct pre-165 value (217) alongside the new 165 total (258), and added the missing `$182-$217`/SMC section to the params-tuple docstring that Phase 164 had also omitted
- **Files modified:** `src/intelligence/features/feature_vector_persistence.py`
- **Verification:** `tests/unit/test_feature_vector_persistence_completeness.py` full pass; manual read-through of the corrected docstring against `_ALL_COLUMN_NAMES`'s actual composition
- **Committed in:** `d21a5ba3`

---

**Total deviations:** 1 auto-fixed (Rule 1), in-scope since it touched lines already being edited for this plan's own changes
**Impact on plan:** No scope creep -- documentation-only correction to comments this plan's own edits were already adjacent to.

## Issues Encountered
None. No auth gates, no architectural decisions needed, no package installs. The one non-trivial engineering choice (splitting the migration file into two commits to match the plan's two-task boundary) was handled by writing an intermediate sections-1-2-only file version, verifying it against the live DB (idempotent `ADD COLUMN IF NOT EXISTS`/`ON CONFLICT DO NOTHING` re-apply), committing it, then restoring the full 3-section file for Task 2 -- no functional risk since the DB state was correct throughout (all 3 sections were applied to the live DB before either commit was made).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plans 02 (swing detection + trend structure), 03 (swing momentum + fibonacci zones), 04 (session levels) can now replace `None` placeholders with real computed values against a fixed, drift-free contract (registry==dataclass, persistence slice complete, all 17 APR knobs already seeded and wired)
- No `FeatureCache` mutator work was in this plan's scope (unlike Phase 164 Plan 01, which built `update_overnight_range()` early) -- Plan 04's session-boundary mutator (D-08/D-09, `update_session_vp()`/`update_wk_vwap()` analogs per 165-PATTERNS.md Pattern 7) is entirely new work for that plan, not started here
- No blockers. Full `tests/unit/` suite green (0 failures), ruff/black clean on every touched file.

## Known Stubs
All 41 new `FeatureVector` fields persist as `NULL` until Plans 02-04 land (intentional, contract-only plan per its own objective) -- not a stub in the "unfinished feature" sense; documented in the plan's own truths/artifacts and re-stated here per the executor's stub-tracking requirement so the verifier doesn't flag it as an unexpected gap:
- `src/intelligence/feature_factory.py` -- all 41 swing/fib/trend/session kwargs passed as `None` at both `_build_feature_vector` call sites (`compute()`, `compute_batch()`) and at `_cold_start_vector`

---
*Phase: 165-swing-fib-trend-structure-primitives*
*Completed: 2026-07-28*

## Self-Check: PASSED

All 7 key files verified present; all 3 commit hashes (b56c8273, b741b4fe, d21a5ba3) verified present in git log.
