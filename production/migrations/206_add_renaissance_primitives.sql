-- Migration 206: Renaissance Primitives — Phase 142.5
--
-- Shared migration file across Plans 05, 05.5, and 06. Renumbered from the
-- incorrectly planned `db/migrations/177...` — the actual next available
-- migration number, after Phase 143's already-planned 202-205 reservations,
-- is 206. All active migrations live in production/migrations/ (db/migrations
-- only holds legacy 001/120/121).
--
-- This file is created by Plan 05 with the breakout-distance columns (14) and
-- APR seeds (10). Plans 05.5 and 06 append their own sections below — do not
-- assume this file is "done" until Plan 06's section lands (91 columns total,
-- 44 APR seeds, 91 feature_registry rows). See 142.5-PLAN-OUTLINE.md.
--
-- DEPLOYMENT GUARD (Round 2 review M2): do NOT apply this migration to any
-- database (dev, staging, or production) until Plan 06 has appended its
-- remaining columns/seeds/registry rows to this same file. Applying it after
-- Plan 05 alone leaves feature_registry / _REGISTRY_ROW_COUNT inconsistent
-- with the feature_vectors schema.
--
-- All ADD COLUMN statements use IF NOT EXISTS for idempotency. All APR seed
-- inserts use ON CONFLICT (config_key) DO NOTHING (config_schema) and
-- ON CONFLICT (config_key) DO NOTHING (config_state) — matching the exact
-- column signature and idempotency pattern of migration 200
-- (200_hmm_lifecycle_apr_keys.sql). changed_by/reason literals: 'migration-206'.

BEGIN;

-- ---------------------------------------------------------------------------
-- Plan 05: Breakout Distance (14 columns)
--
-- Price structure primitives with no theory: raw distance from recent
-- extremes, range position, and trend purity. Column names match the
-- FeatureVector dataclass field names exactly (src/intelligence/schemas.py).
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_high_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_high_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_low_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dist_from_low_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_pct_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_pct_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS new_high_flag DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS new_low_flag DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS stoch_k_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS stoch_k_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_percentile_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_percentile_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS efficiency_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS efficiency_ratio_slow DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.dist_from_high_fast IS
    'Distance from rolling high, ATR-normalized: (rolling_high_N - C) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.dist_from_high_slow IS
    'Distance from rolling high, ATR-normalized: (rolling_high_N - C) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_slow.';
COMMENT ON COLUMN feature_vectors.dist_from_low_fast IS
    'Distance from rolling low, ATR-normalized: (C - rolling_low_N) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.dist_from_low_slow IS
    'Distance from rolling low, ATR-normalized: (C - rolling_low_N) / ATR. '
    'Unbounded non-negative. APR: feature.breakout.dist_window_slow.';
COMMENT ON COLUMN feature_vectors.range_pct_fast IS
    'Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C. '
    'Unbounded non-negative. APR: feature.breakout.range_window_fast.';
COMMENT ON COLUMN feature_vectors.range_pct_slow IS
    'Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C. '
    'Unbounded non-negative. APR: feature.breakout.range_window_slow.';
COMMENT ON COLUMN feature_vectors.new_high_flag IS
    '1.0 if C == rolling_high_N (bar closed at the recent high), else 0.0. '
    'Binary {0,1}. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.new_low_flag IS
    '1.0 if C == rolling_low_N (bar closed at the recent low), else 0.0. '
    'Binary {0,1}. APR: feature.breakout.dist_window_fast.';
COMMENT ON COLUMN feature_vectors.stoch_k_fast IS
    'Stochastic %K: (C - L_N) / (H_N - L_N). Bounded [0,1]; 0.5 on degenerate '
    'range. APR: feature.breakout.stoch_window_fast.';
COMMENT ON COLUMN feature_vectors.stoch_k_slow IS
    'Stochastic %K: (C - L_N) / (H_N - L_N). Bounded [0,1]; 0.5 on degenerate '
    'range. APR: feature.breakout.stoch_window_slow.';
COMMENT ON COLUMN feature_vectors.price_percentile_fast IS
    'Rolling percentile rank of C_t within the trailing window. Bounded [0,1]. '
    'APR: feature.breakout.percentile_window_fast.';
COMMENT ON COLUMN feature_vectors.price_percentile_slow IS
    'Rolling percentile rank of C_t within the trailing window. Bounded [0,1]. '
    'APR: feature.breakout.percentile_window_slow.';
COMMENT ON COLUMN feature_vectors.efficiency_ratio_fast IS
    'Kaufman efficiency ratio: |C_t - C_t-N| / sum(|C_i - C_i-1|). Bounded '
    '[0,1] (0=chop, 1=linear trend). APR: feature.breakout.efficiency_window_fast.';
COMMENT ON COLUMN feature_vectors.efficiency_ratio_slow IS
    'Kaufman efficiency ratio: |C_t - C_t-N| / sum(|C_i - C_i-1|). Bounded '
    '[0,1] (0=chop, 1=linear trend). APR: feature.breakout.efficiency_window_slow.';

-- ---------------------------------------------------------------------------
-- Plan 05: Breakout Distance APR seeds (10 keys, feature.breakout.* namespace)
--
-- Provenance [conventional]: standard fast/slow lookback pairings matching
-- the existing rsi_fast/mid/slow, cci_fast/mid/slow, mfi_fast/slow
-- conventions already seeded in this codebase. Not ML learning targets at
-- seed time (initial conventional defaults); may become ML learning targets
-- once IC evaluation runs (deferred to a future corpus run per this phase's
-- scope). Column signature matches migration 200
-- (200_hmm_lifecycle_apr_keys.sql) exactly.
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.breakout.dist_window_fast',
    'int',
    '20',
    5, 100,
    '[conventional] Fast rolling window (bars) for dist_from_high/low_fast and new_high/low_flag. Not an ML learning target at seed time.'
),
(
    'feature.breakout.dist_window_slow',
    'int',
    '50',
    10, 300,
    '[conventional] Slow rolling window (bars) for dist_from_high/low_slow. Not an ML learning target at seed time.'
),
(
    'feature.breakout.range_window_fast',
    'int',
    '20',
    5, 100,
    '[conventional] Fast rolling window (bars) for range_pct_fast. Not an ML learning target at seed time.'
),
(
    'feature.breakout.range_window_slow',
    'int',
    '50',
    10, 300,
    '[conventional] Slow rolling window (bars) for range_pct_slow. Not an ML learning target at seed time.'
),
(
    'feature.breakout.stoch_window_fast',
    'int',
    '14',
    5, 100,
    '[conventional] Fast rolling window (bars) for stoch_k_fast (classic Stochastic %K period). Not an ML learning target at seed time.'
),
(
    'feature.breakout.stoch_window_slow',
    'int',
    '50',
    10, 300,
    '[conventional] Slow rolling window (bars) for stoch_k_slow. Not an ML learning target at seed time.'
),
(
    'feature.breakout.percentile_window_fast',
    'int',
    '50',
    10, 300,
    '[conventional] Fast rolling window (bars) for price_percentile_fast. Not an ML learning target at seed time.'
),
(
    'feature.breakout.percentile_window_slow',
    'int',
    '200',
    50, 1000,
    '[conventional] Slow rolling window (bars) for price_percentile_slow. Not an ML learning target at seed time.'
),
(
    'feature.breakout.efficiency_window_fast',
    'int',
    '10',
    3, 100,
    '[conventional] Fast rolling window (bars) for efficiency_ratio_fast (Kaufman ER). Not an ML learning target at seed time.'
),
(
    'feature.breakout.efficiency_window_slow',
    'int',
    '50',
    10, 300,
    '[conventional] Slow rolling window (bars) for efficiency_ratio_slow (Kaufman ER). Not an ML learning target at seed time.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.breakout.dist_window_fast',       '20',  1),
