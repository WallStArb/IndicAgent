---
phase: 13-data-completeness
plan: 01
subsystem: database
tags: [timescaledb, postgresql, redis, streams, migration, intelligence-features]

# Dependency graph
requires:
  - phase: 12-signal-integrity
    provides: signal_ledger shadow signals, regime-gating — Phase 13 enriches the feature store these depend on
provides:
  - intelligence_features table with i7 JSONB column (all_ranked signals per bar, default '[]')
  - intelligence_features table with i8 JSONB column (narrative metadata per bar, default '{}')
  - intelligence_features table with days_to_expiry INTEGER column (nullable)
  - GIN indexes on i7 and i8 for JSONB field queries
  - intelligence_i7() and intelligence_i8() stream key constructors
  - intelligence_i7_pattern() and intelligence_i8_pattern() wildcard helpers
  - get_stream_maxlen() support for 'intelligence_i7' and 'intelligence_i8' (returns 200)
affects: [13-02-PLAN, 13-03-PLAN, 13-04-PLAN, feature_writer_service, signal_generator_service, ai_narrative_service]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Enrichment stream pattern: {env}intelligence_i7:{symbol}:{tf} for async i7 backfill"
    - "GIN index on JSONB column: consistent with i1-i6 pattern in intelligence_features"
    - "Additive-only migration: IF NOT EXISTS on all DDL for idempotent re-run safety"

key-files:
  created:
    - production/migrations/018_data_completeness.sql
  modified:
    - src/core/stream_keys.py

key-decisions:
  - "i7 default '[]' not '{}' — empty list semantics (no signals fired) vs empty object"
  - "days_to_expiry nullable — NULL is honest for pre-migration rows; feature_writer sets value on new writes"
  - "intelligence_i7/i8 stream maxlen=200 — enough backpressure buffer without excessive DragonflyDB memory"

patterns-established:
  - "Enrichment stream naming: intelligence_i7:{symbol}:{tf} and intelligence_i8:{symbol}:{tf}"
  - "New stream kinds extend get_stream_maxlen() Literal union — type-safe at call site"

requirements-completed: [DATA-01, DATA-02, DATA-03, DATA-04]

# Metrics
duration: 3min
completed: 2026-03-05
---

# Phase 13 Plan 01: Data Completeness Foundation Summary

**DB migration adds i7/i8/days_to_expiry columns with GIN indexes to intelligence_features; stream_keys.py exports intelligence_i7/i8 constructors and maxlen=200 policy**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-05T09:57:57Z
- **Completed:** 2026-03-05T10:00:36Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Migration 018 applied: i7 JSONB NOT NULL DEFAULT '[]', i8 JSONB NOT NULL DEFAULT '{}', days_to_expiry INTEGER nullable — all with IF NOT EXISTS for idempotent re-run
- Two GIN indexes created (idx_intel_features_i7_gin, idx_intel_features_i8_gin) consistent with i1-i6 pattern
- Four new functions in stream_keys.py: intelligence_i7(), intelligence_i8(), intelligence_i7_pattern(), intelligence_i8_pattern()
- get_stream_maxlen() Literal union extended to include 'intelligence_i7' and 'intelligence_i8' (both return 200)
- 1117 unit tests pass, ruff 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Add i7, i8, days_to_expiry columns via migration** - `66a970b` (feat)
2. **Task 2: Add intelligence_i7/i8 stream key constructors** - `7058694` (feat)

## Files Created/Modified
- `production/migrations/018_data_completeness.sql` - Additive-only DDL: three ALTER TABLE ADD COLUMN IF NOT EXISTS, two CREATE INDEX IF NOT EXISTS, three COMMENT ON COLUMN
- `src/core/stream_keys.py` - Four new key constructors + two new get_stream_maxlen() cases

## Decisions Made
- i7 defaults to '[]' (empty JSON array) not '{}': semantically correct — an empty list means "no signals fired for this bar" vs an empty object which is the i8 pattern
- days_to_expiry is nullable with no DEFAULT: NULL is honest for pre-migration rows; feature_writer_service will set 0 for non-futures and computed days for futures on new writes
- Stream maxlen=200 for intelligence_i7/i8: backpressure buffer sized for the async enrichment pattern (signal_generator publishes after each bar close; AI narrative is sparse)

## Deviations from Plan

**Rule 3 - Blocking: sudo -u postgres approach failed** — `sudo-rs` on this system does not have a 'postgres' OS user. Resolved by using `docker exec timescaledb psql` instead (the migration workspace volume `/workspace` maps to `production/`). Migration applied successfully via the container.

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking infra issue)
**Impact on plan:** No scope change. Identical DDL executed via the container rather than host sudo.

## Issues Encountered
- `echo '***REDACTED-SUDO-PASSWORD***' | sudo -S -u postgres psql` failed with "user 'postgres' not found" — PostgreSQL runs inside Docker (timescaledb container), not as a local OS user. Used `docker exec timescaledb psql` with the workspace volume mount instead.

## Next Phase Readiness
- DB foundation complete: all downstream plans (13-02, 13-03, 13-04) can import intelligence_i7/intelligence_i8 stream key functions
- feature_writer_service can UPSERT i7/i8/days_to_expiry once Plans 02-04 add the write logic
- No blockers for Phase 13 continuation

---
*Phase: 13-data-completeness*
*Completed: 2026-03-05*
