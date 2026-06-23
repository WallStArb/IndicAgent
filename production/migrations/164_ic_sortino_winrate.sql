-- Migration 164: Add ic_sortino and ic_win_rate to feature_ic_scores.
--
-- ic_sortino:  Sortino ratio of the rolling window IC series.
--              Formula: mean(window_ICs) / semi_deviation(window_ICs, target=0)
--              where semi_deviation = sqrt(mean(neg_IC^2)) over windows where IC < 0.
--              NULL when no IC windows are negative (all windows positive — ratio
--              undefined/infinite) or when the ic_sharpe gate is not met.
--
-- ic_win_rate: Fraction of rolling windows where IC > 0. Range [0.0, 1.0].
--              NULL when the ic_sharpe gate is not met (< sharpe_min_windows windows).
--
-- Both metrics share the same rolling-window gate as ic_sharpe:
--   n_raw_bars_regime >= alpha.ic.sharpe_min_windows * alpha.ic.sharpe_window_size
--
-- Why these two:
--   ic_sharpe penalises IC volatility symmetrically. A factor alternating IC=[0.12, -0.04]
--   gets the same Sharpe penalty as IC=[0.12, 0.28]. ic_sortino separates the two by
--   penalising only negative-IC windows. ic_win_rate exposes regime stability without
--   any distributional assumption.
--
-- All statements idempotent. Safe to re-run.

ALTER TABLE feature_ic_scores
    ADD COLUMN IF NOT EXISTS ic_sortino   double precision,
    ADD COLUMN IF NOT EXISTS ic_win_rate  double precision;

COMMENT ON COLUMN feature_ic_scores.ic_sortino IS
    'Sortino ratio of rolling window IC series (mean/semi-deviation from 0). '
    'NULL when no windows have IC < 0, or when ic_sharpe gate not met.';

COMMENT ON COLUMN feature_ic_scores.ic_win_rate IS
    'Fraction of rolling windows where IC > 0. Range [0.0, 1.0]. '
    'NULL when ic_sharpe gate not met (< sharpe_min_windows windows).';