('feature.breakout.dist_window_slow',       '50',  1),
('feature.breakout.range_window_fast',      '20',  1),
('feature.breakout.range_window_slow',      '50',  1),
('feature.breakout.stoch_window_fast',      '14',  1),
('feature.breakout.stoch_window_slow',      '50',  1),
('feature.breakout.percentile_window_fast', '50',  1),
('feature.breakout.percentile_window_slow', '200', 1),
('feature.breakout.efficiency_window_fast', '10',  1),
('feature.breakout.efficiency_window_slow', '50',  1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Plan 06: Non-breakout APR seeds (44 keys, feature.* namespace)
--
-- Seeds one config_schema + config_state row for every FeatureFactoryConfig
-- field introduced by Plans 01-04 and 05.5 that is NOT already seeded by
-- Plan 05 (feature.breakout.* — 10 keys, seeded above). Column signature
-- copied verbatim from migration 200 (200_hmm_lifecycle_apr_keys.sql):
-- config_schema (config_key, value_type, default_value, min_value, max_value,
-- description); config_state (config_key, config_value, version). All
-- [conventional] or [initial_estimate] — not ML learning targets at seed
-- time (same posture as Plan 05's breakout keys); IC evaluation on a future
-- corpus run may promote any of these to ML learning targets.
--
-- Default provenance:
--   - Long-lookback ("annual") windows (252 bars ~ 1 trading year at 1d,
--     or a full year of session-relative bars): dollar_vol, vol_percentile,
--     obv, high_low_corr, vol_asymmetry, hv.ratio_window, ret_kurtosis
--     zscore_window, parkinson/garman_klass/yang_zhang zscore_window,
--     price_vol_corr.fast. price_vol_corr.slow doubles to 504 (2yr) per the
--     phase's fast/slow gradient-naming convention (feature.price_vol_corr.
--     fast=252 loaded in FeatureFactoryConfig; see feature_factory.py).
--   - Standard fast/slow oscillator-style pairs (14/28, matching existing
--     rsi_mid/slow=14/28 and cci conventions): mfi, vol_trend, up_vol_ratio.
--   - Standard fast/slow pairs (10/30, matching existing hv/realized_var/
--     variance_ratio triad): realized_var, variance_ratio, hv.
--   - bb_pct_b.fast/slow (20/50) matches the classic Bollinger Band(20)
--     period plus the same fast/slow ratio already used by
--     feature.breakout.dist_window_fast/slow (20/50).
--   - Single-window volume/volatility dynamics params with no explicit
--     spec default (vol_range_ratio, vol_persistence, vol_std, vol_of_vol)
--     use the same 20-bar conventional default as the sibling single-window
--     params already seeded in this codebase (cmf_period=20, hma_period=20).
--   - intraday_noise.window=78 is the exact bar count of one NY session at
--     5-minute resolution (390 min / 5 min = 78 bars) — the intraday-noise
--     ratio is defined "over session" per its formula, so this default keeps
--     the window aligned to one session by construction.
--   - ret_lag.fast/mid/slow (5/10/20) and overnight_gap.window (20) match
--     the identical fast/mid/slow triad already used by momentum_window_*
--     and Plan 05's breakout dist_window_fast=20.
--   - updown_ratio.fast/slow (20/60) and streak.window (20) match the
--     existing aroon_fast/slow (14/25)-style short/long convention scaled to
--     a monthly/quarterly lookback.
--   - vol_velocity.window=14 matches the existing rsi_mid/vol_trend.fast
--     scale (14 bars).
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.ret_lag.fast',
    'int',
    '5',
    1, 50,
    '[conventional] Fast lookback (bars) for ret_lag_fast: log(C_t / C_t-N). Not an ML learning target at seed time.'
),
(
    'feature.ret_lag.mid',
    'int',
    '10',
    2, 100,
    '[conventional] Mid lookback (bars) for ret_lag_mid. Not an ML learning target at seed time.'
),
(
    'feature.ret_lag.slow',
    'int',
    '20',
    5, 200,
    '[conventional] Slow lookback (bars) for ret_lag_slow. Not an ML learning target at seed time.'
),
(
    'feature.overnight_gap.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for overnight_gap_z z-score normalization. Not an ML learning target at seed time.'
),
(
    'feature.dollar_vol.window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling window (bars) for dollar_vol_z (annual-scale, V*C z-score). Not an ML learning target at seed time.'
),
(
    'feature.vol_range_ratio.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for vol_range_ratio normalization. Not an ML learning target at seed time.'
),
(
    'feature.vol_trend.fast',
    'int',
    '14',
    3, 50,
    '[conventional] Fast volume moving-average window for vol_trend_ratio. Not an ML learning target at seed time.'
),
(
    'feature.vol_trend.slow',
    'int',
    '28',
    10, 200,
    '[conventional] Slow volume moving-average window for vol_trend_ratio. Not an ML learning target at seed time.'
),
(
    'feature.up_vol_ratio.fast',
    'int',
    '14',
    3, 50,
    '[conventional] Fast window (bars) for up_vol_ratio_fast. Not an ML learning target at seed time.'
),
(
    'feature.up_vol_ratio.slow',
    'int',
    '28',
    10, 200,
    '[conventional] Slow window (bars) for up_vol_ratio_slow. Not an ML learning target at seed time.'
),
(
    'feature.vol_percentile.window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling window (bars) for vol_percentile rank (annual-scale). Not an ML learning target at seed time.'
),
(
    'feature.vol_persistence.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for vol_persistence lag-1 autocorrelation of volume. Not an ML learning target at seed time.'
),
(
    'feature.vol_std.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for vol_std_z (z-score of rolling std(V)). Not an ML learning target at seed time.'
),
(
    'feature.mfi.fast',
    'int',
    '14',
    3, 50,
    '[conventional] Fast period for Money Flow Index (mfi_fast). Not an ML learning target at seed time.'
),
(
    'feature.mfi.slow',
    'int',
    '28',
    10, 200,
    '[conventional] Slow period for Money Flow Index (mfi_slow). Not an ML learning target at seed time.'
),
(
    'feature.obv.window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling window (bars) for obv_z (annual-scale z-score of On-Balance Volume). Not an ML learning target at seed time.'
),
(
    'feature.ret_kurtosis.fast',
    'int',
    '30',
    10, 100,
    '[conventional] Fast rolling window (bars) for ret_kurtosis_z_fast excess-kurtosis estimate. Not an ML learning target at seed time.'
),
(
    'feature.ret_kurtosis.slow',
    'int',
    '90',
    30, 300,
    '[conventional] Slow rolling window (bars) for ret_kurtosis_z_slow excess-kurtosis estimate. Not an ML learning target at seed time.'
),
(
    'feature.ret_kurtosis.zscore_window',
    'int',
    '252',
    50, 500,
    '[conventional] Z-score normalization window (bars, annual-scale) for ret_kurtosis_z_fast/slow. Not an ML learning target at seed time.'
),
(
    'feature.updown_ratio.fast',
    'int',
    '20',
    5, 100,
    '[conventional] Fast window (bars) for updown_ratio_fast (count(up)/count(down)). Not an ML learning target at seed time.'
),
(
    'feature.updown_ratio.slow',
    'int',
    '60',
    20, 300,
    '[conventional] Slow window (bars) for updown_ratio_slow. Not an ML learning target at seed time.'
),
(
    'feature.streak.window',
    'int',
    '20',
    5, 100,
    '[conventional] Normalization window (bars) for streak_z (signed directional streak length z-score). Not an ML learning target at seed time.'
),
(
    'feature.realized_var.fast',
    'int',
    '10',
    3, 50,
    '[conventional] Fast window (bars) for realized_var_ratio_fast numerator variance. Not an ML learning target at seed time.'
),
(
    'feature.realized_var.slow',
    'int',
    '30',
    10, 150,
    '[conventional] Slow window (bars) for realized_var_ratio_fast/slow denominator variance. Not an ML learning target at seed time.'
),
(
    'feature.vol_of_vol.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for vol_of_vol (rolling std of atr_z). Not an ML learning target at seed time.'
),
(
    'feature.high_low_corr.window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling window (bars, annual-scale) for high_low_corr Pearson correlation of H and L. Not an ML learning target at seed time.'
),
(
    'feature.variance_ratio.fast',
    'int',
    '10',
    3, 50,
    '[conventional] Fast window (bars) for variance_ratio_fast (Lo-MacKinlay variance ratio). Not an ML learning target at seed time.'
),
(
    'feature.variance_ratio.slow',
    'int',
    '30',
    10, 150,
    '[conventional] Slow window (bars) for variance_ratio_slow. Not an ML learning target at seed time.'
),
(
    'feature.vol_asymmetry.window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling window (bars, annual-scale) for vol_asymmetry_z (std(ret|up)/std(ret|down) z-score). Not an ML learning target at seed time.'
),
(
    'feature.bb_pct_b.fast',
    'int',
    '20',
    5, 100,
    '[conventional] Fast Bollinger Band period (classic BB(20)) for bb_pct_b_fast. Not an ML learning target at seed time.'
),
(
    'feature.bb_pct_b.slow',
    'int',
    '50',
    10, 200,
    '[conventional] Slow Bollinger Band period for bb_pct_b_slow. Not an ML learning target at seed time.'
),
(
    'feature.hv.fast',
    'int',
    '10',
    3, 50,
    '[conventional] Fast window (bars) for hv_z_fast close-to-close historical volatility. Not an ML learning target at seed time.'
),
(
    'feature.hv.slow',
    'int',
    '30',
    10, 150,
    '[conventional] Slow window (bars) for hv_z_slow. Not an ML learning target at seed time.'
),
(
    'feature.hv.ratio_window',
    'int',
    '252',
    20, 500,
    '[conventional] Rolling mean window (bars, annual-scale) for hv_ratio (hv_fast / rolling_mean(hv, N)). Not an ML learning target at seed time.'
),
(
    'feature.parkinson_vol.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling-average window (bars) for parkinson_vol_z raw estimator. Not an ML learning target at seed time.'
),
(
    'feature.parkinson_vol.zscore_window',
    'int',
    '252',
    20, 500,
    '[conventional] Z-score normalization window (bars, annual-scale) for parkinson_vol_z. Not an ML learning target at seed time.'
),
(
    'feature.garman_klass_vol.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling-average window (bars) for garman_klass_vol_z raw estimator. Not an ML learning target at seed time.'
),
(
    'feature.garman_klass_vol.zscore_window',
    'int',
    '252',
    20, 500,
    '[conventional] Z-score normalization window (bars, annual-scale) for garman_klass_vol_z. Not an ML learning target at seed time.'
),
(
    'feature.yang_zhang_vol.window',
    'int',
    '20',
    5, 100,
    '[conventional] Rolling window (bars) for yang_zhang_vol_z raw variance estimator. Not an ML learning target at seed time.'
),
(
    'feature.yang_zhang_vol.zscore_window',
    'int',
    '252',
    20, 500,
    '[conventional] Z-score normalization window (bars, annual-scale) for yang_zhang_vol_z. Not an ML learning target at seed time.'
),
(
    'feature.vol_velocity.window',
    'int',
    '14',
    3, 50,
    '[conventional] Rolling window (bars) for vol_velocity_z (z-score of rolling atr_z velocity). Not an ML learning target at seed time.'
),
(
    'feature.intraday_noise.window',
    'int',
    '78',
    10, 200,
    '[conventional] Session window (bars) for intraday_noise_ratio — 78 = one NY session at 5-minute resolution (390min/5min). Not an ML learning target at seed time.'
),
(
    'feature.price_vol_corr.fast',
    'int',
    '252',
    20, 500,
    '[conventional] Fast rolling window (bars, annual-scale) for price_vol_corr_fast Pearson(|log ret|, volume). Not an ML learning target at seed time.'
),
(
    'feature.price_vol_corr.slow',
    'int',
    '504',
    50, 1000,
    '[conventional] Slow rolling window (bars, 2yr-scale) for price_vol_corr_slow. Not an ML learning target at seed time.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.ret_lag.fast',                  '5',   1),
