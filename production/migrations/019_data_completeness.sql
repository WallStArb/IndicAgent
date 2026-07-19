-- 018_data_completeness.sql
-- Phase 13: Add i7, i8, days_to_expiry columns to intelligence_features
-- Date: 2026-03-05
--
-- Design:
--   i7 JSONB NOT NULL DEFAULT '[]' — all_ranked signals per bar (enriched async by signal_generator)
--   i8 JSONB NOT NULL DEFAULT '{}' — narrative metadata per bar (enriched async by ai_narrative)
--   days_to_expiry INTEGER — nullable; computed at write time by feature_writer from get_active_contracts()
--
--   Pre-migration rows: i7 defaults to '[]' (empty list = no signals); i8 defaults to '{}' (empty object = no narrative); days_to_expiry NULL for old rows.
--   GIN indexes on i7/i8 consistent with i1-i6 pattern for JSONB field queries.

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i7 JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i8 JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS days_to_expiry INTEGER;

CREATE INDEX IF NOT EXISTS idx_intel_features_i7_gin
    ON intelligence_features USING GIN (i7);

CREATE INDEX IF NOT EXISTS idx_intel_features_i8_gin
    ON intelligence_features USING GIN (i8);

COMMENT ON COLUMN intelligence_features.i7 IS
    'All I7 setup signals ranked per bar. Structure: list of {setup_type, confidence, direction, regime_eligible, suppression_reason, entry, stop, target, composite_rank, is_winner}. Empty list [] when no signals fired. Populated async by signal_generator_service via intelligence_i7:SYMBOL:TF stream.';

COMMENT ON COLUMN intelligence_features.i8 IS
    'AI narrative metadata for this bar. Structure: {model, confidence, summary, signal_id, generated_at} when narrative was generated, {} otherwise (sparse is correct). Populated async by ai_narrative_service via intelligence_i8:SYMBOL:TF stream.';

COMMENT ON COLUMN intelligence_features.days_to_expiry IS
    'Calendar days until contract expiry at bar timestamp. 0 for non-futures (FX, crypto). NULL for rows written before Phase 13 migration. Computed from get_active_contracts() expiry map at feature_writer write time.';
