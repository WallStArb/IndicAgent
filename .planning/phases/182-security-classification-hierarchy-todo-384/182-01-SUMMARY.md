---
phase: 182-security-classification-hierarchy-todo-384
plan: 01
subsystem: database
tags: [postgresql, timescaledb, asyncpg, migration, reference-data, classification, point-in-time]

# Dependency graph
requires: []
provides:
  - "classification_scheme / classification_node / instrument_classification tables, live (migration 364)"
  - "ClassificationService (src/config/classification_service.py) -- cached, no-DB-hot-path as-of read layer"
  - "Shared classification contract (DEFAULT_SCHEME, SECTOR_LEVEL, source_ref constants, ClassificationAssignment, current_level_name_sql)"
affects: [182-03, 182-04, 182-05, 182-06, 182-07]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cached read-layer service mirroring VocabularyService's constructor/initialize/_load_all/sync-reader shape"
    - "Point-in-time schema: PK (symbol, scheme, valid_from) + partial unique current-row index WHERE valid_to IS NULL"
    - "Pure module-level _build_caches(node_rows, assignment_rows) builder, called by _load_all, enforcing referential integrity and overlap detection as RuntimeError"

key-files:
  created:
    - production/migrations/364_classification_schema.sql
    - src/config/classification_service.py
    - tests/unit/test_classification_service.py
  modified: []

key-decisions:
  - "src/core/classification_access.py (Ring 0 wrapper) NOT built this plan -- no consumer needs it yet; an unregistered wrapper would silently return unclassified for every symbol, the exact silent-wrong-answer failure CLAUDE.md forbids. Ships with the first daemon consumer (deferred per plan's own discretion note)."
  - "tests/unit/_classification_fakes.py NOT built this plan -- no caller yet, would be dead code (vulture); every consumer test in this phase populates a real ClassificationService's caches directly instead."
  - "ClassificationService.close() only closes a pool it created itself (_owns_pool), unlike VocabularyService which closes unconditionally -- protects a future caller that injects its own BaseBatch pool (e.g. the coverage auditor, Plan 06)."

requirements-completed: [D-01, D-02, D-07, D-08, D-11]

# Metrics
duration: 20min
completed: 2026-09-25
---

# Phase 182 Plan 01: Layer 1 classification schema + ClassificationService Summary

**Migration 364 (three-table point-in-time schema, applied live and committed together) plus `ClassificationService`, a `VocabularyService`-shaped cached read layer with an as-of lookup that never returns None.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-25T12:25Z (approx, first file read)
- **Completed:** 2026-09-25T12:43:54-04:00 (last commit)
- **Tasks:** 2 (Task 2 split RED/GREEN per its `tdd="true"` flag)
- **Files modified:** 3 created, 0 modified

## Accomplishments
- `classification_scheme` / `classification_node` / `instrument_classification` live in the indicagent DB: partial unique current-row index, `ON DELETE RESTRICT`, node-immutability structural CHECKs, no seed rows (seed is a later plan).
- `ClassificationService`: as-of lookup (`node_at_level`, `name_at_level`, `assignment_as_of`), zero hot-path DB calls after `initialize()`, `unclassified` fallback that is never `None`.
- The full shared contract every wave-2 plan (03/04/05/06) imports against: `DEFAULT_SCHEME`, `SECTOR_LEVEL`, the three `SOURCE_REF_*` constants, `ALLOWED_SOURCE_REFS`, `unclassified_code`, `label_or_unclassified`, `current_level_name_sql` (with an injection-shaped-alias guard), `ClassificationAssignment`, `ClassificationNode`, `AssignmentRow`.
- 26 passing unit tests, pure-Python, no DB connection opened by the test file (verified by grep).
- Live smoke test against the (still-empty) schema: `ClassificationService.node_at_level('SPY', 1)` returns `indicagent_v1:unclassified`, confirming the service initializes cleanly against migration 364's real tables.
- Full `tests/unit/ -q` suite still green (2 pre-existing, unrelated skips only).