('feature.ret_lag.mid',                   '10',  1),
('feature.ret_lag.slow',                  '20',  1),
('feature.overnight_gap.window',          '20',  1),
('feature.dollar_vol.window',             '252', 1),
('feature.vol_range_ratio.window',       '20',  1),
('feature.vol_trend.fast',                '14',  1),
('feature.vol_trend.slow',                '28',  1),
('feature.up_vol_ratio.fast',             '14',  1),
('feature.up_vol_ratio.slow',             '28',  1),
('feature.vol_percentile.window',        '252', 1),
('feature.vol_persistence.window',       '20',  1),
('feature.vol_std.window',                '20',  1),
('feature.mfi.fast',                      '14',  1),
('feature.mfi.slow',                      '28',  1),
('feature.obv.window',                    '252', 1),
('feature.ret_kurtosis.fast',             '30',  1),
('feature.ret_kurtosis.slow',             '90',  1),
('feature.ret_kurtosis.zscore_window',   '252', 1),
('feature.updown_ratio.fast',             '20',  1),
('feature.updown_ratio.slow',             '60',  1),
('feature.streak.window',                 '20',  1),
('feature.realized_var.fast',             '10',  1),
('feature.realized_var.slow',             '30',  1),
('feature.vol_of_vol.window',            '20',  1),
('feature.high_low_corr.window',         '252', 1),
('feature.variance_ratio.fast',           '10',  1),
('feature.variance_ratio.slow',           '30',  1),
('feature.vol_asymmetry.window',         '252', 1),
('feature.bb_pct_b.fast',                 '20',  1),
('feature.bb_pct_b.slow',                 '50',  1),
('feature.hv.fast',                       '10',  1),
('feature.hv.slow',                       '30',  1),
('feature.hv.ratio_window',              '252', 1),
('feature.parkinson_vol.window',          '20',  1),
('feature.parkinson_vol.zscore_window', '252', 1),
('feature.garman_klass_vol.window',       '20',  1),
('feature.garman_klass_vol.zscore_window', '252', 1),
('feature.yang_zhang_vol.window',         '20',  1),
('feature.yang_zhang_vol.zscore_window', '252', 1),
('feature.vol_velocity.window',           '14',  1),
('feature.intraday_noise.window',         '78',  1),
('feature.price_vol_corr.fast',          '252', 1),
('feature.price_vol_corr.slow',          '504', 1)
ON CONFLICT (config_key) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Plan 06: Non-breakout feature_vectors columns (77 columns)
--
-- Column names match src.intelligence.schemas.FeatureVector field names
-- exactly. All DOUBLE PRECISION, nullable, IF NOT EXISTS for idempotency.
-- Grouped by category to mirror the dataclass field order.
-- ---------------------------------------------------------------------------

