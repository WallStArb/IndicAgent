-- production/migrations/013_add_i2_column.sql
-- Add I2 tier JSONB column to intelligence_features
-- Version: 1.0.0
-- Date: 2026-03-01

ALTER TABLE intelligence_features
    ADD COLUMN IF NOT EXISTS i2 JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_intel_features_i2_gin
    ON intelligence_features USING GIN (i2);
