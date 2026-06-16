---
phase: 128-3-table-schema-design-and-adr
plan: "02"
subsystem: database
tags: [timescaledb, postgresql, migrations, schema, signal-architecture, hypertable]

# Dependency graph
requires:
  - phase: 128-3-table-schema-design-and-adr
    provides: "CONTEXT.md with locked schema decisions D-02/D-03/D-04/D-05 and RESEARCH.md with live hypertable config"
provides:
  - "production/migrations/137_3table_schema.sql: complete runnable DDL for 3-table signal architecture"
  - "signal_events hypertable with composite PK, compression policy, and 8 btree indexes"
  - "trade_frames regular table with composite FK anchored to hypertable PK via signal_ts denormalization"
  - "trade_executions regular table with FK to trade_frames"
  - "signal_ledger_full view as backward-compat join surface across all three tables"
affects:
  - "128-03-PLAN (ADR authoring)"
  - "Phase 129 (migration executor reads this file verbatim)"
  - "Phase 130 (signal writer must produce signal_ts on every trade_frames row for FK)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Hypertable FK pattern: FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts) — required because hypertable composite PK includes partition dimension"
    - "Compression segmentby on NOT NULL columns only (symbol, timeframe both NOT NULL per Pitfall 2)"
    - "IF NOT EXISTS guards on all CREATE TABLE and CREATE INDEX for idempotency"
    - "CREATE OR REPLACE VIEW for view upsert idempotency"
    - "add_compression_policy called after ALTER TABLE SET timescaledb.compress"

key-files:
  created:
    - production/migrations/137_3table_schema.sql
  modified: []

key-decisions:
  - "signal_ledger_full view name (not signal_ledger_v2) per CLAUDE.md Phase 128 canonical name; CONTEXT.md D-05 SQL content used verbatim, view name aligned to success criteria"
  - "signal_ts as first-class column on trade_frames is a FK anchor requirement, not convenience denormalization — single-column FK to hypertable composite PK is a PostgreSQL constraint violation"
  - "No GIN indexes in Phase 128 DDL — deferred per CONTEXT.md until ML training query patterns are observed"
  - "IF NOT EXISTS guards throughout — migration runner applies each migration once but idempotency guards prevent re-run failures"
  - "signal_ledger NOT dropped in this migration — Phase 129 owns the data migration and DROP"
  - "created_at DEFAULT now() is DB insertion time; signal_computed_at is pipeline wall-clock from payload — both on signal_events, both nullable except created_at"

patterns-established:
  - "Hypertable creation: CREATE TABLE -> create_hypertable -> ADD PRIMARY KEY (composite with ts) -> SET compression -> add_compression_policy"
  - "Composite FK to hypertable: carrier table holds denormalized time column (signal_ts) to satisfy FK referencing composite PK"

requirements-completed:
  - ARCH-01

# Metrics
duration: 15min
completed: 2026-06-15
---

# Phase 128 Plan 02: 3-Table DDL Migration Summary

**Complete runnable DDL for 3-table signal architecture: signal_events hypertable with 7-day chunks and compression, trade_frames with composite FK to hypertable PK via denormalized signal_ts, trade_executions, and signal_ledger_full join view.**

## Performance

- **Duration:** 15 min
- **Started:** 2026-06-15T22:45:00Z
- **Completed:** 2026-06-15T22:48:31Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments

- Produced `production/migrations/137_3table_schema.sql` (237 lines): fully runnable DDL ready for Phase 129 to apply with zero open design questions
- signal_events hypertable: 26 columns, composite PK (signal_id, ts), 7-day chunk interval, compression segmented by (symbol, timeframe) ordered by ts DESC, 7-day compression policy, 8 btree indexes covering all ML segmentation dimensions
- trade_frames: 20 columns, simple PK (frame_id), composite FK `FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)` with denormalized signal_ts as FK anchor, 3 indexes
- trade_executions: 13 columns, simple PK (execution_id), FK to trade_frames.frame_id, 2 indexes
- signal_ledger_full view: backward-compat LEFT JOIN surface across all three tables per CONTEXT.md D-05 SQL

## Task Commits

1. **Task 1: Write 137_3table_schema.sql DDL migration** - `97cdfcaa` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `production/migrations/137_3table_schema.sql` - Complete DDL for 3-table signal architecture; Phase 129 applies this file verbatim

## Decisions Made

- **View name is signal_ledger_full not signal_ledger_v2.** CONTEXT.md D-05 labels it `signal_ledger_v2` but CLAUDE.md canonical name for Phase 128 is `signal_ledger_full` and the plan success criteria explicitly require `signal_ledger_full`. Used D-05 SQL content exactly, updated the view name to match the canonical identifier.
- **IF NOT EXISTS on all tables and indexes.** The plan required idempotency guards. Migration runners apply each migration once, but guards prevent re-run failures during development.
- **No transaction wrapper.** Matches migration 136 style - transaction applied by runner, not individual files. Note: `create_hypertable` and `add_compression_policy` are DDL-level calls that manage their own state; wrapping them in explicit transactions is not necessary.
- **ADD PRIMARY KEY after create_hypertable.** TimescaleDB requires the table to exist as a hypertable before adding a composite PK that includes the partition dimension. Order: CREATE TABLE -> create_hypertable -> ADD PRIMARY KEY.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Phase 129 executes the migration.

## Next Phase Readiness

- `production/migrations/137_3table_schema.sql` is complete and ready for Phase 129 to apply via psql
- Phase 129 must: apply this DDL, then run the data migration copying signal_ledger rows into the three new tables
- Phase 130 writer must populate signal_ts on every trade_frames INSERT to satisfy the composite FK
- signal_ledger_full view will conflict with the existing migration 095 signal_ledger_full view until Phase 129 replaces it via `CREATE OR REPLACE VIEW`

---
*Phase: 128-3-table-schema-design-and-adr*
*Completed: 2026-06-15*