-- Bar Anatomy Ratios (8, Phase 142.5 Plan 01)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS body_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS upper_wick_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS lower_wick_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_vs_atr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS close_vs_open_direction DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS overnight_gap DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS overnight_gap_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_efficiency DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.body_ratio IS '(C - O) / (H - L), bounded [-1, 1]. Directional conviction of the bar.';
COMMENT ON COLUMN feature_vectors.upper_wick_ratio IS '(H - max(O,C)) / (H - L), bounded [0, 1].';
COMMENT ON COLUMN feature_vectors.lower_wick_ratio IS '(min(O,C) - L) / (H - L), bounded [0, 1].';
COMMENT ON COLUMN feature_vectors.range_vs_atr IS '(H - L) / ATR_N, unbounded non-negative.';
COMMENT ON COLUMN feature_vectors.close_vs_open_direction IS 'sign(C - O), categorical {-1, 0, 1}.';
COMMENT ON COLUMN feature_vectors.overnight_gap IS '(O - prev_C) / prev_C, unbounded. APR: feature.overnight_gap.window (via overnight_gap_z).';
COMMENT ON COLUMN feature_vectors.overnight_gap_z IS 'Z-score of overnight_gap. APR: feature.overnight_gap.window.';
COMMENT ON COLUMN feature_vectors.range_efficiency IS 'abs(C - prev_C) / (H - L), bounded [0, 1].';

-- Lagged Return Series (6, Phase 142.5 Plan 01)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_1 DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_2 DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_3 DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_mid DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_lag_slow DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.ret_lag_1 IS 'log(C_t / C_t-1), definitional.';
COMMENT ON COLUMN feature_vectors.ret_lag_2 IS 'log(C_t / C_t-2), definitional.';
COMMENT ON COLUMN feature_vectors.ret_lag_3 IS 'log(C_t / C_t-3), definitional.';
COMMENT ON COLUMN feature_vectors.ret_lag_fast IS 'log(C_t / C_t-N). APR: feature.ret_lag.fast.';
COMMENT ON COLUMN feature_vectors.ret_lag_mid IS 'log(C_t / C_t-N). APR: feature.ret_lag.mid.';
COMMENT ON COLUMN feature_vectors.ret_lag_slow IS 'log(C_t / C_t-N). APR: feature.ret_lag.slow.';

-- Open-to-Close Split (4, Phase 142.5 Plan 01)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS open_ret DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS intraday_ret DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS open_vs_intraday DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS session_time_pos DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.open_ret IS 'log(O_t / prev_C), overnight component, unbounded.';
COMMENT ON COLUMN feature_vectors.intraday_ret IS 'log(C_t / O_t), intraday component, unbounded.';
COMMENT ON COLUMN feature_vectors.open_vs_intraday IS 'open_ret - intraday_ret, unbounded.';
COMMENT ON COLUMN feature_vectors.session_time_pos IS 'Continuous [0, 1] position within the NY session.';

-- Temporal Coordinates: new sin/cos pairs + month_sin/cos (10, Phase 142.5 Plan 02)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hour_of_day_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hour_of_day_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS week_of_month_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS week_of_month_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS day_of_month_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS day_of_month_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS week_of_year_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS week_of_year_cos DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS month_sin DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS month_cos DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.hour_of_day_sin IS 'sin(2*pi*(hour+minute/60)/24), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.hour_of_day_cos IS 'cos(2*pi*(hour+minute/60)/24), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.week_of_month_sin IS 'sin(2*pi*week/5), week=(day-1)//7+1, bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.week_of_month_cos IS 'cos(2*pi*week/5), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.day_of_month_sin IS 'sin(2*pi*day/31), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.day_of_month_cos IS 'cos(2*pi*day/31), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.week_of_year_sin IS 'sin(2*pi*isocalendar_week/52), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.week_of_year_cos IS 'cos(2*pi*isocalendar_week/52), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.month_sin IS 'sin(2*pi*month/12), bounded [-1, 1].';
COMMENT ON COLUMN feature_vectors.month_cos IS 'cos(2*pi*month/12), bounded [-1, 1].';

