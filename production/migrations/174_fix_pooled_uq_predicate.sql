-- Migration 174: Narrow feature_ic_scores_pooled_uq to exclude symbol='POOLED' rows.
--
-- Cross-sectional rows (symbol='POOLED', is_pooled=true, regime=actual_regime) were
-- conflicting with this index because its predicate (WHERE is_pooled = true) captured
-- them, but its column list omits `regime`. Two cross-sectional rows with different
-- regimes but the same (feature_name, symbol, tf, lookahead_bars, training_window_end)
-- collided on this index before the DO NOTHING on feature_ic_scores_cross_sectional_uq
-- could fire.
--
-- Fix: add AND symbol != 'POOLED' so cross-sectional rows fall exclusively under
-- feature_ic_scores_cross_sectional_uq.

DROP INDEX IF EXISTS feature_ic_scores_pooled_uq;

CREATE UNIQUE INDEX feature_ic_scores_pooled_uq
    ON feature_ic_scores (feature_name, symbol, tf, lookahead_bars, training_window_end)
    WHERE is_pooled = true AND symbol != 'POOLED';
