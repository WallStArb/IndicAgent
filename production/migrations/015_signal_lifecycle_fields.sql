-- production/migrations/014_signal_lifecycle_fields.sql
-- Institutional-grade signal lifecycle tracking
-- All columns NULLABLE — pre-existing rows unaffected.

ALTER TABLE signal_ledger
    -- At signal determination time
    ADD COLUMN IF NOT EXISTS determined_at            TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS ask_at_signal            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bid_at_signal            DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS market_price_at_signal   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_zone_low           DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS entry_zone_high          DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS zone_valid_at_signal     BOOLEAN,

    -- At activation
    ADD COLUMN IF NOT EXISTS activation_price         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS zone_entry_pct           DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS bars_to_activation       INTEGER,

    -- During trade (written on exit — in-memory during run)
    ADD COLUMN IF NOT EXISTS mae                      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS mfe                      DOUBLE PRECISION,

    -- At exit
    ADD COLUMN IF NOT EXISTS bars_in_trade            INTEGER,
    ADD COLUMN IF NOT EXISTS outcome                  TEXT;

-- Index for ML training queries
CREATE INDEX IF NOT EXISTS idx_ledger_outcome
    ON signal_ledger (outcome, setup_plugin, timeframe)
    WHERE outcome IS NOT NULL;