-- Volume Structure (12, Phase 142.5 Plan 02)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_acceleration DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS dollar_vol_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_range_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_trend_ratio DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS up_vol_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS up_vol_ratio_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_percentile DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_persistence DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_std_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS mfi_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS mfi_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS obv_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.vol_acceleration IS 'V_t / V_t-1, unbounded positive.';
COMMENT ON COLUMN feature_vectors.dollar_vol_z IS 'Z-score of (V*C). APR: feature.dollar_vol.window.';
COMMENT ON COLUMN feature_vectors.vol_range_ratio IS 'V_t / (H-L) normalized over N. APR: feature.vol_range_ratio.window.';
COMMENT ON COLUMN feature_vectors.vol_trend_ratio IS 'vol_MA_fast / vol_MA_slow. APR: feature.vol_trend.fast/.slow.';
COMMENT ON COLUMN feature_vectors.up_vol_ratio_fast IS 'sum(V|C>O)/sum(V), bounded [0,1]. APR: feature.up_vol_ratio.fast.';
COMMENT ON COLUMN feature_vectors.up_vol_ratio_slow IS 'sum(V|C>O)/sum(V), bounded [0,1]. APR: feature.up_vol_ratio.slow.';
COMMENT ON COLUMN feature_vectors.vol_percentile IS 'Rolling percentile rank of V_t, bounded [0,1]. APR: feature.vol_percentile.window.';
COMMENT ON COLUMN feature_vectors.vol_persistence IS 'Lag-1 autocorrelation of V, bounded [-1,1]. APR: feature.vol_persistence.window.';
COMMENT ON COLUMN feature_vectors.vol_std_z IS 'Z-score of rolling std(V). APR: feature.vol_std.window.';
COMMENT ON COLUMN feature_vectors.mfi_fast IS 'Money Flow Index, bounded [0,100]. APR: feature.mfi.fast.';
COMMENT ON COLUMN feature_vectors.mfi_slow IS 'Money Flow Index, bounded [0,100]. APR: feature.mfi.slow.';
COMMENT ON COLUMN feature_vectors.obv_z IS 'Z-score of On-Balance Volume. APR: feature.obv.window.';

-- Return Distribution (7, Phase 142.5 Plan 03)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_kurtosis_z_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_kurtosis_z_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_autocorr_1 DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_autocorr_5 DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS updown_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS updown_ratio_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS streak_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.ret_kurtosis_z_fast IS 'Z-score of rolling excess kurtosis. APR: feature.ret_kurtosis.fast.';
COMMENT ON COLUMN feature_vectors.ret_kurtosis_z_slow IS 'Z-score of rolling excess kurtosis. APR: feature.ret_kurtosis.slow.';
COMMENT ON COLUMN feature_vectors.ret_autocorr_1 IS 'Lag-1 Pearson autocorrelation of log returns, bounded [-1,1], definitional.';
COMMENT ON COLUMN feature_vectors.ret_autocorr_5 IS 'Lag-5 Pearson autocorrelation of log returns, bounded [-1,1], definitional.';
COMMENT ON COLUMN feature_vectors.updown_ratio_fast IS 'count(up)/count(down) returns, unbounded non-neg. APR: feature.updown_ratio.fast.';
COMMENT ON COLUMN feature_vectors.updown_ratio_slow IS 'count(up)/count(down) returns, unbounded non-neg. APR: feature.updown_ratio.slow.';
COMMENT ON COLUMN feature_vectors.streak_z IS 'Z-score of signed directional streak length. APR: feature.streak.window.';

-- Realized Variance / Volatility (14, Phase 142.5 Plan 03)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS realized_var_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS realized_var_ratio_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_to_close DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS true_range_pct DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_of_vol DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS high_low_corr DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS variance_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS variance_ratio_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_asymmetry_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bb_pct_b_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS bb_pct_b_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hv_z_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hv_z_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hv_ratio DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.realized_var_ratio_fast IS 'var(ret,fast)/var(ret,slow), unbounded non-neg. APR: feature.realized_var.fast/slow.';
COMMENT ON COLUMN feature_vectors.realized_var_ratio_slow IS 'var(ret,fast)/var(ret,slow), unbounded non-neg. APR: feature.realized_var.fast/slow.';
COMMENT ON COLUMN feature_vectors.range_to_close IS '(H-L)/C, unbounded non-neg, no APR.';
COMMENT ON COLUMN feature_vectors.true_range_pct IS 'TR/C, unbounded non-neg, no APR.';
COMMENT ON COLUMN feature_vectors.vol_of_vol IS 'Z-score of rolling std(atr_z). APR: feature.vol_of_vol.window.';
COMMENT ON COLUMN feature_vectors.high_low_corr IS 'Correlation of H and L, bounded [-1,1]. APR: feature.high_low_corr.window.';
COMMENT ON COLUMN feature_vectors.variance_ratio_fast IS 'Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk. APR: feature.variance_ratio.fast.';
COMMENT ON COLUMN feature_vectors.variance_ratio_slow IS 'Lo-MacKinlay VR, unbounded non-neg, ~1.0 under random walk. APR: feature.variance_ratio.slow.';
COMMENT ON COLUMN feature_vectors.vol_asymmetry_z IS 'Z-score of std(ret|up)/std(ret|down). APR: feature.vol_asymmetry.window.';
COMMENT ON COLUMN feature_vectors.bb_pct_b_fast IS '(C-lower_band)/(upper_band-lower_band). APR: feature.bb_pct_b.fast.';
COMMENT ON COLUMN feature_vectors.bb_pct_b_slow IS '(C-lower_band)/(upper_band-lower_band). APR: feature.bb_pct_b.slow.';
COMMENT ON COLUMN feature_vectors.hv_z_fast IS 'Z-score of close-to-close historical volatility. APR: feature.hv.fast.';
COMMENT ON COLUMN feature_vectors.hv_z_slow IS 'Z-score of close-to-close historical volatility. APR: feature.hv.slow.';
COMMENT ON COLUMN feature_vectors.hv_ratio IS 'hv_fast / rolling_mean(hv, N), unbounded non-neg. APR: feature.hv.ratio_window.';

-- Alternative Volatility Estimators (3, Phase 142.5 Plan 04)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS parkinson_vol_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS garman_klass_vol_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS yang_zhang_vol_z DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.parkinson_vol_z IS 'Z-score of rolling-avg ln(H/L)^2/(4ln2). APR: feature.parkinson_vol.window/.zscore_window.';
COMMENT ON COLUMN feature_vectors.garman_klass_vol_z IS 'Z-score of rolling-avg GK term. APR: feature.garman_klass_vol.window/.zscore_window.';
COMMENT ON COLUMN feature_vectors.yang_zhang_vol_z IS 'Z-score of rolling YZ variance estimator. APR: feature.yang_zhang_vol.window/.zscore_window.';

