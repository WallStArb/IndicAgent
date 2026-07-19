-- Phase 78 D-27: Add probabilistic-forecast metrics to llm_model_scores.
-- Nullable: existing rows remain valid; back-fill happens on next _recompute_scores cycle.

ALTER TABLE llm_model_scores
    ADD COLUMN IF NOT EXISTS brier_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS calibration_slope DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS ece DOUBLE PRECISION;

COMMENT ON COLUMN llm_model_scores.brier_score IS 'Mean squared error of confidence vs realized outcome; lower is better; 0.0 = perfect.';
COMMENT ON COLUMN llm_model_scores.calibration_slope IS 'OLS slope of outcome on confidence; 1.0 = perfectly calibrated; <1 = over-confident.';
COMMENT ON COLUMN llm_model_scores.ece IS 'Expected Calibration Error across 10 equal-width confidence bins.';
