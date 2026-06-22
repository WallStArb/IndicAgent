---
phase: 138-ic-engine-forward-returns
plan: "03"
subsystem: database
tags: [feature_vectors, backfill, psycopg2, uuid, feature_factory]

requires:
  - phase: "138-01"
    provides: "feature_vector_persistence module, FEATURE_VECTOR_INSERT_SQL_PSYCOPG2, 70-column schema"
provides:
  - "backfill_feature_factory running with UUID bug fixed; feature_vectors populating with correct data"
  - "136 (symbol,tf) pairs seeded in backfill_status with fetch_complete=true"
  - "psycopg2.extras.register_uuid() registered in _connect_db — prerequisite for all future psycopg2 UUID writes"
affects: ["138-04", "138-05", "138-06", "138-07"]

tech-stack:
  added: []
  patterns:
    - "psycopg2 UUID adapter registration: call psycopg2.extras.register_uuid() after connect() for any service writing UUID columns"
    - "backfill_status pre-seeding: when OHLCV pre-populated outside fetch stage, INSERT with fetch_complete=true before --compute-only"

key-files:
  created: []
  modified:
    - "services/backfill_feature_factory.py"

key-decisions:
  - "psycopg2.extras.register_uuid() added to _connect_db — eliminates UUID type adapter gap without changing persistence contract"
  - "Pre-seeded backfill_status with fetch_complete=true for 136 existing OHLCV pairs; avoids fetch stage re-run for already-populated data"
  - "Backfill left running in background after 90-minute SUMMARY cutoff; P4/P5 cannot start until coverage is sufficient"

patterns-established:
  - "backfill_status pre-seeding pattern: when using --compute-only on pre-existing OHLCV, INSERT fetch_complete=true for each (symbol,tf) pair in market_data_ohlcv"

requirements-completed: []

duration: partial (90-min cutoff; backfill continues in background)
completed: 2026-06-22
---

# Phase 138 Plan 03: FeatureFactory Backfill Summary

**PARTIAL COMPLETION - backfill started and running; UUID bug fixed; 4000 rows written for VUG/1h; full corpus requires ~20-30h continued compute**

## Performance

- **Duration:** Cutoff at 90 minutes (plan timeout applied)
- **Started:** 2026-06-22T18:42:57Z
- **Completed:** 2026-06-22T20:12:57Z (cutoff; backfill continues in background)
- **Tasks:** 1 of 1 (partial - acceptance criteria not met within window)
- **Files modified:** 1 (services/backfill_feature_factory.py - UUID bug fix)

## Accomplishments

- Discovered and fixed critical bug: psycopg2 `can't adapt type 'UUID'` error blocked all feature_vectors writes
- Pre-seeded `backfill_status` with `fetch_complete=true` for 136 (symbol,tf) pairs that already had OHLCV data
- Backfill process running and writing correct data: 4000 rows for VUG/1h with all P1 fields non-NULL
- Verified write quality: `feature_factory_version='1.0.0'`, all 8 new P1 columns non-NULL (bar_close_ts, momentum_z_slow, momentum_reversal_z, quarter_position, days_to_month_end, feature_vector_id)
- Process remains running (PID 589865) at 100% CPU; idempotent and resumable via backfill_status checkpoints

## Task Commits

1. **Task 1: Run FeatureFactory backfill** - `6de8f2d8` (fix: UUID adapter for psycopg2)

## Files Created/Modified

- `services/backfill_feature_factory.py` - Added `psycopg2.extras.register_uuid()` call in `_connect_db()`

## Decisions Made

- `register_uuid()` placed in `_connect_db()` rather than in `feature_vector_persistence.py` because the persistence module is shared by asyncpg callers that do NOT need it; the fix is correctly scoped to the psycopg2-only code path
- 136 `backfill_status` rows pre-seeded with `fetch_complete=true` to allow `--compute-only` to proceed on pre-existing OHLCV without re-fetching from IBKR
- Backfill left running in background after summary cutoff; it is idempotent and will continue writing to feature_vectors

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] psycopg2 UUID adapter not registered causing all writes to fail**
- **Found during:** Task 1 (Run FeatureFactory backfill)
- **Issue:** `backfill_feature_factory._connect_db()` did not call `psycopg2.extras.register_uuid()`. psycopg2 cannot serialize `uuid.UUID` objects without this adapter. Every (symbol, tf) batch failed on the first INSERT with `can't adapt type 'UUID'`, writing 0 rows.
- **Fix:** Added `psycopg2.extras.register_uuid()` after `psycopg2.connect()` in `_connect_db()`
- **Files modified:** `services/backfill_feature_factory.py`
- **Verification:** Subsequent run writes rows correctly; VUG/1h accumulating rows at expected rate; all P1 fields non-NULL
- **Committed in:** `6de8f2d8`

