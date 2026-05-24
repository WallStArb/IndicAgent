-- Migration 094: Re-add CIS scoring columns dropped during Phase 104 storage redesign
-- Columns: cis_score (FLOAT), bucket_scores (JSONB), weights_version (INT)
-- Required by: weight_updater.py training query, cis_weights adaptive learning loop
-- All nullable — pre-migration rows have NULL; weight_updater filters WHERE bucket_scores IS NOT NULL

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS cis_score       FLOAT,
    ADD COLUMN IF NOT EXISTS bucket_scores   JSONB,
    ADD COLUMN IF NOT EXISTS weights_version INTEGER;

-- Serves run_weight_update(): WHERE outcome IS NOT NULL AND bucket_scores IS NOT NULL
-- AND is_shadow = FALSE ORDER BY timestamp DESC. Leading on timestamp satisfies the sort.
CREATE INDEX IF NOT EXISTS idx_ledger_resolved_cis
    ON signal_ledger (timestamp DESC)
    WHERE bucket_scores IS NOT NULL AND outcome IS NOT NULL AND is_shadow = FALSE;
