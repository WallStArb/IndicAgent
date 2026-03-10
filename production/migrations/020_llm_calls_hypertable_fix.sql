-- 020_llm_calls_hypertable_fix.sql
-- Phase 16 gap closure: convert llm_calls to a TimescaleDB hypertable
-- Date: 2026-03-06
--
-- Root cause: Migration 019 used "call_id UUID PRIMARY KEY" which creates a
-- unique index on call_id alone. TimescaleDB requires the partition column
-- (called_at) in every unique index. The create_hypertable call silently
-- no-oped due to "if_not_exists => TRUE" masking the constraint conflict.
--
-- Fix:
--   1. Drop the single-column PK constraint.
--   2. Add a composite PK (call_id, called_at) that satisfies TimescaleDB.
--   3. Call create_hypertable WITHOUT the silent no-op flag so failures surface.
--   4. Use migrate_data => TRUE because the table already has rows.
--   5. Guard the whole block so running this migration twice is a no-op.

DO $$
BEGIN
    -- Only run if llm_calls is NOT already a hypertable
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'llm_calls'
    ) THEN
        -- Drop the UUID-only primary key (blocks hypertable creation)
        ALTER TABLE llm_calls DROP CONSTRAINT IF EXISTS llm_calls_pkey;

        -- Add composite PK that includes the partition column
        ALTER TABLE llm_calls ADD PRIMARY KEY (call_id, called_at);

        -- Create the hypertable — no silent no-op flag so errors surface
        PERFORM create_hypertable('llm_calls', 'called_at', migrate_data => TRUE);

        RAISE NOTICE 'llm_calls converted to TimescaleDB hypertable partitioned by called_at';
    ELSE
        RAISE NOTICE 'llm_calls is already a hypertable — skipping migration 020';
    END IF;
END
$$;

-- Verify the hypertable was created (returns 1 row or raises)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM timescaledb_information.hypertables
        WHERE hypertable_name = 'llm_calls'
    ) THEN
        RAISE EXCEPTION 'VERIFICATION FAILED: llm_calls is still not a hypertable after migration 020';
    END IF;
    RAISE NOTICE 'VERIFICATION PASSED: llm_calls is a hypertable partitioned by called_at';
END
$$;