**2. [Rule 3 - Blocking] backfill_status empty - compute-only stage skipped all pairs**
- **Found during:** Task 1 (first --compute-only run)
- **Issue:** `--compute-only` requires `backfill_status.fetch_complete=true` per pair. Since OHLCV was pre-populated by `run_historical_pipeline.py` (not through the backfill fetch stage), `backfill_status` was empty. The compute loop issued `compute_skip_no_fetch` for all 136 pairs and wrote 0 rows.
- **Fix:** Ran `INSERT INTO backfill_status SELECT DISTINCT symbol, timeframe, true, 'pending', NOW() FROM market_data_ohlcv WHERE timeframe IN ('5m','15m','1h','1d') ON CONFLICT DO UPDATE SET fetch_complete=true` to pre-seed 136 pairs
- **Verification:** `SELECT count(*) FROM backfill_status WHERE fetch_complete=true` returns 136; subsequent run began computing
- **No source file change:** DB-only fix

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking)
**Impact on plan:** Both fixes were necessary to get any rows into feature_vectors. No scope creep.

## Issues Encountered

**Critical: FeatureFactory compute performance is much slower than RESEARCH.md estimated**

RESEARCH.md estimated "2-6 hours for 14 symbols x 4 TFs". Benchmarking revealed:
- `FeatureFactory.compute()` processes ~45 bars/second with 200-bar windows
- Actual backfill uses 2000-bar sliding windows (10x larger), reducing throughput to ~3-5 bars/second for 1h bars
- VUG/1h alone (131K bars) requires ~7-11 hours to compute
- Full 136-pair backfill (42 symbols x up to 4 TFs) estimated at 20-30 hours total

Root cause: `_atr_wilder()` is called 252 times per bar inside a list comprehension (lines 803-809 of feature_factory.py), each call O(window_length). Combined with a 2000-bar window, this is O(252 * 2000) = O(504K) operations per bar.

**This is not a P3 deviation to fix** - performance optimization is out of scope for this operational plan. However, it has significant implications:

- P4 (regime_writer) and P5 (forward_return_writer) CANNOT start until feature_vectors has sufficient coverage
- The backfill process (PID 589865) is running and will continue accumulating rows
- Each session restart should check backfill_status for progress and resume from where it left off

## Data Quality Verification (existing rows)

```sql
-- Verified on 4000 VUG/1h rows as of cutoff
SELECT 
  count(*) as total,                               -- 4000
  count(*) FILTER (WHERE feature_factory_version IS NOT NULL),  -- 4000 (='1.0.0')
  count(*) FILTER (WHERE bar_close_ts IS NOT NULL),             -- 4000
  count(*) FILTER (WHERE momentum_z_slow IS NOT NULL),          -- 4000
  count(*) FILTER (WHERE momentum_reversal_z IS NOT NULL),      -- 4000
  count(*) FILTER (WHERE quarter_position IS NOT NULL),         -- 4000
  count(*) FILTER (WHERE days_to_month_end IS NOT NULL),        -- 4000
  count(*) FILTER (WHERE feature_vector_id IS NOT NULL)         -- 4000
FROM feature_vectors;
```

All P1 fields are 100% populated. Data quality is correct; only quantity is insufficient.

## Current State at Cutoff

| Metric | Value |
|--------|-------|
| feature_vectors total rows | 4,000 |
| Distinct symbols | 1 (VUG) |
| Distinct TFs | 1 (1h) |
| In-progress | VUG/1h |
| Complete pairs | 0 |
| Pending pairs | 135 |
| Backfill process | Running (PID 589865, 100% CPU) |

## Acceptance Criteria Status

| Criterion | Status |
|-----------|--------|
| >= 14 distinct symbols | NOT MET (1 of 14) |
| 4 TFs represented | NOT MET (1 of 4) |
| SPY 5m > 50K rows | NOT MET (0 rows) |
| feature_factory_version non-NULL | MET (for existing rows) |
| bar_close_ts non-NULL | MET (for existing rows) |
| P1 fields non-NULL | MET (for existing rows) |
| D-06 emitted | NOT MET (process still running) |

## Next Phase Readiness

**P4 (regime_writer) and P5 (forward_return_writer) are BLOCKED until backfill completes.**

When resuming this work in a future session:
1. Check backfill progress: `SELECT tf, count(DISTINCT symbol), count(*) FROM feature_vectors GROUP BY tf;`
2. Check what's still pending: `SELECT tf, count(*) FROM backfill_status WHERE status='pending' GROUP BY tf;`
3. If process died, restart: `cd /home/bg/dev/indicagent && nohup .venv/bin/python services/backfill_feature_factory.py --compute-only > logs/backfill_feature_factory.log 2>&1 &`
4. The backfill is idempotent - already-complete (symbol,tf) pairs are skipped via `backfill_status.status='complete'`

Minimum viable state for P4/P5 to start: feature_vectors populated for SPY + IWM + TLT across 5m/15m/1h/1d (est. 4 pairs x 131K rows each = ~44K rows minimum for IC gate validation).

## Self-Check

- [x] SUMMARY.md created at correct path
- [x] Bug fix committed: `6de8f2d8`
- [x] backfill process still running (verified via ps, 100% CPU, PID 589865)
- [x] feature_vectors has 4000 rows with correct data quality

## Self-Check: PASSED

All committed artifacts present. Partial completion documented honestly. Backfill continues in background.

---
*Phase: 138-ic-engine-forward-returns*
*Completed: 2026-06-22 (partial - see Issues Encountered)*
