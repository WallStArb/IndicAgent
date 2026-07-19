-- Migration 109: enforce UNIQUE on signal_ledger.signal_id
-- Prerequisite: all existing rows must have non-null, distinct signal_ids.
-- IMPORTANT: CREATE UNIQUE INDEX CONCURRENTLY cannot run inside a transaction.
-- Run this migration OUTSIDE a transaction block (use --single-transaction=off or
-- a direct psql session, not a migration tool that wraps all statements in BEGIN).

DO $$
BEGIN
  IF (SELECT count(*) FROM (SELECT signal_id FROM signal_ledger GROUP BY signal_id HAVING count(*) > 1) t) > 0 THEN
    RAISE EXCEPTION 'Duplicate signal_ids found — deduplicate before applying constraint';
  END IF;
END $$;

-- Non-transactional — must be the only statement in its execution context:
CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_signal_id_unique
    ON signal_ledger (signal_id);
