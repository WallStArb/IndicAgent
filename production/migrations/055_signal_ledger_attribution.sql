-- Migration 055: Add per-stage confidence attribution columns to signal_ledger
-- Phase 57: IntelligencePipelineComputeAgent — Unified I1-I7 Pipeline
--
-- Adds two nullable FLOAT columns that capture signal confidence at two pipeline
-- checkpoints, enabling post-hoc attribution analysis:
--   pre_quality_confidence  — captured immediately before apply_quality_gate()
--   pre_calibration_confidence — captured after quality_gate + regime_gate + tod_adjust,
--                                immediately before apply_calibration()
--
-- Invariant (enforced by application, not DB constraint):
--   pre_quality_confidence >= pre_calibration_confidence >= calibrated_confidence
--
-- NULL for all rows inserted before Phase 57 cutover (Plan 4).
-- Non-null only for rows written by IntelligencePipelineComputeAgent.
--
-- Apply: docker exec timescaledb psql -U postgres -d indicagent -f /tmp/052_signal_ledger_attribution.sql
-- Verify: SELECT column_name, data_type FROM information_schema.columns
--         WHERE table_name = 'signal_ledger'
--         AND column_name IN ('pre_quality_confidence', 'pre_calibration_confidence');

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS pre_quality_confidence     FLOAT,
    ADD COLUMN IF NOT EXISTS pre_calibration_confidence FLOAT;

COMMENT ON COLUMN signal_ledger.pre_quality_confidence IS
    'Signal confidence captured immediately before apply_quality_gate(). '
    'NULL for rows inserted before Phase 57.';

COMMENT ON COLUMN signal_ledger.pre_calibration_confidence IS
    'Signal confidence captured after quality_gate+regime_gate+tod_adjust, '
    'immediately before apply_calibration(). NULL for rows inserted before Phase 57.';