-- Volatility Dynamics (5, Phase 142.5 Plan 04)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS parkinson_vol_velocity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS garman_klass_vol_velocity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS yang_zhang_vol_velocity DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_velocity_z DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS intraday_noise_ratio DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.parkinson_vol_velocity IS 'parkinson_vol_z_t - parkinson_vol_z_t-1, unbounded, no APR.';
COMMENT ON COLUMN feature_vectors.garman_klass_vol_velocity IS 'garman_klass_vol_z_t - garman_klass_vol_z_t-1, unbounded, no APR.';
COMMENT ON COLUMN feature_vectors.yang_zhang_vol_velocity IS 'yang_zhang_vol_z_t - yang_zhang_vol_z_t-1, unbounded, no APR.';
COMMENT ON COLUMN feature_vectors.vol_velocity_z IS 'Z-score of rolling atr_z velocity. APR: feature.vol_velocity.window.';
COMMENT ON COLUMN feature_vectors.intraday_noise_ratio IS 'sum(|ret|)/|net_ret| over session, unbounded non-neg. APR: feature.intraday_noise.window.';

-- Price-Volume Interactions (8, Phase 142.5 Plan 05.5)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_body_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_vol_product_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_vol_corr_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS price_vol_corr_slow DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS range_vol_product DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS up_vol_body_diff DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_vol_ratio_fast DOUBLE PRECISION;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS vol_skew_product DOUBLE PRECISION;

COMMENT ON COLUMN feature_vectors.vol_body_product IS 'body_ratio * volume_z, unbounded symmetric around 0, no APR.';
COMMENT ON COLUMN feature_vectors.ret_vol_product_fast IS 'ret_lag_fast * volume_z, unbounded symmetric around 0, no APR.';
COMMENT ON COLUMN feature_vectors.price_vol_corr_fast IS 'Rolling Pearson(|log ret|, volume), bounded [-1,1]. APR: feature.price_vol_corr.fast.';
COMMENT ON COLUMN feature_vectors.price_vol_corr_slow IS 'Rolling Pearson(|log ret|, volume), bounded [-1,1]. APR: feature.price_vol_corr.slow.';
COMMENT ON COLUMN feature_vectors.range_vol_product IS 'range_vs_atr * volume_z, unbounded symmetric around 0, no APR.';
COMMENT ON COLUMN feature_vectors.up_vol_body_diff IS 'up_vol_ratio_fast - body_ratio, approx bounded [-1,1], no APR.';
COMMENT ON COLUMN feature_vectors.ret_vol_ratio_fast IS 'ret_lag_fast / atr_z, unbounded symmetric around 0, no APR.';
COMMENT ON COLUMN feature_vectors.vol_skew_product IS 'ret_skew_z * volume_z, unbounded symmetric around 0, no APR.';

-- ---------------------------------------------------------------------------
-- Plan 06: feature_registry seeding (91 rows — all Renaissance primitives,
-- including Plan 05's 14 breakout-distance columns; this is the single
-- registry-seeding home for the whole phase).
--
-- Column signature matches migration 172 (172_feature_registry.sql):
-- (feature_name, group_name, tier, formula_short, normalization,
--  linear_ready, requires_htf, status, added_phase).
-- group_name restricted to the CHECK vocab (momentum, volume, volatility,
-- structure, session, oscillator, calendar, cross_tf, macro, regime) — never
-- "quant" (that label lives only in the separate FEATURE_VECTOR_DOMAIN dict).
-- status='active', added_phase='142.5', requires_htf=false (Cross-TF
-- divergences explicitly deferred per 142.5-PLAN-OUTLINE.md Scope Decisions).
-- The 8 Price-Volume Interaction rows are tier='1_interaction' with
-- parent_features arrays populated so the cascade-deprecation trigger
-- (fn_cascade_parent_deprecation) can auto-demote them if a parent tier-0
-- feature is later deprecated.
-- ---------------------------------------------------------------------------

INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase)
VALUES
-- Bar Anatomy Ratios (8) — structure, 0_atomic
('body_ratio',                'structure', '0_atomic', '(C-O)/(H-L)',                                   'bounded_signed',  true,  false, 'active', '142.5'),
('upper_wick_ratio',          'structure', '0_atomic', '(H-max(O,C))/(H-L)',                             'bounded_unsigned',true, false, 'active', '142.5'),
('lower_wick_ratio',          'structure', '0_atomic', '(min(O,C)-L)/(H-L)',                             'bounded_unsigned',true, false, 'active', '142.5'),
('range_vs_atr',              'structure', '0_atomic', '(H-L)/ATR_N',                                    'unbounded_ratio', false, false, 'active', '142.5'),
('close_vs_open_direction',   'structure', '0_atomic', 'sign(C-O)',                                       'bounded_signed',  true,  false, 'active', '142.5'),
('overnight_gap',             'structure', '0_atomic', '(O-prev_C)/prev_C',                              'unbounded_ratio', false, false, 'active', '142.5'),
('overnight_gap_z',           'structure', '0_atomic', 'z-score of overnight_gap',                        'z_scored',        true,  false, 'active', '142.5'),
('range_efficiency',          'structure', '0_atomic', 'abs(C-prev_C)/(H-L)',                            'bounded_unsigned',true, false, 'active', '142.5'),
-- Lagged Return Series (6) — momentum, 0_atomic
('ret_lag_1',                 'momentum', '0_atomic', 'log(C_t/C_t-1)',                                  'unbounded_ratio', false, false, 'active', '142.5'),
('ret_lag_2',                 'momentum', '0_atomic', 'log(C_t/C_t-2)',                                  'unbounded_ratio', false, false, 'active', '142.5'),
('ret_lag_3',                 'momentum', '0_atomic', 'log(C_t/C_t-3)',                                  'unbounded_ratio', false, false, 'active', '142.5'),
('ret_lag_fast',              'momentum', '0_atomic', 'log(C_t/C_t-N) fast',                             'unbounded_ratio', false, false, 'active', '142.5'),
('ret_lag_mid',               'momentum', '0_atomic', 'log(C_t/C_t-N) mid',                              'unbounded_ratio', false, false, 'active', '142.5'),
('ret_lag_slow',              'momentum', '0_atomic', 'log(C_t/C_t-N) slow',                             'unbounded_ratio', false, false, 'active', '142.5'),
-- Open-to-Close Split (4) — structure/calendar, 0_atomic
('open_ret',                  'structure', '0_atomic', 'log(O_t/prev_C)',                                'unbounded_ratio', false, false, 'active', '142.5'),
('intraday_ret',              'structure', '0_atomic', 'log(C_t/O_t)',                                   'unbounded_ratio', false, false, 'active', '142.5'),
('open_vs_intraday',          'structure', '0_atomic', 'open_ret - intraday_ret',                        'unbounded_ratio', false, false, 'active', '142.5'),
('session_time_pos',          'calendar', '0_atomic', 'continuous [0,1] position within NY session',    'bounded_unsigned',true, false, 'active', '142.5'),
-- Temporal Coordinates + month_sin/cos (10) — calendar, 0_atomic
('hour_of_day_sin',           'calendar', '0_atomic', 'sin(2pi*(hour+min/60)/24)',                       'bounded_signed',  true,  false, 'active', '142.5'),
('hour_of_day_cos',           'calendar', '0_atomic', 'cos(2pi*(hour+min/60)/24)',                       'bounded_signed',  true,  false, 'active', '142.5'),
('week_of_month_sin',         'calendar', '0_atomic', 'sin(2pi*week/5)',                                 'bounded_signed',  true,  false, 'active', '142.5'),
('week_of_month_cos',         'calendar', '0_atomic', 'cos(2pi*week/5)',                                 'bounded_signed',  true,  false, 'active', '142.5'),
('day_of_month_sin',          'calendar', '0_atomic', 'sin(2pi*day/31)',                                 'bounded_signed',  true,  false, 'active', '142.5'),
('day_of_month_cos',          'calendar', '0_atomic', 'cos(2pi*day/31)',                                 'bounded_signed',  true,  false, 'active', '142.5'),
('week_of_year_sin',          'calendar', '0_atomic', 'sin(2pi*isoweek/52)',                              'bounded_signed',  true,  false, 'active', '142.5'),
('week_of_year_cos',          'calendar', '0_atomic', 'cos(2pi*isoweek/52)',                              'bounded_signed',  true,  false, 'active', '142.5'),
('month_sin',                 'calendar', '0_atomic', 'sin(2pi*month/12)',                               'bounded_signed',  true,  false, 'active', '142.5'),
('month_cos',                 'calendar', '0_atomic', 'cos(2pi*month/12)',                               'bounded_signed',  true,  false, 'active', '142.5'),
-- Volume Structure (12) — volume, 0_atomic
('vol_acceleration',          'volume', '0_atomic', 'V_t/V_t-1',                                          'unbounded_ratio', false, false, 'active', '142.5'),
('dollar_vol_z',              'volume', '0_atomic', 'z-score of (V*C)',                                   'z_scored',        true,  false, 'active', '142.5'),
('vol_range_ratio',           'volume', '0_atomic', 'V_t/(H-L) normalized over N',                        'unbounded_ratio', false, false, 'active', '142.5'),
('vol_trend_ratio',           'volume', '0_atomic', 'vol_MA_fast/vol_MA_slow',                            'unbounded_ratio', false, false, 'active', '142.5'),
('up_vol_ratio_fast',         'volume', '0_atomic', 'sum(V|C>O)/sum(V) fast',                             'bounded_unsigned',true, false, 'active', '142.5'),
('up_vol_ratio_slow',         'volume', '0_atomic', 'sum(V|C>O)/sum(V) slow',                             'bounded_unsigned',true, false, 'active', '142.5'),
('vol_percentile',            'volume', '0_atomic', 'rolling percentile rank of V_t',                     'bounded_unsigned',true, false, 'active', '142.5'),
('vol_persistence',           'volume', '0_atomic', 'lag-1 autocorrelation of V',                         'bounded_signed',  true,  false, 'active', '142.5'),
('vol_std_z',                 'volume', '0_atomic', 'z-score of rolling std(V)',                          'z_scored',        true,  false, 'active', '142.5'),
('mfi_fast',                  'volume', '0_atomic', 'Money Flow Index fast',                              'bounded_unsigned',true, false, 'active', '142.5'),
('mfi_slow',                  'volume', '0_atomic', 'Money Flow Index slow',                              'bounded_unsigned',true, false, 'active', '142.5'),
('obv_z',                     'volume', '0_atomic', 'z-score of OBV',                                     'z_scored',        true,  false, 'active', '142.5'),
-- Return Distribution (7) — momentum (autocorr) / volatility (rest), 0_atomic
('ret_kurtosis_z_fast',       'volatility', '0_atomic', 'z-score of rolling excess kurtosis fast',       'z_scored',        true,  false, 'active', '142.5'),
('ret_kurtosis_z_slow',       'volatility', '0_atomic', 'z-score of rolling excess kurtosis slow',       'z_scored',        true,  false, 'active', '142.5'),
('ret_autocorr_1',            'momentum', '0_atomic', 'lag-1 Pearson autocorrelation of log returns',    'bounded_signed',  true,  false, 'active', '142.5'),
('ret_autocorr_5',            'momentum', '0_atomic', 'lag-5 Pearson autocorrelation of log returns',    'bounded_signed',  true,  false, 'active', '142.5'),
('updown_ratio_fast',         'volatility', '0_atomic', 'count(up)/count(down) fast',                    'unbounded_ratio', false, false, 'active', '142.5'),
('updown_ratio_slow',         'volatility', '0_atomic', 'count(up)/count(down) slow',                    'unbounded_ratio', false, false, 'active', '142.5'),
('streak_z',                  'volatility', '0_atomic', 'z-score of signed directional streak length',   'z_scored',        true,  false, 'active', '142.5'),
-- Realized Variance / Volatility (14) — volatility, 0_atomic
('realized_var_ratio_fast',   'volatility', '0_atomic', 'var(ret,fast)/var(ret,slow)',                   'unbounded_ratio', false, false, 'active', '142.5'),
('realized_var_ratio_slow',   'volatility', '0_atomic', 'var(ret,fast)/var(ret,slow)',                   'unbounded_ratio', false, false, 'active', '142.5'),
('range_to_close',            'volatility', '0_atomic', '(H-L)/C',                                       'unbounded_ratio', false, false, 'active', '142.5'),
('true_range_pct',            'volatility', '0_atomic', 'TR/C',                                          'unbounded_ratio', false, false, 'active', '142.5'),
('vol_of_vol',                'volatility', '0_atomic', 'z-score of rolling std(atr_z)',                 'z_scored',        true,  false, 'active', '142.5'),
('high_low_corr',              'volatility', '0_atomic', 'correlation of H and L',                        'bounded_signed',  true,  false, 'active', '142.5'),
('variance_ratio_fast',       'volatility', '0_atomic', 'Lo-MacKinlay VR fast, ~1.0 under random walk',  'unbounded_ratio', false, false, 'active', '142.5'),
('variance_ratio_slow',       'volatility', '0_atomic', 'Lo-MacKinlay VR slow, ~1.0 under random walk',  'unbounded_ratio', false, false, 'active', '142.5'),
('vol_asymmetry_z',           'volatility', '0_atomic', 'z-score of std(ret|up)/std(ret|down)',          'z_scored',        true,  false, 'active', '142.5'),
('bb_pct_b_fast',             'volatility', '0_atomic', '(C-lower_band)/(upper_band-lower_band) fast',   'bounded_unsigned',true, false, 'active', '142.5'),
('bb_pct_b_slow',             'volatility', '0_atomic', '(C-lower_band)/(upper_band-lower_band) slow',   'bounded_unsigned',true, false, 'active', '142.5'),
('hv_z_fast',                 'volatility', '0_atomic', 'z-score of close-to-close HV fast',             'z_scored',        true,  false, 'active', '142.5'),
('hv_z_slow',                 'volatility', '0_atomic', 'z-score of close-to-close HV slow',             'z_scored',        true,  false, 'active', '142.5'),
('hv_ratio',                  'volatility', '0_atomic', 'hv_fast / rolling_mean(hv, N)',                  'unbounded_ratio', false, false, 'active', '142.5'),
-- Alternative Volatility Estimators (3) — volatility, 0_atomic
('parkinson_vol_z',           'volatility', '0_atomic', 'z-score of rolling-avg ln(H/L)^2/(4ln2)',       'z_scored',        true,  false, 'active', '142.5'),
('garman_klass_vol_z',        'volatility', '0_atomic', 'z-score of rolling-avg Garman-Klass term',      'z_scored',        true,  false, 'active', '142.5'),
('yang_zhang_vol_z',          'volatility', '0_atomic', 'z-score of rolling Yang-Zhang variance',        'z_scored',        true,  false, 'active', '142.5'),
-- Volatility Dynamics (5) — volatility, 0_atomic
('parkinson_vol_velocity',    'volatility', '0_atomic', 'parkinson_vol_z_t - parkinson_vol_z_t-1',       'unbounded_ratio', false, false, 'active', '142.5'),
('garman_klass_vol_velocity', 'volatility', '0_atomic', 'garman_klass_vol_z_t - garman_klass_vol_z_t-1', 'unbounded_ratio', false, false, 'active', '142.5'),
('yang_zhang_vol_velocity',   'volatility', '0_atomic', 'yang_zhang_vol_z_t - yang_zhang_vol_z_t-1',     'unbounded_ratio', false, false, 'active', '142.5'),
('vol_velocity_z',            'volatility', '0_atomic', 'z-score of rolling atr_z velocity',             'z_scored',        true,  false, 'active', '142.5'),
('intraday_noise_ratio',      'volatility', '0_atomic', 'sum(|ret|)/|net_ret| over session',             'unbounded_ratio', false, false, 'active', '142.5'),
-- Breakout Distance (14) — structure, 0_atomic (Phase 142.5 Plan 05)
('dist_from_high_fast',       'structure', '0_atomic', '(rolling_high-C)/ATR fast',                     'unbounded_ratio', false, false, 'active', '142.5'),
('dist_from_high_slow',       'structure', '0_atomic', '(rolling_high-C)/ATR slow',                     'unbounded_ratio', false, false, 'active', '142.5'),
('dist_from_low_fast',        'structure', '0_atomic', '(C-rolling_low)/ATR fast',                      'unbounded_ratio', false, false, 'active', '142.5'),
('dist_from_low_slow',        'structure', '0_atomic', '(C-rolling_low)/ATR slow',                      'unbounded_ratio', false, false, 'active', '142.5'),
('range_pct_fast',            'structure', '0_atomic', '(rolling_high-rolling_low)/C fast',             'unbounded_ratio', false, false, 'active', '142.5'),
('range_pct_slow',            'structure', '0_atomic', '(rolling_high-rolling_low)/C slow',             'unbounded_ratio', false, false, 'active', '142.5'),
('new_high_flag',             'structure', '0_atomic', '1.0 if C==rolling_high else 0.0',                'bounded_unsigned',true, false, 'active', '142.5'),
('new_low_flag',              'structure', '0_atomic', '1.0 if C==rolling_low else 0.0',                 'bounded_unsigned',true, false, 'active', '142.5'),
('stoch_k_fast',              'structure', '0_atomic', '(C-L_N)/(H_N-L_N) fast',                        'bounded_unsigned',true, false, 'active', '142.5'),
('stoch_k_slow',              'structure', '0_atomic', '(C-L_N)/(H_N-L_N) slow',                        'bounded_unsigned',true, false, 'active', '142.5'),
('price_percentile_fast',     'structure', '0_atomic', 'rolling percentile rank of C fast',             'bounded_unsigned',true, false, 'active', '142.5'),
('price_percentile_slow',     'structure', '0_atomic', 'rolling percentile rank of C slow',             'bounded_unsigned',true, false, 'active', '142.5'),
('efficiency_ratio_fast',     'structure', '0_atomic', 'Kaufman ER fast (0=chop,1=trend)',               'bounded_unsigned',true, false, 'active', '142.5'),
('efficiency_ratio_slow',     'structure', '0_atomic', 'Kaufman ER slow (0=chop,1=trend)',               'bounded_unsigned',true, false, 'active', '142.5')
ON CONFLICT (feature_name) DO NOTHING;

