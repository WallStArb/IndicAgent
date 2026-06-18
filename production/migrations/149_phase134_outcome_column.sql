-- Migration 149: Add outcome column to trade_executions (Phase 134)
--
-- Adds the 9-class SignalOutcome classification to trade_executions so that
-- stopped_at_entry rate and other outcome distributions can be queried directly
-- without re-deriving the taxonomy on every query.
--
-- Order is important:
--   1. Add column (nullable for backfill)
--   2. Add CHECK constraint BEFORE backfill (all rows are NULL → instant check)
--   3. Add index
--   4. Backfill historical rows from existing actual_mfe/actual_bars/exit_reason
--
-- After this migration, SELECT COUNT(*) FROM trade_executions WHERE outcome IS NULL
-- must return 0.

-- Step 1: Add outcome column (nullable to allow backfill before enforcement)
ALTER TABLE trade_executions ADD COLUMN IF NOT EXISTS outcome TEXT;

-- Step 2: CHECK constraint enumerating all 9 SignalOutcome values.
-- Added BEFORE backfill so constraint validates cheaply (all rows are NULL at this point).
-- CONDITION_EXPIRED is the 9th value — resolves live lifecycle_tracker.py:379 path
-- that previously had no valid enum member.
ALTER TABLE trade_executions
    ADD CONSTRAINT chk_te_outcome CHECK (
        outcome IS NULL OR outcome IN (
            'never_activated',
            'stopped_at_entry',
            'stopped_in_trade',
            'target_1',
            'target_1_2',
            'target_full',
            'ttl_expired_ahead',
            'ttl_expired_behind',
            'condition_expired'
        )
    );

-- Step 3: Partial index for query efficiency (only index non-NULL rows)
CREATE INDEX IF NOT EXISTS idx_trade_executions_outcome
    ON trade_executions(outcome)
    WHERE outcome IS NOT NULL;

-- Step 4: Backfill historical rows.
-- Logic mirrors _classify_stop_outcome() in lifecycle_tracker.py exactly,
-- including the actual_bars IS NULL branch (None bars => never activated => entry stop).
-- CONDITION_EXPIRED maps to itself — NOT to ttl_expired_behind (that would be lossy).
-- ttl_expired (bare, without _ahead/_behind suffix) is mapped by actual_mfe sign,
-- matching lifecycle_tracker.py:636.
UPDATE trade_executions
SET outcome =
    CASE
        WHEN exit_reason = 'stop_loss' THEN
            CASE
                WHEN actual_mfe <= 0.05 OR actual_bars IS NULL OR actual_bars <= 2
                THEN 'stopped_at_entry'
                ELSE 'stopped_in_trade'
            END
        WHEN exit_reason = 'chandelier_stop' THEN 'stopped_in_trade'
        WHEN exit_reason = 'condition_expired' THEN 'condition_expired'
        WHEN exit_reason = 'ttl_expired' THEN
            CASE
                WHEN actual_mfe > 0 THEN 'ttl_expired_ahead'
                ELSE 'ttl_expired_behind'
            END
        WHEN exit_reason IN (
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind'
        ) THEN exit_reason
        ELSE NULL
    END
WHERE outcome IS NULL;
