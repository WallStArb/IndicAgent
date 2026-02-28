-- Add CIS scoring columns to signal_ledger
-- Version: 1.0.0
-- Last Updated: 2026-02-27
-- Status: Current
--
-- Purpose:
--   Enables tracking CIS bucket scores at signal fire time and signal quality on exit.
--   weights_version links to cis_weights table (added in migration 012).
--   signal_quality is populated by signal_tracker_service.py on signal exit.
--
-- Design decisions:
--   - All columns NULLABLE — pre-CIS signals will have NULL for all 4 columns.
--   - bucket_scores JSONB — store {"trend": 0.4, ...} as structured data for
--     weight_updater training queries.
--   - Partial index on resolved signals covers weight_updater training queries only.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS cis_score       FLOAT,
    ADD COLUMN IF NOT EXISTS bucket_scores   JSONB,
    ADD COLUMN IF NOT EXISTS weights_version INTEGER,
    ADD COLUMN IF NOT EXISTS signal_quality  FLOAT;

-- Index for weight_updater queries (resolved signals with outcomes)
CREATE INDEX IF NOT EXISTS idx_ledger_resolved_cis
    ON signal_ledger (weights_version, signal_quality)
    WHERE weights_version IS NOT NULL AND signal_quality IS NOT NULL;
