-- Migration 096: Add attribution confidence fields to signal_ledger
-- pre_quality_confidence: raw confidence before quality gate adjustment (stamped by signal_processor)
-- pre_calibration_confidence: confidence after quality gate but before time-of-day calibration
-- Both are captured in-memory during the I7 pipeline but were never persisted until this migration.
-- All nullable — pre-migration rows have NULL.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS pre_quality_confidence     double precision,
    ADD COLUMN IF NOT EXISTS pre_calibration_confidence double precision;
