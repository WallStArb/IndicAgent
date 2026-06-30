-- Migration 184: Add regime_rolling column for HMM rolling refit pilot
-- Experiment: docs/experiments/2024-06-29-hmm-rolling-refit-pilot.md
-- Date: 2026-06-29

-- Add regime_rolling column to feature_vectors (shadow column for pilot testing)
ALTER TABLE feature_vectors
ADD COLUMN IF NOT EXISTS regime_rolling TEXT;

-- Add index for efficient regime-based queries in IC engine comparison
CREATE INDEX IF NOT EXISTS idx_feature_vectors_regime_rolling
ON feature_vectors (symbol, tf, regime_rolling)
WHERE regime_rolling IS NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN feature_vectors.regime_rolling IS
'Shadow regime label from rolling HMM refit pilot (3-year window, annual step). Experiment tests whether parameter look-ahead bias materially affects IC scores. Canonical regime remains in ''regime'' column.';
