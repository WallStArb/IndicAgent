---
phase: 039-data-quality-db-health
plan: 03
subsystem: database
tags: [timescaledb, hypertable, psycopg2, migration, index, ohlcv, signal_ledger]

requires:
  - phase: 039-02
    provides: CIS null repair script (repair_cis_nulls.py) — connect_db() pattern reused here

provides:
  - rebuild_ohlcv.py script: rebuild market_data_ohlcv with 7-day chunks, reduces ~15,740 chunks to < 200
  - verify_v2_ready() gate: chunk_count < 200 AND benchmark latency < 500ms — exits 1 on failure
  - 043_signal_ledger_lifecycle_index.sql: CONCURRENTLY composite index for lifecycle UPDATEs

affects: [040-machine-hardening, 046-ml-model]

tech-stack:
  added: []
  patterns:
    - "Idempotent hypertable rebuild: CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING + IF NOT EXISTS everywhere"
    - "Verification gate pattern: pure function returning (bool, dict) with failure reason — testable without DB"
    - "CONCURRENTLY index delivered via psql -c (not psql -f) to avoid implicit transaction wrapping"

key-files:
  created:
    - production/scripts/rebuild_ohlcv.py
    - tests/unit/scripts/test_rebuild_ohlcv.py
    - production/migrations/043_signal_ledger_lifecycle_index.sql
  modified: []

key-decisions:
  - "Migration file numbered 043 (not 040 as planned) — 040/041/042 were added during Phase 39.1 while plan was written"
  - "verify_v2_ready() is a pure function taking a connection: enables unit testing without live DB"
  - "7-day chunk interval reduces chunk count from ~15,740 to < 200 (~40x reduction) for market_data_ohlcv"
  - "ON CONFLICT DO NOTHING on (symbol, timeframe, timestamp) unique key makes copy fully restartable"
  - "Old table preserved as market_data_ohlcv_old — never dropped (Renaissance: never drop data)"

patterns-established:
  - "Verification gate: pure function (conn) -> (bool, dict) with specific reason string — parallel to repair_cis_nulls audit pattern"
  - "connect_db() reused from repair_cis_nulls.py — canonical psycopg2 Settings URL parser"

requirements-completed: [DATA-03, DATA-04]

duration: 7min
completed: 2026-03-19
---

# Phase 039 Plan 03: OHLCV Rebuild + Signal Ledger Index Summary

**OHLCV hypertable rebuild script with chunk-count/latency verification gate and signal_ledger composite index migration for lifecycle UPDATE performance**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-19T23:02:36Z
- **Completed:** 2026-03-19T23:09:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `rebuild_ohlcv.py` creates market_data_ohlcv_v2 with 7-day chunks, copies data in 30-day batches (ON CONFLICT DO NOTHING), runs verify_v2_ready() gate, then renames atomically — exits 1 if gate fails
- `verify_v2_ready()` is a pure function: chunk_count < 200 AND aggregate benchmark < 500ms — 6 unit tests cover chunk gate, latency gate, boundary conditions (200 exact, 500ms exact), and pass case
- Migration 043 documents `CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_lifecycle ON signal_ledger (symbol, timeframe, status, computed_at DESC)` with `psql -c` delivery instruction (CONCURRENTLY cannot run in a transaction)

## Task Commits

Each task was committed atomically:

1. **Task 1: rebuild_ohlcv.py + tests** - `dd36113` (feat)
2. **Task 2: signal_ledger lifecycle index migration** - `c1b7bd9` (feat)

**Plan metadata:** (this commit)

## Files Created/Modified

- `production/scripts/rebuild_ohlcv.py` - Full hypertable rebuild script with create_v2_table(), copy_data(), verify_v2_ready(), atomic_rename(), --dry-run flag
- `tests/unit/scripts/test_rebuild_ohlcv.py` - 6 unit tests for verify_v2_ready() pure function
- `production/migrations/043_signal_ledger_lifecycle_index.sql` - CONCURRENTLY composite index DDL + delivery instructions

## Decisions Made

- Migration numbered 043 not 040 as planned — 040, 041, 042 were added during Phase 39.1 while this plan was authored; renamed to prevent file collision.
- `verify_v2_ready()` designed as a pure function accepting a DB connection (not a method) — makes unit testing straightforward without live TimescaleDB.
- Old table preserved as `market_data_ohlcv_old` after rename — consistent with Renaissance principle of never dropping data that might have signal value.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration file number changed from 040 to 043**
- **Found during:** Task 2 (migration file creation)
- **Issue:** Plan specified `040_signal_ledger_lifecycle_index.sql` but `040_signal_ledger_outcome_check_constraint.sql`, `041_signal_ledger_schema_hardening.sql`, and `042_signal_stats_daily.sql` were added during Phase 39.1 (after this plan was written)
- **Fix:** Used next available number: `043_signal_ledger_lifecycle_index.sql`
- **Files modified:** `production/migrations/043_signal_ledger_lifecycle_index.sql`
- **Verification:** File exists, contains all required DDL and delivery instructions
- **Committed in:** c1b7bd9 (Task 2 commit)

**2. [Rule 1 - Bug] Removed unused `import time` from test file**
- **Found during:** Task 1 commit (pre-commit hook caught it)
- **Issue:** `import time` was included in test file but not used — pre-commit F401 check blocked commit
- **Fix:** Removed the unused import
- **Files modified:** `tests/unit/scripts/test_rebuild_ohlcv.py`
- **Verification:** Pre-commit passed, all 6 tests still pass

---

**Total deviations:** 2 auto-fixed (1 naming collision, 1 unused import)
**Impact on plan:** Both auto-fixes were mechanical corrections, zero scope creep.

## Issues Encountered

None — plan executed cleanly after the two minor auto-fixes.

## User Setup Required

**Manual steps required to apply the changes:**

1. **Run rebuild_ohlcv.py (dry-run first):**
   ```bash
   INDICAGENT_ENV=development .venv/bin/python production/scripts/rebuild_ohlcv.py --dry-run
   # Verify gate passes, then run without --dry-run
   INDICAGENT_ENV=development .venv/bin/python production/scripts/rebuild_ohlcv.py
   ```

2. **Apply signal_ledger index (run on live system — CONCURRENTLY, no lock):**
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent \
       -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_lifecycle \
           ON signal_ledger (symbol, timeframe, status, computed_at DESC);"
   ```

## Next Phase Readiness

- OHLCV rebuild script is ready to run — use `--dry-run` first to verify chunk count and latency targets before committing the rename
- Signal ledger index is ready to apply — CONCURRENTLY is safe on a live system with no table lock
- DATA-03 and DATA-04 requirements are scripted; production application is a manual operator step

---
*Phase: 039-data-quality-db-health*
*Completed: 2026-03-19*
