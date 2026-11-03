-- 584 4b-2 group 3: the four event-counter columns are right-censored, not saturating.
-- NULL = no event known inside the trailing window, or an unknown (NaN) event row newer
-- than the newest known True. Supersedes migration 288's saturating-window-1 comment text.

COMMENT ON COLUMN feature_vectors.bars_since_extreme_move_fast IS 'bars since |log_ret| > sigma_threshold*rolling_std, fast window; NULL when no event is known inside the window (right-censored, todo 584 rule 2; APR: feature.bars_since_extreme_move.sigma_threshold)';
COMMENT ON COLUMN feature_vectors.bars_since_extreme_move_slow IS 'bars since |log_ret| > sigma_threshold*rolling_std, slow window; NULL when no event is known inside the window (right-censored, todo 584 rule 2; APR: feature.bars_since_extreme_move.sigma_threshold)';
COMMENT ON COLUMN feature_vectors.bars_since_vol_spike_fast IS 'bars since rel_volume > vol_spike_threshold, fast window; NULL when no event is known inside the window (right-censored, todo 584 rule 2; APR: feature.bars_since_vol_spike.threshold)';
COMMENT ON COLUMN feature_vectors.bars_since_vol_spike_slow IS 'bars since rel_volume > vol_spike_threshold, slow window; NULL when no event is known inside the window (right-censored, todo 584 rule 2; APR: feature.bars_since_vol_spike.threshold)';
