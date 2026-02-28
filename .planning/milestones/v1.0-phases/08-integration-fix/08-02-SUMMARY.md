---
phase: 08-integration-fix
plan: 02
subsystem: database
tags: [psycopg2, signal-ledger, backfill, cis, sql]

# Dependency graph
requires:
  - phase: 07-composite-intelligence-score
    provides: "CIS columns (cis_score, bucket_scores, weights_version, signal_quality) added to signal_ledger via migration 011"
provides:
  - "_INSERT_SYNC_SQL in historical_backfill.py updated to 28 columns including all CIS fields"
  - "Backfill can now run against Phase 7 signal_ledger schema without column mismatch"
affects: [08-integration-fix, historical-backfill, signal-ledger]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Backfill INSERT SQL mirrors signal_ledger._INSERT_SQL column list — update both when schema changes"
    - "Backfill passes NULL for CIS columns — live pipeline populates them via CIS aggregator at fire time"

key-files:
  created: []
  modified:
    - production/scripts/historical_backfill.py
    - tests/unit/test_historical_backfill.py

key-decisions:
  - "08-02: backfill SQL updated to 28 columns to match Phase 7 signal_ledger schema; NULL passed for all 4 CIS fields"
  - "08-02: _insert_signals_sync builds params inline (not via to_insert_params()) — both SQL and params updated together"

patterns-established:
  - "Keep _INSERT_SYNC_SQL in historical_backfill.py column-count-balanced with signal_ledger._INSERT_SQL at all times"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-02-28
---

# Phase 08 Plan 02: Backfill SQL CIS Column Update Summary

**_INSERT_SYNC_SQL updated from 24 to 28 columns with cis_score, bucket_scores, weights_version, signal_quality — NULL-passthrough for backfill rows, 3 new tests, 787 passing**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-28T13:01:33Z
- **Completed:** 2026-02-28T13:06:00Z
- **Tasks:** 2 (1 read/analysis + 1 TDD)
- **Files modified:** 2

## Accomplishments

- Updated `_INSERT_SYNC_SQL` from 24 columns to 28 to match the Phase 7 `signal_ledger` schema (cis_score, bucket_scores, weights_version, signal_quality)
- Updated `_insert_signals_sync()` to pass `None` for all 4 CIS params — backfill rows correctly insert NULL for CIS data that only exists in live pipeline signals
- Added 3 TDD tests: SQL has CIS columns, column/placeholder balance, NULL passthrough in param tuple

## Task Commits

Each task was committed atomically:

1. **Task 1: Read current backfill SQL and LedgerEntry structure** - (analysis only, no commit — read-only task)
2. **Task 2: TDD — update _INSERT_SYNC_SQL and params for CIS columns** - `b21b446` (feat)

## Files Created/Modified

- `/home/bg/dev/indicagent/production/scripts/historical_backfill.py` - `_INSERT_SYNC_SQL` expanded to 28 columns; `_insert_signals_sync()` params now include 4 trailing `None` values for CIS fields
- `/home/bg/dev/indicagent/tests/unit/test_historical_backfill.py` - Added `TestCISColumnsInSQL` with 3 tests verifying SQL content, column/placeholder balance, and NULL param passthrough

## Decisions Made

- `_insert_signals_sync()` builds params inline rather than delegating to `LedgerEntry.to_insert_params()`. Both the SQL and the inline params tuple were updated together to maintain alignment.
- Backfill always passes `None` for CIS columns — live signals receive CIS values from the CIS aggregator at fire time; backfill replay does not run the CIS aggregator.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-existing E501 violations (6 lines) and E741 (`l` variable) in backfill script and test file — all pre-existing, out of scope per scope boundary rule. Not fixed, not re-introduced.

## Next Phase Readiness

- Historical backfill can now run `--replay-only` against the Phase 7 schema without column mismatch errors
- All 787 unit tests passing; backfill SQL is now aligned with `signal_ledger._INSERT_SQL` (28 columns each)

---
*Phase: 08-integration-fix*
*Completed: 2026-02-28*

## Self-Check: PASSED

- FOUND: `.planning/phases/08-integration-fix/08-02-SUMMARY.md`
- FOUND: `production/scripts/historical_backfill.py`
- FOUND: `tests/unit/test_historical_backfill.py`
- FOUND: commit `b21b446`
