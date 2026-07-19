-- Migration 157: Seed alpha.ic.* and alpha.decay.* APR keys.
--
-- Seeds the Adaptive Parameter Registry entries for the IC engine and decay monitor.
-- All keys are idempotent: ON CONFLICT (config_key) DO NOTHING.
--
-- Key design notes:
--
--   alpha.ic.bootstrap_block_size.*  — TF-specific circular block bootstrap block sizes.
--     Optimal block length grows O(N^(1/3)) per Hall & Horowitz 1996. 5m bars have
--     ~78 bars/day, so block_size=78 captures one trading day of autocorrelation structure.
--     15m: 26 bars/day. 1h/1d: 10 (conventional lower bound). APR allows override without
--     code change as data accumulates and empirical block length can be estimated.
--     ML-learning-target: no (block size is a methodology parameter, not a signal parameter).
--
--   alpha.ic.subsample_min_stride — minimum sampling stride for non-overlapping windows.
--     Actual stride used by IC engine = max(subsample_min_stride, lookahead_bars).
--     This ensures non-overlapping observations for all lookaheads: a fixed stride of 5
--     on a 20-bar lookahead would produce overlapping returns and corrupt the independence
--     assumption required for block bootstrap and IC Sharpe computation.
--     ML-learning-target: no.
--
-- Column set matches migration 153 (config_schema has config_key, value_type, default_value,
-- min_value, max_value, description; config_state has config_key, config_value, version).

-- -------------------------------------------------------------------------
-- Section 1: config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.ic.min_observations',
    'int',
    '500',
    100, 10000,
    '[rca_analysis] Minimum independent observations required for IC estimation. At N=100 the CI on IC=0.04 is approximately ±0.10, wider than the signal itself. At N=500 it narrows to ±0.04. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_resamples',
    'int',
    '2000',
    200, 10000,
    '[conventional] Number of circular block bootstrap resamples for IC confidence interval estimation. 2000 is conventional for stable CI coverage. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.5m',
    'int',
    '78',
    5, 500,
    '[initial_estimate] Circular block bootstrap block size for 5m bars. ~78 bars per trading day captures one day of autocorrelation structure per Hall & Horowitz 1996 O(N^(1/3)) guideline. APR-backed so empirical optimal block length can be updated without code change. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.15m',
    'int',
    '26',
    5, 200,
    '[initial_estimate] Circular block bootstrap block size for 15m bars. ~26 bars per trading day. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.1h',
    'int',
    '10',
    3, 100,
    '[conventional] Circular block bootstrap block size for 1h bars. Conventional lower bound of 10; fewer than 10 bars per day at this timeframe. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
(
    'alpha.ic.bootstrap_block_size.1d',
    'int',
    '10',
    3, 100,
    '[conventional] Circular block bootstrap block size for 1d bars. Conventional lower bound of 10 for daily frequency. See alpha.ic.bootstrap_block_size.5m for methodology. Not an ML learning target.'
),
(
    'alpha.ic.fdr_alpha',
    'float',
    '0.05',
    0.001, 0.20,
    '[conventional] Benjamini-Hochberg FDR correction q-value for multiple-testing correction across the full feature universe. 0.05 is the conventional choice for financial IC studies. Not an ML learning target.'
),
(
    'alpha.ic.walk_forward_folds',
    'int',
    '3',
    2, 10,
    '[conventional] Number of chronological walk-forward validation folds. 3 folds is the conventional minimum for out-of-sample stability assessment given data depth constraints. Not an ML learning target.'
),
(
    'alpha.ic.sharpe_window_size',
    'int',
    '2000',
    200, 20000,
    '[rca_analysis] Observations per rolling IC Sharpe window. 2000 non-overlapping observations at 1/5 sub-sampling = 10,000 bars per window. Matches the minimum for statistically stable IC Sharpe per IC spec §X.1. Not an ML learning target.'
),
(
    'alpha.ic.sharpe_min_windows',
    'int',
    '10',
    3, 50,
    '[conventional] Minimum number of rolling IC windows required to compute IC Sharpe. Below this threshold ic_sharpe is NULL. 10 windows is the conventional minimum for a time-series t-test to have power. Not an ML learning target.'
),
(
    'alpha.ic.subsample_min_stride',
    'int',
    '5',
    1, 60,
    '[conventional] Minimum sampling stride for non-overlapping IC observations. Actual stride = max(subsample_min_stride, lookahead_bars). This ensures non-overlapping observations for all lookaheads: a fixed stride of 5 on a 20-bar lookahead would produce overlapping returns and corrupt the independence assumption required for block bootstrap and IC Sharpe computation. Not an ML learning target.'
),
(
    'alpha.ic.min_reliable_n',
    'int',
    '100',
    20, 1000,
    '[conventional] n_independent threshold for the reliable flag on feature_ic_scores rows. Below this threshold the IC estimate is recorded but marked unreliable; it is excluded from ensemble weight computation. Not an ML learning target.'
),
(
    'alpha.decay.ci_lower_threshold',
    'float',
    '0.0',
    -1.0, 0.5,
    '[conventional] Rolling IC CI lower bound below which is_decaying is set to true. Zero means the IC is no longer statistically positive. Not an ML learning target.'
),
(
    'alpha.decay.materiality_threshold',
    'float',
    '0.005',
    0.0001, 0.10,
    '[initial_estimate] Minimum (weight × |ic_ci_lower|) to trigger EnsembleBuilder re-solve. Prevents costly re-solve on features with negligible portfolio weight even if their IC is decaying. Not an ML learning target.'
),
(
    'alpha.decay.regime_shift_fraction',
    'float',
    '0.60',
    0.10, 1.0,
    '[initial_estimate] Fraction of (feature, symbol, tf) cells simultaneously showing decay that classifies an event as a market regime shift rather than feature-specific decay. Holds weights during market-wide IC collapse to prevent whipsaw re-solving. Not an ML learning target.'
),
(
    'alpha.decay.recovery_min_observations',
    'int',
    '2000',
    200, 20000,
    '[rca_analysis] New independent observations required before a decaying feature is eligible for recovery evaluation. Must be non-overlapping with the decay detection window to avoid look-ahead bias in the recovery decision. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 2: config_state entries (seed values = defaults above)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.ic.min_observations',            '500',    1),
('alpha.ic.bootstrap_resamples',         '2000',   1),
('alpha.ic.bootstrap_block_size.5m',     '78',     1),
('alpha.ic.bootstrap_block_size.15m',    '26',     1),
('alpha.ic.bootstrap_block_size.1h',     '10',     1),
('alpha.ic.bootstrap_block_size.1d',     '10',     1),
('alpha.ic.fdr_alpha',                   '0.05',   1),
('alpha.ic.walk_forward_folds',          '3',      1),
('alpha.ic.sharpe_window_size',          '2000',   1),
('alpha.ic.sharpe_min_windows',          '10',     1),
('alpha.ic.subsample_min_stride',        '5',      1),
('alpha.ic.min_reliable_n',              '100',    1),
('alpha.decay.ci_lower_threshold',       '0.0',    1),
('alpha.decay.materiality_threshold',    '0.005',  1),
('alpha.decay.regime_shift_fraction',    '0.60',   1),
('alpha.decay.recovery_min_observations','2000',   1)
ON CONFLICT (config_key) DO NOTHING;
