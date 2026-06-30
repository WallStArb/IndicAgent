-- Migration 187: Demote 7 zero-IC features from ensemble_weights.
-- These features showed zero information coefficient in Phase A corpus runs and must
-- not influence alpha_publisher scoring. The features remain in feature_vectors as
-- diagnostic data; this only removes them from the ensemble weighting table.
DELETE FROM ensemble_weights
WHERE feature_name IN (
    'momentum_rank_z',
    'poc_dist_atr',
    'sr_resist_dist',
    'sr_support_dist',
    'va_position',
    'volatility_rank_z',
    'volume_rank_z'
);
