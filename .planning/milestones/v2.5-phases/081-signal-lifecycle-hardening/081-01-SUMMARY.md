---
phase: 081-signal-lifecycle-hardening
plan: "01"
subsystem: database-migrations
tags:
  - signal-ledger
  - migration
  - data-quality
  - lifecycle
dependency_graph:
  requires: []
  provides:
    - signal_ledger.is_backfill column
    - signal_ledger.ttl_bars column
    - idx_signal_ledger_replay_lookup index
  affects:
    - signal_ledger table (truncated + extended)
    - downstream plans 02-08 (all depend on these columns)
tech_stack:
  added: []
  patterns:
    - idempotent ADD COLUMN IF NOT EXISTS
    - partial index on hypertable (WHERE exit_at IS NULL)
key_files:
  created:
    - production/migrations/083_signal_ledger_lifecycle_columns.sql
  modified: []
decisions:
  - TRUNCATE signal_ledger is irreversible by design — v0 contamination (wrong entry_price/zones pre-Phase-79 fix) makes these rows worse than no data for ML training
  - ttl_bars DEFAULT 10 mirrors existing lifecycle tracker default, safe for live signals
  - Partial index on timestamp WHERE exit_at IS NULL targets the replay auditor's query pattern without indexing the full hypertable
metrics:
  duration_seconds: 22
  completed_date: "2026-05-08"
  tasks_completed: 1
  tasks_total: 1
  files_created: 1
  files_modified: 0
---

# Phase 81 Plan 01: DB Migration 083 — Signal Ledger Lifecycle Columns Summary

**One-liner:** PostgreSQL migration adding `is_backfill` + `ttl_bars` to `signal_ledger` with irreversible TRUNCATE to remove contaminated v0 data.

## What Was Built

Migration `083_signal_ledger_lifecycle_columns.sql` performs three operations in a single transaction:

1. **TRUNCATE signal_ledger** — wipes all v0 rows whose `entry_price`/zones were computed by the pre-Phase-79 buggy `make_signal_from_frame()`. These rows cannot be salvaged: they lack `is_backfill` provenance and have structurally wrong price levels. ML training on them would introduce systematic bias.

2. **ADD COLUMN is_backfill BOOLEAN NOT NULL DEFAULT FALSE** — provenance flag distinguishing real-time signals (FALSE) from BarReplayProviderAgent catch-up signals (TRUE). ML training queries use `WHERE is_backfill = FALSE` to exclude historical replay from live-signal models, or explicitly include backfill for regime-aware training.

3. **ADD COLUMN ttl_bars INTEGER NOT NULL DEFAULT 10** — per-signal TTL window in bars. Replaces the hardcoded constant in `lifecycle_tracker.py`, enabling per-plugin or per-timeframe TTL tuning stored on the signal row itself. Default 10 matches existing tracker behavior — no behavioral change for live signals.

4. **CREATE INDEX idx_signal_ledger_replay_lookup** — partial index on `timestamp WHERE exit_at IS NULL` targeting the replay auditor's primary query pattern: pending signals older than 2 minutes that need outcome resolution.

## Operational Apply Command

```bash
docker exec -i timescaledb psql -U postgres -d indicagent \
  < production/migrations/083_signal_ledger_lifecycle_columns.sql
```

Verify after apply:
```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'signal_ledger'
  AND column_name IN ('is_backfill', 'ttl_bars')
ORDER BY column_name;

SELECT indexname FROM pg_indexes
WHERE tablename = 'signal_ledger'
  AND indexname = 'idx_signal_ledger_replay_lookup';

SELECT COUNT(*) FROM signal_ledger;  -- should be 0 post-TRUNCATE
```

## Deviations from Plan

None — plan executed exactly as written.

## Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create migration 083 — truncate + add is_backfill + ttl_bars columns | e3912786 | production/migrations/083_signal_ledger_lifecycle_columns.sql |

## Self-Check: PASSED

- FOUND: `production/migrations/083_signal_ledger_lifecycle_columns.sql`
- FOUND: commit `e3912786`
