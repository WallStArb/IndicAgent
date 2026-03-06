---
phase: 16-llm-intelligence-layer
plan: "06"
subsystem: database
tags: [timescaledb, postgresql, migration, hypertable, llm_calls]

# Dependency graph
requires:
  - phase: 16-llm-intelligence-layer
    provides: "019_llm_intelligence_layer.sql schema foundation for llm_calls and llm_model_scores"
provides:
  - "Migration 020: idempotent hypertable conversion for llm_calls (composite PK + create_hypertable)"
  - "Corrected migration 019: composite PK (call_id, called_at), no silent if_not_exists"
  - "7 unit tests verifying migration SQL structure and idempotency"
affects: [llm_writer_service, future-deployments, ci-staging-environments]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TimescaleDB hypertable: composite PK (id, time_col) required when time_col is partition column"
    - "Hypertable migration guard: DO $$ IF NOT EXISTS (timescaledb_information.hypertables) THEN ... END IF"
    - "Migration SQL unit tests: read SQL as plain text, assert structural properties — no DB connection needed"

key-files:
  created:
    - production/migrations/020_llm_calls_hypertable_fix.sql
    - tests/unit/test_migration_020.py
  modified:
    - production/migrations/019_llm_intelligence_layer.sql

key-decisions:
  - "Migration 020 uses DO $$ idempotency guard checking timescaledb_information.hypertables before ALTER/create_hypertable"
  - "migrate_data => TRUE required because llm_calls already has rows in production"
  - "019 source corrected so future deployments (CI, staging, new environments) fail loudly rather than silently creating a plain table"

patterns-established:
  - "SQL migration unit tests: structural assertions on SQL text, no DB required — fast and CI-clean"

requirements-completed: [LLM-01]

# Metrics
duration: 4min
completed: 2026-03-06
---

# Phase 16 Plan 06: LLM Calls Hypertable Fix Summary

**Migration 020 converts llm_calls from plain table to TimescaleDB hypertable via composite PK (call_id, called_at) and idempotent DO-block guard; migration 019 source corrected to prevent silent no-op on future deployments.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-06T05:05:20Z
- **Completed:** 2026-03-06T05:09:30Z
- **Tasks:** 1 of 2 complete (Task 2 is checkpoint:human-action — requires docker exec in user terminal)
- **Files modified:** 4

## Accomplishments

- Created idempotent migration 020 that drops single-column PK, adds composite PK (call_id, called_at), and calls create_hypertable with migrate_data to handle existing rows
- Corrected migration 019 source SQL: composite PK constraint replaces UUID PRIMARY KEY; silent if_not_exists removed so future deployments fail loudly on schema errors
- 7 unit tests confirm migration SQL structure without any DB connection (structural text assertions — fast, CI-clean)
- Fixed pre-existing ruff noise in test_ai_narrative_service.py (unused imports from prior plan)

## Task Commits

Each task was committed atomically:

1. **Task 1: Write migration 020 + corrected 019 + unit test** - `428f175` (feat)

**Plan metadata:** pending final commit after checkpoint

_Note: TDD tasks may have multiple commits (test -> feat -> refactor)_

## Files Created/Modified

- `/home/bg/dev/indicagent/production/migrations/020_llm_calls_hypertable_fix.sql` - Idempotent hypertable conversion: drops UUID PK, adds composite PK, create_hypertable with migrate_data
- `/home/bg/dev/indicagent/tests/unit/test_migration_020.py` - 7 structural unit tests for migration SQL (no DB needed)
- `/home/bg/dev/indicagent/production/migrations/019_llm_intelligence_layer.sql` - Corrected: UUID NOT NULL + table-level PRIMARY KEY (call_id, called_at); removed if_not_exists from create_hypertable

## Decisions Made

- Used DO $$ idempotency guard checking `timescaledb_information.hypertables` so migration 020 is safe to re-run without errors
- `migrate_data => TRUE` required because production table already has rows from Phase 16 llm_writer_service
- Migration 019 source corrected (not just 020 fix) so fresh deployments to CI/staging/new environments also get the correct schema

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed test variable name `l` causing ruff E741 errors in new test file**
- **Found during:** Task 1 (test authoring from plan template)
- **Issue:** Plan template used single-letter variable `l` in list comprehensions; ruff E741 flags ambiguous names
- **Fix:** Renamed `l` to `line` in `test_migration_020.py` — tests still pass
- **Files modified:** tests/unit/test_migration_020.py
- **Verification:** `ruff check tests/unit/test_migration_020.py` — 0 errors
- **Committed in:** 428f175 (Task 1 commit)

**2. [Rule 3 - Blocking] Fixed comment lines causing test_create_hypertable_no_if_not_exists false positive**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Migration 020 comments contained "create_hypertable" and "if_not_exists" on the same line; test pattern-matched these comment lines and failed
- **Fix:** Rewrote comments to not have both keywords on same line (comments refer to the old behavior, not the new call)
- **Files modified:** production/migrations/020_llm_calls_hypertable_fix.sql
- **Verification:** test_create_hypertable_no_if_not_exists PASSED
- **Committed in:** 428f175 (Task 1 commit)

**3. [Rule 3 - Blocking] Fixed pre-existing ruff errors in test_ai_narrative_service.py**
- **Found during:** Task 1 (full ruff check)
- **Issue:** test_ai_narrative_service.py had 4 ruff errors (3x F401 unused import, 1x I001 import sort) from prior plan work; blocked "ruff 0 errors" requirement
- **Fix:** `ruff check --fix` auto-removed dead `import json as _json` lines and sorted import block
- **Files modified:** tests/unit/service_tests/test_ai_narrative_service.py
- **Verification:** `ruff check .` — 0 errors; all 1172 unit tests still pass
- **Committed in:** 428f175 (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 3 - blocking)
**Impact on plan:** All auto-fixes necessary for correctness and passing criteria. No scope creep.

## Issues Encountered

- Plan template code used ambiguous variable name `l` in list comprehensions — ruff E741 in new test file. Fixed inline (renamed to `line`).
- Migration comment wording caused test false positive — comments referencing old behavior had "create_hypertable" and "if_not_exists" on same line, matching test pattern incorrectly. Fixed by rewording comments.

## User Setup Required

**Production DB migration requires manual docker exec.** Apply in your terminal:

```bash
cd /home/bg/dev/indicagent
docker exec -i timescaledb psql -U postgres -d indicagent < production/migrations/020_llm_calls_hypertable_fix.sql
```

Verify with:
```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT hypertable_name, num_dimensions FROM timescaledb_information.hypertables WHERE hypertable_name='llm_calls';"
```
Expected: one row — `llm_calls | 1`

## Next Phase Readiness

- Migration 020 file committed and tested — ready to apply to production
- After migration applied: `timescaledb_information.hypertables` will return one row for llm_calls
- llm_writer_service INSERT SQL unchanged — composite PK does not break existing writes
- Phase 16 gap closures (16-06, 16-07) complete after checkpoint passes

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-06*
