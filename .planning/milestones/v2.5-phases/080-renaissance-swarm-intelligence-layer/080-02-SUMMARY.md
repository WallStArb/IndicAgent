---
phase: "080"
plan: "02"
subsystem: "schema/database"
tags: ["migration", "timescaledb", "swarm", "schema", "signal_ledger"]
dependency_graph:
  requires: []
  provides:
    - "signal_ledger.adjusted_confidence FLOAT column"
    - "signal_ledger.swarm_multiplier FLOAT column"
    - "signal_ledger.swarm_agent_count INT column"
    - "swarm_agent_weights table (agent_id, timeframe PK)"
    - "idx_ledger_adjusted_confidence partial index"
  affects:
    - "signal_ledger hypertable"
    - "Plans 05 (dispatch), 06 (writer) — depend on these columns"
tech_stack:
  added: []
  patterns:
    - "Idempotent DDL (ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT EXISTS)"
    - "Partial index (WHERE adjusted_confidence IS NOT NULL)"
key_files:
  created:
    - "production/migrations/082_swarm_weights_and_adjusted_confidence.sql"
  modified: []
decisions:
  - "Migration applied immediately to TimescaleDB — all three columns confirmed present, swarm_agent_weights table queryable"
  - "All ALTER TABLE uses IF NOT EXISTS — migration is idempotent and safe to re-run"
  - "Partial index WHERE adjusted_confidence IS NOT NULL — zero overhead until WriterAgent (Plan 06) populates the column"
metrics:
  duration_minutes: 3
  completed_date: "2026-05-07"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 80 Plan 02: Schema Migration 082 Summary

Phase 80 schema foundation — three nullable columns on `signal_ledger` plus a new `swarm_agent_weights` table, applied idempotently to TimescaleDB.

## What Was Done

Created and applied `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` with all DDL required for Phase 80 swarm enrichment:

- **3 new columns on `signal_ledger`**: `adjusted_confidence FLOAT`, `swarm_multiplier FLOAT`, `swarm_agent_count INT` — all nullable with `IF NOT EXISTS` guard
- **New table `swarm_agent_weights`**: keyed on `(agent_id, timeframe)` PRIMARY KEY; columns `weight FLOAT DEFAULT 1.0`, `sample_size INT DEFAULT 0`, `spearman_rho FLOAT`, `calibration_error FLOAT`, `updated_at TIMESTAMPTZ`
- **Partial index `idx_ledger_adjusted_confidence`**: on `signal_ledger(adjusted_confidence) WHERE adjusted_confidence IS NOT NULL` — zero overhead until populated

## Verification

Schema confirmed in live TimescaleDB:

```
column_name          | data_type
---------------------+------------------
adjusted_confidence  | double precision
swarm_agent_count    | integer
swarm_multiplier     | double precision
(3 rows)
```

`swarm_agent_weights` table queryable (empty, as expected — no weights until Plan 05 dispatch runs).

## Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create migration 082 and apply to TimescaleDB | f7c9bc32 | production/migrations/082_swarm_weights_and_adjusted_confidence.sql |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `production/migrations/082_swarm_weights_and_adjusted_confidence.sql` exists
- [x] All 7 grep checks from acceptance criteria pass (0 destructive ops, all DDL present)
- [x] TimescaleDB shows 3 new columns on signal_ledger
- [x] swarm_agent_weights table queryable

## Self-Check: PASSED
