-- Phase 44.3: Add columns for BarIntelligenceRecord atomic INSERT
-- intelligence_features rows will be complete at insert time (no UPSERTs)
-- After this migration, FeatureWriterService performs a single atomic INSERT per bar
-- with all columns populated from BarIntelligenceRecord.

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS winner_plugin text,
    ADD COLUMN IF NOT EXISTS winner_confidence double precision,
    ADD COLUMN IF NOT EXISTS winner_direction text,
    ADD COLUMN IF NOT EXISTS signals_evaluated integer,
    ADD COLUMN IF NOT EXISTS signals_after_quality integer,
    ADD COLUMN IF NOT EXISTS signals_after_regime integer,
    ADD COLUMN IF NOT EXISTS signals_after_tod integer,
    ADD COLUMN IF NOT EXISTS signals_after_calibration integer,
    ADD COLUMN IF NOT EXISTS ledger_written boolean,
    ADD COLUMN IF NOT EXISTS i7_computed_at timestamptz,
    ADD COLUMN IF NOT EXISTS session_type text;