## Task Commits

1. **Task 1: Migration 364, applied live, committed immediately** - `8dd8aea57` (feat)
2. **Task 2a: Failing tests for ClassificationService (RED)** - (test commit, superseded in message by 2b's squashed rename; see below)
3. **Task 2b: Implement ClassificationService (GREEN) + rename a duplicate test name flagged by pre-commit** - `906d3e497` (feat)

Note: the RED-phase `test(182-01): add failing tests...` commit was made, then immediately amended in the natural next commit by the pre-commit duplicate-test-names hook forcing a rename (`test_no_db_calls_after_init` collided with `test_vocabulary_service.py`'s own test of the same name) before the GREEN commit could land -- both the test file and the implementation file ended up committed together in `906d3e497` because the rename had to happen before the hook would allow the GREEN commit through. `git log --oneline -5` shows both `8dd8aea57` and `906d3e497` as the two real commits for this plan; the intermediate RED commit's tree is fully superseded by `906d3e497`.

**Plan metadata:** (this commit, docs: complete plan)

## Files Created/Modified
- `production/migrations/364_classification_schema.sql` - Layer 1 schema: 3 tables, partial unique index, structural CHECKs, no seed rows
- `src/config/classification_service.py` - `ClassificationService` + shared contract (constants, dataclasses, `current_level_name_sql`, `_build_caches`)
- `tests/unit/test_classification_service.py` - 26 pure-Python unit tests, no DB

## Decisions Made
- Migration number confirmed free both locally and on `origin/main` before writing (364; re-checked via `git fetch` + `git ls-tree origin/main`).
- `ClassificationService.close()` tracks pool ownership (`_owns_pool`) rather than closing unconditionally like `VocabularyService` -- explicit deviation from the mirrored template, called out in the plan's own `<action>` text, protecting a future caller (Plan 06's coverage auditor) that injects its own pool.
- `src/core/classification_access.py` and `tests/unit/_classification_fakes.py` deliberately not built (both pre-recorded as discretion choices in the plan's `<objective>`, not a new decision made during execution).

## Deviations from Plan

**1. [Rule 3 - Blocking] Renamed a test function to fix a pre-commit-caught name collision**
- **Found during:** Task 2 (GREEN commit attempt)
- **Issue:** `test_no_db_calls_after_init` in the new test file collided with an identically-named test in `tests/unit/test_vocabulary_service.py`; the repo's duplicate-test-names pre-commit hook blocked the commit.
- **Fix:** Renamed to `test_classification_service_no_db_calls_after_init` in the new file only.
- **Files modified:** `tests/unit/test_classification_service.py`
- **Verification:** Pre-commit hook's duplicate-test-names check passed on retry; `.venv/bin/pytest tests/unit/test_classification_service.py -x -q` still green after the rename.
- **Committed in:** `906d3e497`

---

**Total deviations:** 1 auto-fixed (1 blocking, tooling-caught naming collision)
**Impact on plan:** Cosmetic rename only, no behavior change. No scope creep.

## Issues Encountered
None beyond the deviation above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 03 (node-list design + seed migration render) and Plan 04 (onboarding gate) can import the full shared contract from `src/config/classification_service.py` exactly as specified in this plan's `<interfaces>` block -- no renames needed.
- `classification_scheme` has 0 rows by design; Plan 03/07 own seeding it. Any consumer calling `ClassificationService.node_at_level()` today correctly gets `indicagent_v1:unclassified` for every symbol until the seed lands.
- `src/core/classification_access.py` remains unbuilt; the first daemon-style consumer (a later plan/phase) should build it then, per this plan's discretion note -- do not resurrect it speculatively.

---
*Phase: 182-security-classification-hierarchy-todo-384*
*Plan: 01*
*Completed: 2026-09-25*
