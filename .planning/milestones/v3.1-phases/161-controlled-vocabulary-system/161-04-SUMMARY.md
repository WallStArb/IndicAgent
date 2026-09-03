---
phase: 161-controlled-vocabulary-system
plan: 04
subsystem: api
tags: [fastapi, controlled-vocabulary, asyncpg, read-only-endpoint]

# Dependency graph
requires:
  - phase: 161-01
    provides: "controlled_vocabulary / vocabulary_group / vocabulary_group_member schema + 6 seeded namespaces (migrations 239/240)"
provides:
  - "GET /api/vocabulary/{namespace} — returns codes/labels/groups for a Controlled Vocabulary namespace via a parameterized query"
  - "Router registered under /api/vocabulary in src/api/main.py"
affects: [dashboard, controlled-vocabulary-consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "FastAPI route uses Depends(get_db_manager) + DatabaseManager.fetch() (features.py's convention), not drift.py's inline get_connection import — see Deviations"

key-files:
  created:
    - src/api/routes/vocabulary.py
    - tests/unit/api/test_vocabulary_api.py
  modified:
    - src/api/main.py

key-decisions:
  - "Unknown namespace returns 404 (design doc's 'validate namespace against the known set' intent), not a 200 with empty codes"
  - "Route queries controlled_vocabulary/vocabulary_group_member directly via db_manager.fetch(), not through VocabularyService — the API process doesn't run VocabularyService.initialize(), and D-05 scopes that service to library-embedded daemon consumers, not this network endpoint"

patterns-established:
  - "Path-parameterized read-only metadata route: Depends(get_db_manager) + try/except -> 404 on any DB error, never a raw SQL error/500"

requirements-completed: []

# Metrics
duration: 25min
completed: 2026-07-18
---

# Phase 161 Plan 04: Controlled Vocabulary API Route Summary

**Backend `GET /api/vocabulary/{namespace}` FastAPI route returning codes/labels/groups for a seeded Controlled Vocabulary namespace via a parameterized asyncpg query, registered under `/api/vocabulary` in `main.py`.**

## Performance

- **Duration:** 25 min
- **Started:** 2026-07-18T00:01:00Z
- **Completed:** 2026-07-18T00:26:39Z
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- `GET /api/vocabulary/{namespace}` returns `{namespace, codes: [...], groups: {...}}` for a known namespace, sourced from `controlled_vocabulary` (codes) and `vocabulary_group_member` (groups)
- Unknown namespace (zero rows) or any DB error both surface as a clean 404 — never a raw SQL error or 500 (T-161-07)
- `namespace` is bound as a parameterized query argument (`$1`) throughout, never string-interpolated (T-161-01)
- Router registered in `src/api/main.py` under `prefix="/api/vocabulary"`
- 6 TestClient unit tests cover happy path, group payload shape, unknown namespace, DB-error path, and bound-parameter verification for both known and unknown namespaces

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement /api/vocabulary/{namespace} route** - `bbe8178b` (feat)
2. **Task 2: Register the vocabulary router in main.py** - `d093ce3e` (feat)

**Plan metadata:** (this commit, docs)

## Files Created/Modified
- `src/api/routes/vocabulary.py` — `APIRouter` with `GET /{namespace}`; two parameterized queries against `controlled_vocabulary` and `vocabulary_group_member`; 404 on zero rows or DB error
- `tests/unit/api/test_vocabulary_api.py` — `TestClient` + `dependency_overrides[get_db_manager]` tests (happy path, groups, unknown namespace, DB error, bound-parameter checks)
- `src/api/main.py` — added `vocabulary` to the `from .routes import (...)` tuple; appended `app.include_router(vocabulary.router, prefix="/api/vocabulary", tags=["vocabulary"])` after the existing `validation.router` line

## Decisions Made
- **404 for unknown namespace** (not 200 + empty `codes`): matches the design doc's "validate namespace against the known set" intent cited in the plan's acceptance criteria.
- **`db_manager.fetch()` via `Depends(get_db_manager)`, not `VocabularyService`**: the route is a read-side HTTP consumer, not a daemon embedding the library-cached service (D-05 in `161-CONTEXT.md` scopes `VocabularyService` to daemons that call `initialize()` at startup). Querying the tables directly, exactly as the sibling `drift.py`/`features.py` routes do, keeps the API process DB-only with no extra service lifecycle to wire into `main.py`'s lifespan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used features.py's `Depends(get_db_manager)` pattern instead of drift.py's `get_connection` import**
- **Found during:** Task 1 (implementation)
- **Issue:** The plan's primary analog, `src/api/routes/drift.py`, does `from src.core.database_manager import get_connection` — but `database_manager.py` has no module-level `get_connection` function (only `DatabaseManager.get_connection()`, an instance method). That import statement sits outside `drift.py`'s own `try/except`, so calling `GET /api/drift` today raises an uncaught `ImportError` (a pre-existing bug in a file outside this plan's scope — logged, not fixed, per the SCOPE BOUNDARY rule). Copying that pattern verbatim would have made the new vocabulary route equally broken on every real request, failing the plan's own "unknown namespace never a 500" acceptance criterion for every request, known or unknown.
- **Fix:** Used `src/api/routes/features.py`'s verified-working convention instead: `db_manager: DatabaseManager = Depends(get_db_manager)` injected via FastAPI `Depends`, calling `db_manager.fetch(query, *args)`. This is the same DB-access shape `161-PATTERNS.md`'s own test-pattern section flagged as needing a pre-implementation check ("check which DB-access convention the actual implementation picks before writing this test's dependency_overrides target").
- **Files modified:** `src/api/routes/vocabulary.py`, `tests/unit/api/test_vocabulary_api.py` (uses `dependency_overrides[dependencies.get_db_manager]`, matching `test_features_route.py`'s pattern instead of a `unittest.mock.patch` on a non-existent `get_connection`)
- **Verification:** All 6 route tests pass; full `tests/unit/` suite green (no regression)
- **Committed in:** `bbe8178b` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — analog file had a latent import bug)
**Impact on plan:** Necessary correctness fix; without it the route would 500 on every request, failing the plan's own acceptance criteria. No scope creep — `drift.py` itself was left untouched (out of this plan's `files` list; logged here, not fixed there).

## Issues Encountered
- This worktree's git branch was forked before Wave 1 (161-01/161-02) merged into `main`, so `production/migrations/239_controlled_vocabulary_schema.sql`, `240_controlled_vocabulary_seed_namespaces.sql`, and `src/config/vocabulary_service.py` are not present on disk here. Confirmed via `git show main:<path>` (read-only, no merge/reset performed) that this plan's files (`src/api/routes/vocabulary.py`, `src/api/main.py`, the test file) don't overlap with Wave 1's files, so no merge conflict is expected when the orchestrator merges this worktree back. Table/column names used in the route (`controlled_vocabulary(namespace, code, label, description, sort_order, is_deprecated)`, `vocabulary_group_member(namespace, group_name, code)`) were verified against `main`'s actual migration 239 rather than taken solely from the plan text.
- This worktree also lacked a `.venv` (a known gap — see `feedback_gsd_worktree_venv_missing.md`). Symlinked `.venv -> /home/bg/dev/indicagent/.venv` (filesystem-only, gitignored, not a git operation) so the pre-commit hook's ruff/black checks could run; both passed clean.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- `/api/vocabulary/{namespace}` is live and ready for a future dashboard consumer (explicitly out of scope for this phase per the plan's objective — "we aren't building ux now").
- `drift.py`'s broken `get_connection` import is a pre-existing bug outside this plan's file scope; not fixed here, worth a follow-up todo if `/api/drift` is ever exercised for real.

---
*Phase: 161-controlled-vocabulary-system*
*Completed: 2026-07-18*

## Self-Check: PASSED

- FOUND: src/api/routes/vocabulary.py
- FOUND: tests/unit/api/test_vocabulary_api.py
- FOUND: .planning/milestones/v3.1-phases/161-controlled-vocabulary-system/161-04-SUMMARY.md
- FOUND: bbe8178b (Task 1 commit)
- FOUND: d093ce3e (Task 2 commit)
- FOUND: 08f04d10 (SUMMARY commit)
