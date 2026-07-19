-- Migration 175: Add partial unique index for cross-sectional IC rows
-- Cross-sectional rows use symbol='POOLED' with distinct regime labels,
-- so their uniqueness key must include regime (unlike per-symbol pooled rows
-- which aggregate across regimes and omit regime from the constraint).
CREATE UNIQUE INDEX IF NOT EXISTS feature_ic_scores_cross_sectional_uq
    ON feature_ic_scores (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
    WHERE is_pooled = true AND symbol = 'POOLED';

-- Remove the 244 rows written with the wrong conflict target in the first partial run.
DELETE FROM feature_ic_scores WHERE symbol = 'POOLED' AND is_pooled = true;
