---
phase: 039-data-quality-db-health
plan: 01
subsystem: database
tags: [timescaledb, signal_ledger, generated-columns, check-constraints, materialized-view, sql-migration]

# Dependency graph
requires:
  - phase: 039.1-intelligence-layer-enforcement
    provides: SignalStatus enum with 'pending', 'active', 'regime_suppressed' values
provides:
  - signal_ledger.effective_ts column (COALESCE(signal_computed_at, feature_ts) via trigger)
  - signal_ledger.pipeline_lag_ms column (epoch ms latency, NULL for pending)
  - chk_signal_ledger_status CHECK constraint (pending/active/regime_suppressed/expired)
  - chk_signal_ledger_direction CHECK constraint (direction IN (-1, 1))
  - signal_stats_daily materialized view (33,859 rows on creation)
  - idx_signal_ledger_effective_ts index on (symbol, timeframe, effective_ts DESC)
affects: [phase-40-machine-hardening, phase-46-ml-model, signals-api, signal-lifecycle]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Trigger-based derived columns instead of GENERATED ALWAYS AS (TimescaleDB compression incompatibility)"
    - "Inline summary computation in FastAPI route — no separate fetchrow needed"

key-files:
  created:
    - production/migrations/041_signal_ledger_schema_hardening.sql
    - production/migrations/042_signal_stats_daily.sql
  modified:
    - src/api/routes/signals.py
    - tests/unit/api_tests/test_signals_routes.py

key-decisions:
  - "Trigger approach for effective_ts and pipeline_lag_ms — GENERATED ALWAYS AS STORED is incompatible with TimescaleDB compressed hypertables"
  - "status CHECK allows 'expired' in addition to the 3 SignalStatus enum values — legacy data uses 'expired' as terminal state"
  - "direction CHECK uses smallint values (-1, 1) not text ('LONG', 'SHORT') — actual column is smallint"
  - "signal_stats_daily uses feature_ts for date grouping (not effective_ts) for consistency with existing analytics"

patterns-established:
  - "effective_ts is the canonical ordering column for signal_ledger — use ORDER BY sl.effective_ts DESC everywhere"
  - "Summary block in /api/signals/recent is computed inline from fetched rows, not from a separate DB query"

requirements-completed: [DATA-08, DATA-09, DATA-10]

# Metrics
duration: 4min
completed: 2026-03-19
---

# Phase 039 Plan 01: Signal Ledger Schema Hardening Summary

**signal_ledger enriched with effective_ts trigger column, pipeline_lag_ms latency instrumentation, two CHECK constraints, and signal_stats_daily materialized view (33,859 rows) for fast IC computation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-19T23:02:09Z
- **Completed:** 2026-03-19T23:06:09Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments

- Applied idempotent migration 041 adding effective_ts and pipeline_lag_ms via BEFORE INSERT OR UPDATE trigger (generated columns unsupported with TimescaleDB compression — trigger approach used instead)
- Applied idempotent migration 042 creating signal_stats_daily materialized view with 33,859 rows and unique index for IC queries
- Replaced all COALESCE(signal_computed_at, feature_ts) in signals.py ORDER BY with sl.effective_ts — enables index-scan via idx_signal_ledger_effective_ts
- Fixed pre-existing test failures where test_summary_block_fields used fetchrow mock for a summary now computed inline from fetch rows

## Task Commits

Each task was committed atomically:

1. **Task 1-2: Schema inspection + migration** - `5f1b088` (feat)
2. **Task 4: signals.py effective_ts update + test fix** - `84a5758` (feat)

Note: Task 3 (effective_ts index + signal_stats_daily) was applied to the database directly — the 042 migration was included in commit 5f1b088.

## Files Created/Modified

- `production/migrations/041_signal_ledger_schema_hardening.sql` - effective_ts/pipeline_lag_ms columns, CHECK constraints, BEFORE INSERT OR UPDATE trigger, backfill
- `production/migrations/042_signal_stats_daily.sql` - signal_stats_daily materialized view with 3 indexes
- `src/api/routes/signals.py` - ORDER BY sl.effective_ts DESC (was COALESCE), SELECT sl.effective_ts AS signal_computed_at
- `tests/unit/api_tests/test_signals_routes.py` - Updated summary tests to provide actual signal_rows (summary computed inline, not via fetchrow)

