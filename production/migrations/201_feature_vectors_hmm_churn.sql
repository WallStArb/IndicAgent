-- Migration 201: Add feature_vectors.hmm_churn column (P2c).
--
-- Rolling churn_window-bar regime-label-change rate, populated by regime_writer.py.
-- Nullable — legacy rows stay NULL until re-labeled by the next regime_writer run.
-- No backfill here; regime_writer populates this column on its next run.

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hmm_churn double precision;

COMMENT ON COLUMN feature_vectors.hmm_churn IS
    'Rolling label-change rate over the prior feature.hmm.churn_window bars (P2c). '
    '1.0 = every bar in the window changed regime label; 0.0 = fully stable. '
    'NULL until regime_writer.py re-labels the row. High churn signals boundary '
    'oscillation the LIFECYCLE-04 regime-shift guard must be able to distinguish '
    'from a genuine regime shift.';
