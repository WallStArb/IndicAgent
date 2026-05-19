---
phase: 091-instrument-registry
plan: "01"
subsystem: database
tags: [postgresql, asyncpg, pg_notify, instruments, fx, trigger, schema]

# Dependency graph
requires: []
provides:
  - "upsert_instruments() uses c.symbol as PK - FX pairs no longer collide"
  - "pg_notify trigger trg_instruments_notify on instruments table (AFTER INSERT OR UPDATE OR DELETE)"
  - "USDJPY row present in instruments table with correct contract_details JSONB"
  - "create_schema.sql instruments DDL matches production (base TEXT NOT NULL, expiry DATE columns)"
affects:
  - "091-02 (LISTEN listener depends on trigger existing)"
  - "091-03 (get_active_contracts flip depends on USDJPY present and PK correct)"
  - "091-04 (migration script depends on fixed upsert PK)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "pg_notify trigger pattern: COALESCE(NEW.symbol, OLD.symbol) for INSERT/UPDATE/DELETE safety"
    - "CREATE OR REPLACE TRIGGER for idempotent DDL scripts"

key-files:
  created:
    - production/scripts/add_instruments_trigger.sql
  modified:
    - src/core/database_manager.py
    - production/schemas/create_schema.sql

key-decisions:
  - "FX PK uses full symbol (USDJPY, USDCHF) not base currency (USD) - eliminates collision for shared-base FX pairs"
  - "Trigger uses COALESCE(NEW.symbol, OLD.symbol) and RETURN COALESCE(NEW, OLD) for correct DELETE behavior"
  - "USDJPY row inserted with exact Instrument dataclass field names to match model_dump() output"
  - "create_schema.sql updated with DEFAULT '' on base column to match live DB (avoids NOT NULL constraint failure on existing rows)"

patterns-established:
  - "Pattern: Trigger SQL scripts use CREATE OR REPLACE for both FUNCTION and TRIGGER - safe to re-run"
  - "Pattern: All instruments rows keyed by full symbol (c.symbol), not base currency (c.base)"

requirements-completed: [INST-01, INST-05]

# Metrics
duration: 3min
completed: 2026-05-19
---

# Phase 091 Plan 01: Instrument Registry Foundation Summary

**Fixed FX symbol collision in upsert_instruments (c.base to c.symbol as PK), installed pg_notify trigger on instruments table, and added missing USDJPY row - DB now has 4 FX instruments and fires LISTEN notifications on all row changes**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-19T21:32:26Z
- **Completed:** 2026-05-19T21:34:50Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Fixed latent FX collision bug: `upsert_instruments()` used `c.base` as the DB PK, causing USDJPY and USDCHF (both `base="USD"`) to collide - USDJPY was silently dropped on every API startup
- Installed `trg_instruments_notify` trigger that fires `pg_notify('instruments', symbol)` on INSERT, UPDATE, and DELETE - foundation for sub-second hot-reload in Plans 02 and 03
- Inserted USDJPY row with correct contract_details JSONB matching Instrument dataclass field names; DB now has 4 FX instruments
- Synced `create_schema.sql` to match production DDL: added `base TEXT NOT NULL DEFAULT ''` and `expiry DATE` columns

## Task Commits

1. **Task 1: Fix upsert_instruments() FX collision** - `dfbbd09c` (fix)
2. **Task 2: Create idempotent pg_notify trigger SQL and apply to live DB** - `bcef3b02` (feat)
3. **Task 3: Add USDJPY row and sync create_schema.sql** - `37ec2c88` (fix)

## Files Created/Modified

- `src/core/database_manager.py` - Changed params tuple first element from `c.base` to `c.symbol` in `upsert_instruments()`; added inline comment explaining FX collision rationale
- `production/scripts/add_instruments_trigger.sql` - New: idempotent CREATE FUNCTION + CREATE TRIGGER using COALESCE for DELETE safety; applied to live DB
- `production/schemas/create_schema.sql` - Added `base TEXT NOT NULL DEFAULT ''` and `expiry DATE` to instruments CREATE TABLE to match production

## Decisions Made

- Used `COALESCE(NEW.symbol, OLD.symbol)` in trigger function body and `RETURN COALESCE(NEW, OLD)` - required because on DELETE, NEW is NULL; bare `NEW.symbol` would error
- `base TEXT NOT NULL DEFAULT ''` (with default) rather than `base TEXT NOT NULL` - prevents NOT NULL constraint failure if the DDL is ever run against a DB with existing rows that predate the column
- USDJPY contract_details fields match the live USDCHF row structure exactly (verified via `SELECT contract_details FROM instruments WHERE symbol='USD'`)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Trigger is live in production DB; Plan 02 (LISTEN listener in CacheManager) can be implemented immediately
- `upsert_instruments()` fix is deployed; Plan 04 migration script will correctly insert full-symbol FX rows
- USDJPY is present with correct data; Plan 03 `get_active_contracts()` flip will include all 4 FX instruments
- Note: legacy FX rows keyed by base (EUR, GBP, USD) still exist alongside new USDJPY row; Plan 04 migration script handles cleanup of the legacy USD/EUR/GBP rows

---
*Phase: 091-instrument-registry*
*Completed: 2026-05-19*
