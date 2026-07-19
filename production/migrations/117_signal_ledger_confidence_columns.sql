-- Migration 117: add raw_confidence and calibrated_confidence to signal_ledger
--
-- raw_confidence: plugin-computed score before any extrinsic adjustment
--   (maps from pre_quality_confidence stamped by signal_processor.py before calibration)
-- calibrated_confidence: post-calibration score before regime gating
--   (set by calibrator.py; regime_gate.py attenuates this further but that result
--    is NOT stored — cis_score captures the final regime-adjusted CIS, not this)
--
-- Both are required ML features: separating intrinsic signal quality from
-- extrinsic adjustments is necessary to train models on what the calibration
-- and regime gating are actually contributing to outcomes.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS raw_confidence double precision,
    ADD COLUMN IF NOT EXISTS calibrated_confidence double precision;
