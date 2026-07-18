---
phase: 161-controlled-vocabulary-system-planned
plan: 02

subsystem: infra
tags: [controlled-vocabulary, asyncpg, config-service-pattern, apr-analog]

# Dependency graph
requires:
  - phase: 161-01
    provides: "controlled_vocabulary / vocabulary_group / vocabulary_group_member schema (parallel plan, not a hard build-time dependency for this module)"
provides:
  - "VocabularyService: cached, library-embedded read-only projection over the 3 vocabulary tables"
  - "VocabEntry frozen dataclass (code, label, description, sort_order, is_deprecated)"
  - "check_enum_divergence(): pure three-way ENUM divergence comparison, unit-tested for future ENUM namespace additions"
affects: [161-03, 161-04, api-vocabulary-route, vocabulary-drift-audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cached-library-not-microservice service shape (D-05), mirrors ConfigService exactly"
    - "Prewarm-all-at-init, zero lazy-DB-fallback cache pattern"

key-files:
  created:
    - src/config/vocabulary_service.py
    - tests/unit/test_vocabulary_service.py
  modified: []

key-decisions:
  - "D-05/D-06/D-07 (from 161-CONTEXT.md) implemented as written: VocabularyService is a plain library, no DAG node; D-06's 3-part namespace-addition test documented verbatim in-module; no shared base class with ConceptRegistryService"
  - "check_enum_divergence() intentionally not wired into initialize() for any of the six live namespaces — all are TEXT-backed, none ENUM-backed; the mechanism exists purely for a future ENUM namespace addition per the design doc"

patterns-established:
  - "TDD RED/GREEN gate per task: test(161-02) commit with a failing test, followed by feat(161-02) commit making it pass, for both Task 1 and Task 2"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-07-17
---

# Phase 161 Plan 02: VocabularyService Summary

**Cached, library-embedded `VocabularyService` (ConfigService-shaped) with synchronous DB-free hot-path lookups over `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member`, plus a pure three-way ENUM divergence comparison function.**

## Performance

- **Duration:** ~5 min (first commit 2026-07-17T20:16:09-04:00, last commit 2026-07-17T20:17:13-04:00)
- **Started:** 2026-07-17T20:16:09-04:00
- **Completed:** 2026-07-17T20:17:13-04:00
- **Tasks:** 2 completed
- **Files modified:** 2 (both created)

## Accomplishments
- `VocabularyService` mirrors `ConfigService`'s exact cache-first shape (`__init__`/`initialize()`/`close()`), prewarming `_entries` (namespace -> code -> `VocabEntry`) and `_groups` ((namespace, group) -> `frozenset[str]`) in one `_load_all()` pass with no lazy DB fallback on miss.
- Four synchronous, DB-free hot-path readers: `codes()`, `label()` (falls back to the code on unknown), `group_codes()` (returns `frozenset()` on unknown group), `namespace()` (returns `[]` on unknown namespace).
- D-06's 3-part namespace-addition test documented verbatim in the module docstring (membership mutability / external enumeration without importing Python / concrete metadata-enrichment consumers).
- Pure `check_enum_divergence()` function: raises `ValueError` naming the namespace and the differing members on any pairwise mismatch among registry codes / Python enum members / pg_enum catalog labels; silent pass when all three agree. Kept separate from the thin async `_fetch_pg_enum_labels()` catalog-query helper so the comparison logic is unit-testable with zero DB I/O.
- 11 unit tests, all pure-Python/no-DB, all green.

## Task Commits

Each task followed the TDD RED/GREEN cycle with separate commits:

1. **Task 1: Implement VocabularyService (cache + lookups)**
   - `c97d318f` (test) — failing tests for cache lookups, confirmed RED (ImportError, module didn't exist)
   - `782e582d` (feat) — VocabularyService implementation, confirmed GREEN
2. **Task 2: Three-way ENUM divergence check**
   - `12d496f9` (test) — failing test for `check_enum_divergence`, confirmed RED (ImportError, symbol didn't exist)
   - `3769e238` (feat) — `check_enum_divergence()` + `_fetch_pg_enum_labels()`, confirmed GREEN

## Files Created/Modified
- `src/config/vocabulary_service.py` — `VocabEntry` frozen dataclass, `VocabularyService` (cache + 4 sync readers), `check_enum_divergence()`, `_fetch_pg_enum_labels()` async helper
- `tests/unit/test_vocabulary_service.py` — 11 pure-Python tests: cache lookups (8), `test_no_db_calls_after_init`, ENUM divergence (2)

## Decisions Made
None beyond what CONTEXT.md's D-05/D-06/D-07 already locked — implemented as designed. No architectural deviation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Symlinked main-repo `.venv` into the worktree**
- **Found during:** Task 1, first commit attempt
- **Issue:** This worktree has no `.venv` (known gotcha — worktrees don't get a fresh venv). The pre-commit hook resolves `REPO_ROOT` via `git rev-parse --show-toplevel`, which in worktree mode returns the worktree path, so `ruff`/`black` were unresolvable and the commit was blocked.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a362270c14f1fc215/.venv`. `.venv` is gitignored (`.gitignore:130`), so the symlink is untracked and does not appear in `git status` or get committed.
- **Files modified:** none (symlink only, outside git)
- **Verification:** `git status --short` after the symlink shows a clean tree with no `.venv` entry; subsequent commits ran ruff/black successfully.
- **Committed in:** N/A (not a tracked change)

---

**Total deviations:** 1 auto-fixed (1 blocking, environment-only, no source-code impact)
**Impact on plan:** Zero impact on shipped code. No scope creep.

## Issues Encountered
None beyond the `.venv` symlink workaround documented above.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- `VocabularyService` and `check_enum_divergence()` are ready for any consumer to embed (e.g., the `/api/vocabulary/{namespace}` route and the column-backed drift audit module, both later plans in this phase).
- This plan does not depend on Plan 161-01's migrations at build time (pure Python, no schema import), but functional integration (calling `initialize()` against a live DB) requires Plan 161-01's `controlled_vocabulary`/`vocabulary_group`/`vocabulary_group_member` tables to exist — verified via unit tests only in this plan, per its own scope.
- No blockers.

---
*Phase: 161-controlled-vocabulary-system-planned*
*Completed: 2026-07-17*

## Self-Check: PASSED

- FOUND: `src/config/vocabulary_service.py`
- FOUND: `tests/unit/test_vocabulary_service.py`
- FOUND: `.planning/phases/161-controlled-vocabulary-system-planned/161-02-SUMMARY.md`
- FOUND commits: `c97d318f`, `782e582d`, `12d496f9`, `3769e238`, `3fcc9a9e`
