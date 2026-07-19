-- Migration 149: HMM trainer, GARCH, and Kalman hyperparameter APR keys.
--
-- Moves hardcoded numeric constants from hmm_trainer.py, garch_volatility.py,
-- and kalman_trend.py into the Adaptive Parameter Registry so they surface
-- in /config/parameters and become ML learning targets.
--
-- All inserts are idempotent: ON CONFLICT (config_key) DO NOTHING.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.hmm.n_components',
    'int',
    '3',
    2, 10,
    '[conventional] Number of hidden states in the GaussianHMM. 3 = ranging/trending-up/trending-down; conventional choice for price regime classification. Not an ML learning target (changes model topology, requires full retraining).'
),
(
    'feature.hmm.n_iter',
    'int',
    '50',
    10, 500,
    '[conventional] Maximum Baum-Welch EM iterations for GaussianHMM training. 50 is standard; increase if convergence warnings appear. Not an ML learning target.'
),
(
    'feature.hmm.min_rows_for_training',
    'int',
    '500',
    100, 10000,
    '[conventional] Minimum valid observation rows per TF required to attempt Baum-Welch training. Below this threshold the TF is skipped. Not an ML learning target.'
),
(
    'feature.hmm.vol_window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for realized volatility computation in the HMM observation vector. Must match HMMRegimePlugin.vol_window for trainer/inference consistency. Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1m',
    'int',
    '30',
    7, 180,
    '[conventional] Training query lookback in days for 1m bars (~43,200 bars on liquid futures). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.5m',
    'int',
    '60',
    14, 365,
    '[conventional] Training query lookback in days for 5m bars (~17,280 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.15m',
    'int',
    '90',
    30, 365,
    '[conventional] Training query lookback in days for 15m bars (~8,640 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1h',
    'int',
    '180',
    60, 730,
    '[conventional] Training query lookback in days for 1h bars (~4,320 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.4h',
    'int',
    '365',
    90, 730,
    '[conventional] Training query lookback in days for 4h bars (~2,190 bars). Not an ML learning target.'
),
(
    'feature.hmm.lookback_days.1d',
    'int',
    '730',
    180, 1825,
    '[conventional] Training query lookback in days for 1d bars (~730 bars). Not an ML learning target.'
),
(
    'feature.garch.omega',
    'float',
    '0.00001',
    0.000001, 0.001,
    '[conventional] GARCH(1,1) long-run variance intercept (omega). Standard prior for equity/futures returns; controls unconditional variance floor. ML learning target: tune per instrument class after sufficient trade_frames with counterfactual_pnl_r (n >= 100).'
),
(
    'feature.garch.alpha',
    'float',
    '0.10',
    0.01, 0.50,
    '[conventional] GARCH(1,1) shock coefficient (alpha). Weight on lagged squared return epsilon^2. Standard prior; 0.10 is conventional for daily-frequency equity series. ML learning target. Constraint: alpha + beta < 1 for stationarity.'
),
(
    'feature.garch.beta',
    'float',
    '0.85',
    0.50, 0.99,
    '[conventional] GARCH(1,1) persistence coefficient (beta). Weight on lagged conditional variance. 0.85 is conventional; high persistence typical of equity vol. ML learning target. Constraint: alpha + beta < 1 for stationarity.'
),
(
    'feature.kalman.garch_r_scale',
    'float',
    '10000.0',
    100.0, 1000000.0,
    '[conventional] Scale factor applied to garch_sigma when computing adaptive measurement noise R for the Kalman filter. R_adaptive = (garch_sigma * scale)^2. garch_sigma is in log-return units (~0.001-0.02); scale maps to R range 0.1-40 in price units. ML learning target: tune per instrument class after Phase 133 corpus.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries (seed values = defaults)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.hmm.n_components', '3', 1),
('feature.hmm.n_iter', '50', 1),
('feature.hmm.min_rows_for_training', '500', 1),
('feature.hmm.vol_window', '20', 1),
('feature.hmm.lookback_days.1m', '30', 1),
('feature.hmm.lookback_days.5m', '60', 1),
('feature.hmm.lookback_days.15m', '90', 1),
('feature.hmm.lookback_days.1h', '180', 1),
('feature.hmm.lookback_days.4h', '365', 1),
('feature.hmm.lookback_days.1d', '730', 1),
('feature.garch.omega', '0.00001', 1),
('feature.garch.alpha', '0.10', 1),
('feature.garch.beta', '0.85', 1),
('feature.kalman.garch_r_scale', '10000.0', 1)
ON CONFLICT (config_key) DO NOTHING;