## Decisions Made

1. **Trigger approach for derived columns**: TimescaleDB compressed hypertables do not support GENERATED ALWAYS AS STORED columns (ALTER TABLE fails). Used BEFORE INSERT OR UPDATE trigger instead. Both approaches produce identical semantics.

2. **status CHECK includes 'expired'**: Historical signal_ledger rows use 'expired' as a legacy terminal status. The constraint allows it alongside the 3 current SignalStatus enum values to avoid breaking the backfill.

3. **direction CHECK on smallint**: The plan described direction as text ('LONG'/'SHORT'), but the actual column is smallint. Constraint correctly uses (-1, 1) matching the actual schema.

## Schema Verification

All success criteria confirmed:
- `effective_ts` and `pipeline_lag_ms` columns exist (timestamptz, double precision)
- `chk_signal_ledger_status` and `chk_signal_ledger_direction` CHECK constraints exist
- `signal_stats_daily` materialized view: **33,859 rows**
- `idx_signal_ledger_effective_ts` index on (symbol, timeframe, effective_ts DESC)
- EXPLAIN ANALYZE confirms Index Scan using `_hyper_13_*_idx_signal_ledger_effective_ts` for symbol+timeframe queries
- `grep "effective_ts" src/api/routes/signals.py` confirms ORDER BY usage; no COALESCE in ORDER BY

## Pipeline Lag Instrumentation (Renaissance Principle)

The `pipeline_lag_ms` column instruments the latency between bar close (`feature_ts`) and signal computation (`signal_computed_at`) at the row level. P95 pipeline lag can now be computed directly from the table:
```sql
SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pipeline_lag_ms)
FROM signal_ledger WHERE pipeline_lag_ms IS NOT NULL;
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Trigger approach required instead of GENERATED ALWAYS AS STORED**
- **Found during:** Task 2 (migration creation)
- **Issue:** TimescaleDB compressed hypertables reject GENERATED ALWAYS AS STORED columns — ALTER TABLE fails with unsupported operation error
- **Fix:** Implemented BEFORE INSERT OR UPDATE trigger + backfill UPDATE for existing rows; semantically identical
- **Files modified:** production/migrations/041_signal_ledger_schema_hardening.sql
- **Committed in:** 5f1b088

**2. [Rule 1 - Bug] Fixed test_summary_block_fields using wrong mock pattern**
- **Found during:** Task 4 (test verification)
- **Issue:** Test provided fetchrow mock for summary data, but get_recent_signals computes summary inline from fetch rows — fetchrow is never called
- **Fix:** Rewrote test to provide actual signal_rows (7 expired + 2 regime_suppressed + 1 pending) that produce the expected summary values; updated test_summary_win_rate_and_avg_pnl_r_null_when_no_data similarly
- **Files modified:** tests/unit/api_tests/test_signals_routes.py
- **Committed in:** 84a5758

---

**Total deviations:** 2 auto-fixed (1 blocking schema issue, 1 test correctness)
**Impact on plan:** Both fixes necessary for correctness. No scope creep. All plan objectives achieved.

## Issues Encountered

- Pre-existing ai_narrative test failures (18 failures) confirmed pre-existing on main branch — out of scope for this plan

## Self-Check

- [x] effective_ts column exists in signal_ledger
- [x] pipeline_lag_ms column exists in signal_ledger
- [x] chk_signal_ledger_status constraint exists
- [x] chk_signal_ledger_direction constraint exists
- [x] signal_stats_daily view exists with 33,859 rows
- [x] signals.py ORDER BY uses sl.effective_ts DESC (confirmed by grep)
- [x] All signals route unit tests pass (17/17)
- [x] Commits 5f1b088 and 84a5758 exist on main

## Self-Check: PASSED

## Next Phase Readiness

- `effective_ts` column is ready for Phase 40 queries and lifecycle UPDATE patterns
- `pipeline_lag_ms` enables P95 latency monitoring for machine hardening (Phase 40)
- `signal_stats_daily` provides win-rate aggregations for IC computation (Plan 05)
- All migrations are idempotent — safe to re-apply

---
*Phase: 039-data-quality-db-health*
*Completed: 2026-03-19*
