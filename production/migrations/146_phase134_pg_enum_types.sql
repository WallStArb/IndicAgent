-- Migration 146: Create PG ENUM types for signal classification columns (Phase 134)
--
-- Converts trade_executions.outcome, trade_frames.entry_type, and
-- signal_events.status from TEXT (+ CHECK constraint) to proper PostgreSQL
-- ENUM types. Invalid values become impossible to write — rejected at the
-- DB level rather than discovered when a query silently returns 0 rows.
--
-- Pre-migration audit (Task 1) confirmed all existing values are valid:
--   trade_executions.outcome : 0 NULLs, 0 out-of-set values (6 distinct values)
--   trade_frames.entry_type  : 0 out-of-set values (at_close only)
--   signal_events.status     : 0 out-of-set values (expired/pending/active)
--
-- HYPERTABLE MAINTENANCE WINDOW (Step 4 — signal_events.status):
-- signal_events is a TimescaleDB hypertable. ALTER COLUMN TYPE rewrites every
-- chunk and acquires ACCESS EXCLUSIVE locks. Running it against a live,
-- actively-written table risks long blocking and lock contention. The status
-- column conversion MUST be executed inside a services-stopped maintenance window.
--
-- Step 4 is NOT a pure psql step. Before running psql on this file, execute:
--   sudo systemctl stop indicagent-intelligence-pipeline indicagent-signal-writer
--   sudo systemctl stop indicagent-lifecycle-writer indicagent-signal-tracker-compute
-- Then run this migration. Then restart:
--   sudo systemctl start indicagent-intelligence-pipeline
--   (lifecycle-writer and signal-tracker-compute are already inactive — leave as-is)
--
-- Additional prerequisites discovered during execution:
--   1. signal_ledger view references both trade_frames.entry_type AND signal_events.status —
--      the view must be dropped before the column casts and recreated afterward.
--   2. signal_events has compressed chunks — decompress before ALTER TABLE, recompress after:
--      SELECT decompress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, if_compressed => true)
--        FROM timescaledb_information.chunks WHERE hypertable_name='signal_events' AND is_compressed=true;
--      (after ALTER TABLE)
--      SELECT compress_chunk(format('%I.%I', chunk_schema, chunk_name)::regclass, if_not_compressed => true)
--        FROM timescaledb_information.chunks WHERE hypertable_name='signal_events'
--        AND is_compressed=false AND range_end < NOW() - INTERVAL '1 week';
--   3. signal_events.status has a column DEFAULT ('pending'::text) — drop before cast,
--      reset as 'pending'::signal_status_type afterward.
--
-- See 134-VERIFICATION.md §Hypertable Maintenance Window for the full execution log.
--
-- Idempotency: ENUM type creation uses DO blocks (PostgreSQL does not support
-- IF NOT EXISTS for CREATE TYPE). Column casts are not idempotent by nature —
-- re-running after the types are created will no-op the type creation and fail
-- the ALTER COLUMN if the column is already the ENUM type. This migration is
-- designed to be applied exactly once.


-- ---------------------------------------------------------------------------
-- Step 1: Create ENUM types
-- ---------------------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signal_outcome_type') THEN
        CREATE TYPE signal_outcome_type AS ENUM (
            'never_activated',
            'stopped_at_entry',
            'stopped_in_trade',
            'target_1',
            'target_1_2',
            'target_full',
            'ttl_expired_ahead',
            'ttl_expired_behind',
            'condition_expired'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entry_type_type') THEN
        CREATE TYPE entry_type_type AS ENUM (
            'at_close',
            'at_pullback',
            'at_limit',
            'at_reclaim',
            'zone_proximal'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signal_status_type') THEN
        CREATE TYPE signal_status_type AS ENUM (
            'pending',
            'active',
            'regime_suppressed',
            'expired'
        );
    END IF;
END $$;


-- ---------------------------------------------------------------------------
-- Step 2: Drop existing CHECK constraints (superseded by ENUM type enforcement)
-- ---------------------------------------------------------------------------

ALTER TABLE trade_executions DROP CONSTRAINT IF EXISTS chk_te_outcome;
ALTER TABLE trade_frames DROP CONSTRAINT IF EXISTS chk_tf_entry_type;


-- ---------------------------------------------------------------------------
-- Step 3: Cast non-hypertable columns (trade_executions, trade_frames)
-- Regular tables — cheaper cast, no chunk rewrite required.
-- ---------------------------------------------------------------------------

ALTER TABLE trade_executions
    ALTER COLUMN outcome TYPE signal_outcome_type
    USING outcome::signal_outcome_type;

ALTER TABLE trade_frames
    ALTER COLUMN entry_type TYPE entry_type_type
    USING entry_type::entry_type_type;


-- ---------------------------------------------------------------------------
-- Step 4: HYPERTABLE maintenance — signal_events.status
-- PREREQUISITE: writer services MUST be stopped before this step executes.
-- See migration header comment for the exact systemctl commands.
-- This ALTER TABLE rewrites every chunk (ACCESS EXCLUSIVE lock). It is safe
-- only when no concurrent writers exist.
-- ---------------------------------------------------------------------------

ALTER TABLE signal_events
    ALTER COLUMN status TYPE signal_status_type
    USING status::signal_status_type;


-- ---------------------------------------------------------------------------
-- Step 5: Add CHECK constraint on exit_reason (TEXT — retained as TEXT)
-- exit_reason is a coarser operational code, not a taxonomy label, so TEXT
-- with a CHECK is appropriate. The constraint MUST include chandelier_stop
-- and condition_expired — these are LIVE code paths in lifecycle_tracker.py
-- (lines ~347 and ~372) that currently produce 0 DB rows only because the
-- current signal regime has not triggered them. Excluding them would cause a
-- constraint violation the moment the regime triggers those exits.
-- ---------------------------------------------------------------------------

ALTER TABLE trade_executions
    ADD CONSTRAINT chk_te_exit_reason
    CHECK (exit_reason IS NULL OR exit_reason IN (
        'stop_loss',
        'chandelier_stop',
        'condition_expired',
        'ttl_expired',
        'ttl_expired_ahead',
        'ttl_expired_behind',
        'target_1',
        'target_2',
        'target_3',
        'target_1_2',
        'target_full'
    ));
