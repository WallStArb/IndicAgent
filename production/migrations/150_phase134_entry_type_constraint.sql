-- Migration 150: Add CHECK constraint to trade_frames.entry_type (Phase 134)
--
-- Enforces at the DB level that entry_type is always one of the 5 valid
-- EntryType values defined in src/intelligence/trading/signal_outcome.py.
-- Mirrors the approach of migration 149 (chk_te_outcome on trade_executions).
--
-- Preflight audit (run before applying):
--   SELECT DISTINCT entry_type FROM trade_frames ORDER BY entry_type;
-- All existing values must be in the allowed set — confirmed at migration time
-- (only 'at_close' present in the corpus).
--
-- Note: this constraint may already exist if applied by a parallel migration.
-- The DO block is idempotent.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'trade_frames'::regclass
          AND conname = 'chk_tf_entry_type'
    ) THEN
        ALTER TABLE trade_frames
            ADD CONSTRAINT chk_tf_entry_type
            CHECK (entry_type IN (
                'at_close',
                'at_pullback',
                'at_limit',
                'at_reclaim',
                'zone_proximal'
            ));
    END IF;
END $$;
