-- Migration 039: Performance fixes + schema correctness (Phase 35/38 follow-up)
--
-- Fixes identified by Postgres best-practices audit (2026-03-18):
--
--   1. Create confidence_calibration table (migration 038 was not applied)
--   2. Add signal_computed_at partial index on signal_ledger
--   3. Add event_type index on system_events
--   4. Add CHECK constraints on contract_metadata (asset_class, roll_direction)
--   5. Add updated_at auto-trigger on contract_metadata
--
-- All statements idempotent. No CONCURRENTLY (not supported on hypertables).

-- ============================================================
-- Section 1: confidence_calibration table
-- (migration 038_calibration_fields.sql was not applied)
-- ============================================================

CREATE TABLE IF NOT EXISTS confidence_calibration (
    plugin_name   TEXT         NOT NULL,
    timeframe     TEXT         NOT NULL,
    breakpoints   DOUBLE PRECISION[] NOT NULL,
    values        DOUBLE PRECISION[] NOT NULL,
    ece           DOUBLE PRECISION   NOT NULL,
    sample_size   INT          NOT NULL,
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (plugin_name, timeframe)
);

COMMENT ON TABLE confidence_calibration IS
    'Isotonic regression calibration curves per (plugin_name, timeframe). '
    'Refreshed every 30 min by confidence_calibrator.py when N >= 100 resolved signals.';

-- ============================================================
-- Section 2: signal_ledger.signal_computed_at index
--
-- Queries in signals.py filter on signal_computed_at directly:
--   - Analytics strip: signal_computed_at >= NOW() - INTERVAL '24 hours'
--   - Calibrator:      signal_computed_at IS NOT NULL (for outcome rows)
--
-- Partial index (IS NOT NULL) keeps it small — backfilled/legacy rows
-- without signal_computed_at are never queried via this column.
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_signal_ledger_computed_at
    ON signal_ledger (signal_computed_at DESC)
    WHERE signal_computed_at IS NOT NULL;

-- ============================================================
-- Section 3: system_events.event_type index
--
-- Audit log queries filter by event_type (e.g. 'roll', 'pipeline_reset').
-- No index exists today.
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_system_events_event_type
    ON system_events (event_type, detected_at DESC);

-- ============================================================
-- Section 4: contract_metadata CHECK constraints
--
-- asset_class and roll_direction are free-form TEXT today.
-- Validate at DB level to prevent invalid values accumulating.
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'contract_metadata_asset_class_check'
          AND conrelid = 'public.contract_metadata'::regclass
    ) THEN
        ALTER TABLE contract_metadata
            ADD CONSTRAINT contract_metadata_asset_class_check
            CHECK (asset_class IN ('futures', 'equity', 'crypto', 'fx', 'option'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'contract_metadata_roll_direction_check'
          AND conrelid = 'public.contract_metadata'::regclass
    ) THEN
        ALTER TABLE contract_metadata
            ADD CONSTRAINT contract_metadata_roll_direction_check
            CHECK (roll_direction IN ('up', 'down', 'flat', 'unknown'));
    END IF;
END $$;

-- ============================================================
-- Section 5: contract_metadata updated_at auto-trigger
--
-- The updated_at column has DEFAULT NOW() but never updates on
-- subsequent writes. A trigger ensures it stays current.
-- ============================================================

CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_contract_metadata_updated_at'
          AND tgrelid = 'public.contract_metadata'::regclass
    ) THEN
        CREATE TRIGGER trg_contract_metadata_updated_at
            BEFORE UPDATE ON contract_metadata
            FOR EACH ROW EXECUTE FUNCTION _set_updated_at();
    END IF;
END $$;
