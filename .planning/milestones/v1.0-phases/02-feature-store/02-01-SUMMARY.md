---
phase: 02-feature-store
plan: 01
subsystem: database
tags: [timescaledb, postgresql, hypertable, jsonb, gin-index, compression, migrations]

# Dependency graph
requires:
  - phase: 01-typed-event-schema
    provides: IntelligenceEvent schema with tiered sub-models (bar, i1, i3, i4, i5, smc, i6) that define the column structure
provides:
  - intelligence_features hypertable with tiered JSONB columns and 7-day compression policy
  - 6 GIN indexes for per-tier JSONB queries (WHERE i4 @> '{"garch_vol_regime": 1}')
  - signal_ledger.feature_ts and signal_ledger.feature_tf nullable columns
  - Partial index idx_ledger_feature_ts enabling efficient JOIN lookups
affects:
  - 02-02 (feature_writer_service.py needs the intelligence_features table to write to)
  - 02-03 (signal_generator_service.py needs feature_ts/feature_tf columns in signal_ledger)
  - 05-ml-scoring (intelligence_features is the ML training data source; signal_ledger JOIN enables label extraction)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - TimescaleDB hypertable creation with 7-day chunk interval and compress_orderby=ASC
    - Tiered JSONB column design — one column per IntelligenceEvent sub-model for GIN-queryable per-tier queries
    - Nullable column addition to live hypertable via ALTER TABLE ADD COLUMN IF NOT EXISTS (no lock)
    - Partial index on nullable column (WHERE feature_ts IS NOT NULL) for post-migration rows only

key-files:
  created:
    - production/migrations/009_intelligence_features.sql
    - production/migrations/010_signal_ledger_feature_cols.sql
  modified: []

key-decisions:
  - "intelligence_features: NO retention policy — indefinite storage for seasonal ML analysis (design doc decision honored)"
  - "compress_orderby = 'ts ASC' — forward scan performance lesson from migration 007 applied"
  - "All JSONB tier columns NOT NULL DEFAULT '{}'::jsonb — GIN indexes safe, never encounter column-level NULL"
  - "feature_ts/feature_tf are nullable — historical signals before Phase 2 correctly have NULL values"

patterns-established:
  - "Tiered JSONB hypertable: tiered JSONB per sub-model + per-tier GIN indexes enables schema-less evolution of plugin outputs"
  - "Nullable FK-like columns: nullable feature_ts/feature_tf with partial index avoids NULL index bloat while enabling efficient post-Phase-2 lookups"

requirements-completed: [FST-01, FST-03, FST-04]

# Metrics
duration: 8min
completed: 2026-02-23
---

# Phase 2 Plan 01: Feature Store DB Migrations Summary

**intelligence_features TimescaleDB hypertable with tiered JSONB (bar/i1/i3/i4/i5/smc/i6), 6 GIN indexes, 7-day compression, no retention; signal_ledger gains nullable feature_ts/feature_tf JOIN columns**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-02-23T19:03:53Z
- **Completed:** 2026-02-23T19:11:00Z
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- intelligence_features hypertable created (hypertable_id=17) with 13 columns: ts, symbol, tf, platform, source, schema_version, bar, i1, i3, i4, i5, smc, i6
- 6 GIN indexes on all tiered JSONB columns plus composite index (symbol, tf, ts DESC) — 9 indexes total
- 7-day compression policy active (job_id=1015, Columnstore Policy) with compress_orderby='ts ASC' and compress_segmentby='symbol,tf'
- No retention policy — indefinite storage confirmed (0 retention jobs for intelligence_features)
- signal_ledger.feature_ts (TIMESTAMPTZ nullable) and signal_ledger.feature_tf (TEXT nullable) added
- Partial index idx_ledger_feature_ts(feature_ts) WHERE feature_ts IS NOT NULL created

## Task Commits

Each task was committed atomically:

1. **Task 1: Write migration 009 — intelligence_features hypertable** - `4b90b26` (feat)
2. **Task 2: Write migration 010 — signal_ledger feature_ts/feature_tf columns** - `cf08327` (feat)

**Plan metadata:** (docs commit — see final commit hash)

## Files Created/Modified

- `production/migrations/009_intelligence_features.sql` - intelligence_features hypertable DDL with tiered JSONB, GIN indexes, 7-day compression, no retention policy
- `production/migrations/010_signal_ledger_feature_cols.sql` - ALTER TABLE signal_ledger ADD COLUMN feature_ts/feature_tf (nullable) + partial index

## Decisions Made

- Kept design doc decision: no retention policy on intelligence_features for seasonal ML analysis
- Verified compress_orderby = 'ts ASC' — applied migration 007 lesson explicitly in migration comments
- JSONB columns NOT NULL DEFAULT '{}' to protect GIN indexes from column-level NULL (pitfall 3 from research)
- Columns nullable on signal_ledger: historical backfill signals will have NULL feature_ts/feature_tf — this is correct and expected

## Deviations from Plan

None - plan executed exactly as written.

**Note:** The plan's `must_haves` truth used `SELECT ... WHERE application_name LIKE '%intelligence_features%'` to find the compression job. In practice, TimescaleDB names compression jobs "Columnstore Policy [N]" and stores the hypertable name in a separate column. The query `WHERE hypertable_name='intelligence_features'` correctly identifies job 1015 with `compress_after: "7 days"`. The compression policy is confirmed active.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Migrations are applied to the local PostgreSQL instance.

## Next Phase Readiness

- intelligence_features hypertable ready to receive rows from feature_writer_service.py (Phase 2 Plan 02)
- signal_ledger.feature_ts/feature_tf ready for population by signal_generator_service.py (Phase 2 Plan 03)
- All Phase 2 schema prerequisites confirmed met via verification queries

---
*Phase: 02-feature-store*
*Completed: 2026-02-23*

## Self-Check: PASSED

- FOUND: production/migrations/009_intelligence_features.sql
- FOUND: production/migrations/010_signal_ledger_feature_cols.sql
- FOUND: .planning/phases/02-feature-store/02-01-SUMMARY.md
- FOUND commit: 4b90b26 (feat(02-01): intelligence_features hypertable migration 009)
- FOUND commit: cf08327 (feat(02-01): signal_ledger feature_ts/feature_tf columns migration 010)
