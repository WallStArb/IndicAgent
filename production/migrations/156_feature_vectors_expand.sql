-- Migration 156: Expand feature_vectors from 36 to 54 feature columns.
--
-- Adds the 18 features defined in IC spec §VI.3 that were absent from migration 155:
--   Oscillators (6):             rsi_fast, rsi_mid, rsi_slow, cci_fast, cci_mid, cci_slow
--   Trend freshness (2):         aroon_fast, aroon_slow
--   Volume/flow (1):             ofi_div
--   HMM regime (1):              hmm_duration
--   Calendar/session (4):        in_london_kz, power_hour, opening_range, above_wk_vwap
--   Statistical/liquidity (4):   amihud_illiq_z, high_52w_dist, ret_skew_z, ret_acf1_z
--
-- After this migration: feature_vectors has 59 total columns
--   5 key/metadata: symbol, tf, bar_ts, pipeline_version, regime_label_source
--   1 nullable:     regime
--   54 features:    double precision (all nullable)
--
-- All statements are idempotent (IF NOT EXISTS / ON CONFLICT DO NOTHING).
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- Section 1: Add 18 new feature columns to feature_vectors
-- -------------------------------------------------------------------------

-- Volume/flow: ofi_div (after existing rel_volume column group)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ofi_div double precision;

-- Trend freshness (after existing adx)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS aroon_fast double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS aroon_slow double precision;

-- HMM regime: hmm_duration (after existing hmm_entropy)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS hmm_duration double precision;

-- Calendar/session (after existing month_position)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS in_london_kz double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS power_hour double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS opening_range double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS above_wk_vwap double precision;

-- Oscillators (new group)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_fast double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_mid double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_slow double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS cci_fast double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS cci_mid double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS cci_slow double precision;

-- Statistical/liquidity (new group, after cross-timeframe)
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS amihud_illiq_z double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS high_52w_dist double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_skew_z double precision;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ret_acf1_z double precision;

-- -------------------------------------------------------------------------
-- Section 2: Seed 14 new APR keys in config_schema
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('feature.period.rsi.fast',      'int', '7',   '[conventional] RSI fast period (half Wilder canonical). ML learning target after sufficient IC data.'),
    ('feature.period.rsi.mid',       'int', '14',  '[conventional] RSI mid period (Wilder canonical). ML learning target after sufficient IC data.'),
    ('feature.period.rsi.slow',      'int', '28',  '[conventional] RSI slow period (double of canonical). ML learning target after sufficient IC data.'),
    ('feature.period.cci.fast',      'int', '10',  '[initial_estimate] CCI fast period. ML learning target after sufficient IC data.'),
    ('feature.period.cci.mid',       'int', '20',  '[initial_estimate] CCI mid period. ML learning target after sufficient IC data.'),
    ('feature.period.cci.slow',      'int', '40',  '[initial_estimate] CCI slow period. ML learning target after sufficient IC data.'),
    ('feature.period.aroon.fast',    'int', '14',  '[initial_estimate] Aroon fast window. ML learning target after sufficient IC data.'),
    ('feature.period.aroon.slow',    'int', '25',  '[initial_estimate] Aroon slow window. ML learning target after sufficient IC data.'),
    ('feature.amihud.zscore_window', 'int', '252', '[conventional] Amihud illiquidity z-score window (~1 trading year). Not an ML learning target.'),
    ('feature.ret_skew.window',      'int', '60',  '[initial_estimate] Rolling window for return skewness computation. ML learning target.'),
    ('feature.ret_skew.zscore_window','int','252', '[conventional] Z-score window for return skewness (~1 trading year). Not an ML learning target.'),
    ('feature.ret_acf.window',       'int', '30',  '[initial_estimate] Rolling window for ACF lag-1 computation. ML learning target.'),
    ('feature.ret_acf.zscore_window','int', '252', '[conventional] Z-score window for ACF lag-1 (~1 trading year). Not an ML learning target.'),
    ('feature.high_52w.window',      'int', '252', '[conventional] 52-week high window (252 trading days). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 3: Seed 14 new APR keys in config_state
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.period.rsi.fast',       '7',   1),
    ('feature.period.rsi.mid',        '14',  1),
    ('feature.period.rsi.slow',       '28',  1),
    ('feature.period.cci.fast',       '10',  1),
    ('feature.period.cci.mid',        '20',  1),
    ('feature.period.cci.slow',       '40',  1),
    ('feature.period.aroon.fast',     '14',  1),
    ('feature.period.aroon.slow',     '25',  1),
    ('feature.amihud.zscore_window',  '252', 1),
    ('feature.ret_skew.window',       '60',  1),
    ('feature.ret_skew.zscore_window','252', 1),
    ('feature.ret_acf.window',        '30',  1),
    ('feature.ret_acf.zscore_window', '252', 1),
    ('feature.high_52w.window',       '252', 1)
ON CONFLICT (config_key) DO NOTHING;