-- Price-Volume Interactions (8) — volume, 1_interaction, parent_features set
-- (separate INSERT so parent_features TEXT[] literals stay readable)
INSERT INTO feature_registry
    (feature_name, group_name, tier, formula_short, normalization, linear_ready,
     requires_htf, status, added_phase, parent_features)
VALUES
('vol_body_product',      'volume', '1_interaction', 'body_ratio * volume_z',                 'unbounded_ratio', false, false, 'active', '142.5', ARRAY['body_ratio', 'volume_z']),
('ret_vol_product_fast',  'volume', '1_interaction', 'ret_lag_fast * volume_z',                'unbounded_ratio', false, false, 'active', '142.5', ARRAY['ret_lag_fast', 'volume_z']),
('price_vol_corr_fast',   'volume', '1_interaction', 'rolling Pearson(|log ret|, volume) fast', 'bounded_signed',  true,  false, 'active', '142.5', ARRAY['ret_lag_1', 'volume_z']),
('price_vol_corr_slow',   'volume', '1_interaction', 'rolling Pearson(|log ret|, volume) slow', 'bounded_signed',  true,  false, 'active', '142.5', ARRAY['ret_lag_1', 'volume_z']),
('range_vol_product',     'volume', '1_interaction', 'range_vs_atr * volume_z',                'unbounded_ratio', false, false, 'active', '142.5', ARRAY['range_vs_atr', 'volume_z']),
('up_vol_body_diff',      'volume', '1_interaction', 'up_vol_ratio_fast - body_ratio',         'bounded_signed',  true,  false, 'active', '142.5', ARRAY['up_vol_ratio_fast', 'body_ratio']),
('ret_vol_ratio_fast',    'volume', '1_interaction', 'ret_lag_fast / atr_z',                   'unbounded_ratio', false, false, 'active', '142.5', ARRAY['ret_lag_fast', 'atr_z']),
('vol_skew_product',      'volume', '1_interaction', 'ret_skew_z * volume_z',                  'unbounded_ratio', false, false, 'active', '142.5', ARRAY['ret_skew_z', 'volume_z'])
ON CONFLICT (feature_name) DO NOTHING;

COMMIT;
