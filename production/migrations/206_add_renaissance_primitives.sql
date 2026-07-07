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

-- Plan 06 appends the schema-column and feature_registry sections below.

COMMIT;
