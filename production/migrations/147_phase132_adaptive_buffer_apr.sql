-- Migration 147: Seed Phase 132 adaptive buffer piecewise coefficients into APR.
--
-- Migrates the 12 distinct configurable coefficients inside _adaptive_buffer()
-- (trade_framer.py) to config_schema + config_state. These 12 values define
-- a single piecewise GARCH vol-response curve and are the highest-value ML
-- learning targets in the stop geometry system.
--
-- NOTE: feature.trade_framer.adaptive_buffer_hard_cap is seeded separately
-- in migration 146 (Plan 02). This file seeds exactly the 12 piecewise
-- coefficient keys.
--
-- COUPLING WARNING (embedded in all descriptions): these 12 coefficients define
-- a single piecewise GARCH vol-response curve. Tuning one in isolation can
-- break the function shape — tune as a group or preserve the piecewise structure.
--
-- All keys are idempotent: ON CONFLICT (config_key) DO NOTHING / DO UPDATE.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.trade_framer.adaptive_buffer_vol_ratio_min',
    'float', '0.70', 0.1, 1.0,
    '[initial_estimate] ML learning target: Lower clamp bound for garch_vol_ratio in _adaptive_buffer(). vol_ratio values below this are clamped to this value before piecewise evaluation. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_vol_ratio_max',
    'float', '1.50', 1.0, 3.0,
    '[initial_estimate] ML learning target: Upper clamp bound for garch_vol_ratio in _adaptive_buffer(). vol_ratio values above this are clamped to this value before piecewise evaluation. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_low_vol_base',
    'float', '0.80', 0.3, 1.0,
    '[initial_estimate] ML learning target: Base multiplier for the low-volatility branch (vol_ratio <= 1.0) of _adaptive_buffer(). At vol_ratio == vol_ratio_min, garch_mult == this value. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_low_vol_slope_num',
    'float', '0.20', 0.0, 1.0,
    '[initial_estimate] ML learning target: Numerator of the slope fraction in the low-vol branch of _adaptive_buffer(). slope = low_vol_slope_num / low_vol_slope_den. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_low_vol_slope_den',
    'float', '0.30', 0.05, 1.0,
    '[initial_estimate] ML learning target: Denominator of the slope fraction in the low-vol branch of _adaptive_buffer(). slope = low_vol_slope_num / low_vol_slope_den. min > 0 prevents division by zero. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_high_vol_slope_num',
    'float', '0.35', 0.0, 1.0,
    '[initial_estimate] ML learning target: Numerator of the slope fraction in the high-vol branch of _adaptive_buffer(). slope = high_vol_slope_num / high_vol_slope_den. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_high_vol_slope_den',
    'float', '0.50', 0.05, 1.0,
    '[initial_estimate] ML learning target: Denominator of the slope fraction in the high-vol branch of _adaptive_buffer(). slope = high_vol_slope_num / high_vol_slope_den. min > 0 prevents division by zero. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_hurst_trend_threshold',
    'float', '0.55', 0.5, 0.9,
    '[initial_estimate] ML learning target: Hurst exponent threshold above which _adaptive_buffer() applies trend-tightening. Regime must be "trend". When hurst >= this value, result is tightened by (hurst - threshold) * tighten_rate. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_hurst_mr_threshold',
    'float', '0.45', 0.1, 0.5,
    '[initial_estimate] ML learning target: Hurst exponent threshold below which _adaptive_buffer() applies mean-reversion tightening. Regime must be "mean_reversion". When hurst <= this value, result is tightened by (threshold - hurst) * tighten_rate. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_hurst_tighten_rate',
    'float', '0.16', 0.0, 1.0,
    '[initial_estimate] ML learning target: Rate at which Hurst deviation tightens the buffer result in _adaptive_buffer(). Applied as result *= 1.0 - (hurst_deviation) * tighten_rate. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_garch_shock_threshold',
    'float', '3.0', 1.0, 10.0,
    '[initial_estimate] ML learning target: garch_shock value above which _adaptive_buffer() applies the shock floor multiplier. When garch_shock > this value, result is floored at base_mult * garch_shock_mult. WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
),
(
    'feature.trade_framer.adaptive_buffer_garch_shock_mult',
    'float', '1.35', 1.0, 3.0,
    '[initial_estimate] ML learning target: Floor multiplier applied to base_mult when a GARCH shock is detected in _adaptive_buffer(). result = max(result, base_mult * garch_shock_mult). WARNING: these 12 coefficients define a single piecewise GARCH vol-response curve. Tuning one in isolation can break the function shape — tune as a group or preserve the piecewise structure.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.trade_framer.adaptive_buffer_vol_ratio_min',  '0.70', 1),
    ('feature.trade_framer.adaptive_buffer_vol_ratio_max',  '1.50', 1),
    ('feature.trade_framer.adaptive_buffer_low_vol_base',   '0.80', 1),
    ('feature.trade_framer.adaptive_buffer_low_vol_slope_num', '0.20', 1),
    ('feature.trade_framer.adaptive_buffer_low_vol_slope_den', '0.30', 1),
    ('feature.trade_framer.adaptive_buffer_high_vol_slope_num', '0.35', 1),
    ('feature.trade_framer.adaptive_buffer_high_vol_slope_den', '0.50', 1),
    ('feature.trade_framer.adaptive_buffer_hurst_trend_threshold', '0.55', 1),
    ('feature.trade_framer.adaptive_buffer_hurst_mr_threshold',    '0.45', 1),
    ('feature.trade_framer.adaptive_buffer_hurst_tighten_rate',    '0.16', 1),
    ('feature.trade_framer.adaptive_buffer_garch_shock_threshold', '3.0',  1),
    ('feature.trade_framer.adaptive_buffer_garch_shock_mult',      '1.35', 1)
ON CONFLICT (config_key) DO UPDATE
    SET config_value = EXCLUDED.config_value,
        updated_at   = now();

-- -------------------------------------------------------------------------
-- config_history entries
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.trade_framer.adaptive_buffer_vol_ratio_min',       1, '0.70', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_vol_ratio_max',       1, '1.50', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_low_vol_base',        1, '0.80', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_low_vol_slope_num',   1, '0.20', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_low_vol_slope_den',   1, '0.30', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_high_vol_slope_num',  1, '0.35', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_high_vol_slope_den',  1, '0.50', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_hurst_trend_threshold', 1, '0.55', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_hurst_mr_threshold',  1, '0.45', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_hurst_tighten_rate',  1, '0.16', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_garch_shock_threshold', 1, '3.0', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient'),
(NOW(), 'feature.trade_framer.adaptive_buffer_garch_shock_mult',    1, '1.35', 'migration_147', 'Phase 132 A5 APR seed — adaptive buffer piecewise coefficient')
ON CONFLICT DO NOTHING;
