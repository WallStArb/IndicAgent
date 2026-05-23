---
phase: 091-instrument-registry
plan: "06"
subsystem: api
tags: [fastapi, pydantic, asyncpg, pg_notify, crud, instruments]

# Dependency graph
requires:
  - phase: 091-01
    provides: pg_notify trigger on instruments table (INSERT/UPDATE/DELETE)
  - phase: 091-02
    provides: LISTEN/NOTIFY consumer in pipeline CacheManager
provides:
  - POST /api/instruments (upsert with ON CONFLICT)
  - PUT /api/instruments/{symbol} (partial update - is_active or contract_details JSONB merge)
  - DELETE /api/instruments/{symbol} (soft-delete via is_active=false, 404 if absent)
  - InstrumentUpsert and InstrumentUpdate Pydantic request models
  - 8 unit tests covering happy paths, validation errors, and 404 cases
affects: [091-instrument-registry, api, instruments-pipeline-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Soft-delete via UPDATE is_active=false (not hard DELETE) preserves audit history and triggers pg_notify"
    - "JSONB merge via || operator (contract_details = contract_details || $2::jsonb) for partial updates"
    - "execute_command() return tag parsing: int(status.split()[-1]) for rows-affected count"
    - "FastAPI dependency_overrides with AsyncMock for unit tests - no real DB required"

key-files:
  created:
    - tests/unit/api/test_instruments_crud.py
  modified:
    - src/api/routes/instruments.py

key-decisions:
  - "Soft-delete (is_active=false via UPDATE) used instead of hard DELETE so DB trigger fires pg_notify and audit history is preserved"
  - "PUT merges contract_details fields via JSONB || operator; is_active handled as top-level column update separately"
  - "No explicit pg_notify call in route handlers - DB trigger installed in 091-01 fires automatically on INSERT/UPDATE"
  - "PUT first queries for symbol existence and returns 404 before any UPDATE to avoid silent no-op"

patterns-established:
  - "execute_command() status tag pattern: parse rows affected via int(status.split()[-1]) for 404 detection"
  - "Test app isolation: test_app = FastAPI() + router mount avoids main.py lifespan in unit tests"

requirements-completed: [INST-02]

# Metrics
duration: 4min
completed: 2026-05-19
---

# Phase 091 Plan 06: Instrument Registry CRUD API Summary

**FastAPI POST/PUT/DELETE endpoints for operator-driven instrument management, with Pydantic validation and soft-delete that propagates to the running pipeline via the existing pg_notify trigger chain.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-19T22:01:18Z
- **Completed:** 2026-05-19T22:05:37Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Three new CRUD endpoints added to `src/api/routes/instruments.py`: POST (upsert), PUT (partial update), DELETE (soft-delete)
- Pydantic request models with `Literal["equity","futures","fx","crypto"]` asset_class validation and `float | None` for numeric fields that rejects string values at the validation layer
- 8 unit tests covering: happy paths, invalid asset_class (422), invalid float type (422), 404 on missing symbol, soft-delete asserting UPDATE not hard DELETE
- Live smoke test confirmed POST creates row, DELETE sets is_active=false, and 404s return correctly

## Task Commits

1. **Task 1: Extend instruments router with POST/PUT/DELETE** - `fbb79e0a` (feat)
2. **Task 2: Add 8 unit tests for CRUD endpoints** - `9482cf11` (test)

## Files Created/Modified

- `src/api/routes/instruments.py` - Added InstrumentUpsert, InstrumentUpdate models and three write endpoints
- `tests/unit/api/test_instruments_crud.py` - 8 unit tests with AsyncMock db_manager via dependency_overrides

## Decisions Made

- Soft-delete via `UPDATE instruments SET is_active=false` (not `DELETE`) ensures the DB trigger fires pg_notify so the pipeline listener invalidates its cache, and audit history is preserved.
- PUT endpoint queries for symbol existence first (before any UPDATE) to reliably return 404, since `execute_command()` for a zero-match UPDATE still returns `"UPDATE 0"` but provides no early-exit path via Postgres.
- No explicit `pg_notify()` call in route handlers; the trigger installed in Plan 091-01 fires on every INSERT/UPDATE/DELETE automatically.
- JSONB merge via `||` operator allows partial updates to contract_details without overwriting fields the caller didn't include.

## Deviations from Plan

None - plan executed exactly as written. Added one extra test (`test_post_instrument_symbol_uppercased`) and one extra test (`test_put_instrument_invalid_tick_size_type_rejected`) beyond the required 6, for a total of 8 tests.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- INST-02 satisfied: operators can add/update/deactivate instruments via HTTP without touching code
- Changes propagate to the running pipeline via the trigger-NOTIFY-listener chain (Plans 091-01 and 091-02)
- Phase 091 complete: all 6 plans shipped (01-trigger, 02-listener, 03-settings-decomp, 04-migration-script, 05-get-active-contracts, 06-CRUD-API)

---
*Phase: 091-instrument-registry*
*Completed: 2026-05-19*
