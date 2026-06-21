-- Migration 155: feature_vectors hypertable, backfill_status, and APR keys.
--
-- Creates the Phase 137 persistence and control-plane foundation:
--   1. feature_vectors hypertable (41 total columns: 5 key + 36 non-key typed)
--   2. backfill_status checkpoint table (D-11)
--   3. feature.* APR keys (16 keys, config_schema + config_state)
--   4. alpha.vector.v1_quant.members APR key (D-03)
--
-- Column accounting:
--   5 key columns: symbol, tf, bar_ts, pipeline_version, regime_label_source
--     (regime is nullable metadata, not a key constraint column but among the 5 listed)
--   36 non-key typed columns: 35 feature floats + pipeline_version
--   Wait - pipeline_version is text NOT NULL, regime is text nullable.
--   Key columns by constraint: symbol, tf, bar_ts (PRIMARY KEY)
--   Plus regime_label_source (5th structural column), regime (6th nullable)
--   Total: 5 key/structural + 1 nullable regime + 35 features = 41 total
--
-- All inserts are idempotent: ON CONFLICT (config_key) DO NOTHING.
-- Safe to re-run.

-- -------------------------------------------------------------------------
-- Section 1: feature_vectors hypertable
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS feature_vectors (
    symbol              text             NOT NULL,
    tf                  text             NOT NULL,
    bar_ts              timestamptz      NOT NULL,
    pipeline_version    text             NOT NULL,
    regime              text,
    regime_label_source text             NOT NULL DEFAULT 'filtered'
                        CHECK (regime_label_source IN ('filtered', 'unknown')),

    -- Bar-level (14)
    momentum_z_5        double precision,
    momentum_z_20       double precision,
    range_position      double precision,
    bar_close_pos       double precision,
    gap_z               double precision,
    informed_flow       double precision,
    volume_z            double precision,
    ofi_z               double precision,
    cvd_slope_z         double precision,
    cmf                 double precision,
    rel_volume          double precision,
    vwap_dev_sigma      double precision,
    atr_z               double precision,
    vol_ratio           double precision,

    -- Session-level (4)
    poc_dist_atr        double precision,
    va_position         double precision,
    sr_support_dist     double precision,
    sr_resist_dist      double precision,

    -- Regime-level (7)
    hmm_regime_prob     double precision,
    hmm_entropy         double precision,
    hurst               double precision,
    shannon             double precision,
    garch_ratio         double precision,
    hma_slope_z         double precision,
    adx                 double precision,

    -- Cross-asset (3)
    vix_z               double precision,
    flight_quality      double precision,
    yield_slope_z       double precision,

    -- Calendar (5)
    in_ny_session       double precision,
    in_overlap          double precision,
    dow_sin             double precision,
    dow_cos             double precision,
    month_position      double precision,

    -- Cross-timeframe (3)
    ctf_momentum        double precision,
    ctf_vwap_align      double precision,
    ctf_regime_align    double precision,

    PRIMARY KEY (symbol, tf, bar_ts)
);

SELECT create_hypertable(
    'feature_vectors',
    'bar_ts',
    chunk_time_interval => INTERVAL '3 months',
    if_not_exists => TRUE
);

-- Enable columnstore/compression on the hypertable (TimescaleDB 2.x pattern).
-- Must run before add_compression_policy.
-- Idempotent: re-running ALTER TABLE SET on an already-compressed table is a no-op.
ALTER TABLE feature_vectors SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'bar_ts ASC'
);

SELECT add_compression_policy(
    'feature_vectors',
    INTERVAL '6 months',
    if_not_exists => TRUE
);

-- -------------------------------------------------------------------------
-- Section 2: backfill_status checkpoint table (D-11)
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS backfill_status (
    symbol          text        NOT NULL,
    tf              text        NOT NULL,
    status          text        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'complete', 'failed')),
    fetch_complete  boolean     NOT NULL DEFAULT false,
    rows_written    bigint,
    theoretical_max bigint,
    started_at      timestamptz,
    completed_at    timestamptz,
    error_msg       text,
    PRIMARY KEY (symbol, tf)
);

-- -------------------------------------------------------------------------
-- Section 3: config_schema entries for feature.* APR keys
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('feature.momentum.window_short',       'int', '5',   '[conventional] Short momentum lookback bars. ML learning target after sufficient IC data.'),
    ('feature.momentum.window_long',        'int', '20',  '[conventional] Long momentum lookback bars. ML learning target after sufficient IC data.'),
    ('feature.momentum.zscore_window',      'int', '252', '[conventional] Rolling z-score window for momentum, ~1 trading year. Not an ML learning target.'),
    ('feature.volume.zscore_window',        'int', '20',  '[conventional] Volume z-score rolling window. Not an ML learning target.'),
    ('feature.ofi.zscore_window',           'int', '20',  '[conventional] OFI z-score rolling window. Not an ML learning target.'),
    ('feature.cvd.slope_bars',              'int', '5',   '[conventional] CVD slope lookback bars. ML learning target after sufficient IC data.'),
    ('feature.cmf.period',                  'int', '20',  '[conventional] Chaikin Money Flow period. Not an ML learning target.'),
    ('feature.vol.short_bars',              'int', '5',   '[conventional] Short realized vol window bars. ML learning target.'),
    ('feature.vol.long_bars',               'int', '20',  '[conventional] Long realized vol window bars. ML learning target.'),
    ('feature.hma.period',                  'int', '20',  '[conventional] Hull MA period for hma_slope_z computation. Not an ML learning target.'),
    ('feature.adx.period',                  'int', '14',  '[conventional] ADX period. Not an ML learning target.'),
    ('feature.hurst.window',                'int', '252', '[conventional] Hurst R/S rolling window, ~1 trading year. Not an ML learning target.'),
    ('feature.garch.window',                'int', '100', '[initial_estimate] GARCH estimation window bars. ML learning target after sufficient IC data.'),
    ('feature.vix.zscore_window',           'int', '252', '[conventional] VIX z-score rolling window, ~1 trading year. Not an ML learning target.'),
    ('feature.yield_curve.zscore_window',   'int', '252', '[conventional] Yield curve z-score window, ~1 trading year. Not an ML learning target.'),
    ('feature.regime.cache_refresh_bars',   'int', '30',  '[initial_estimate] Regime feature recompute cadence in bars. Regime-level features (HMM, Hurst, Shannon, GARCH) are expensive; recompute every N bars and serve from cache. ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 4: config_state entries (seed values = defaults)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.momentum.window_short',       '5',   1),
    ('feature.momentum.window_long',        '20',  1),
    ('feature.momentum.zscore_window',      '252', 1),
    ('feature.volume.zscore_window',        '20',  1),
    ('feature.ofi.zscore_window',           '20',  1),
    ('feature.cvd.slope_bars',              '5',   1),
    ('feature.cmf.period',                  '20',  1),
    ('feature.vol.short_bars',              '5',   1),
    ('feature.vol.long_bars',               '20',  1),
    ('feature.hma.period',                  '20',  1),
    ('feature.adx.period',                  '14',  1),
    ('feature.hurst.window',                '252', 1),
    ('feature.garch.window',                '100', 1),
    ('feature.vix.zscore_window',           '252', 1),
    ('feature.yield_curve.zscore_window',   '252', 1),
    ('feature.regime.cache_refresh_bars',   '30',  1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- Section 5: alpha.vector.v1_quant.members (D-03)
-- Requires alpha. prefix in OPS_PREFIXES (handled in src/config/config_service.py).
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('alpha.vector.v1_quant.members', 'str',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     '[initial_estimate] V1 Quant vector constituent primitives. Mutable via APR. IC discovery may prune members.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('alpha.vector.v1_quant.members',
     'momentum_z_5,momentum_z_20,hma_slope_z,range_position,bar_close_pos,atr_z,vol_ratio,ctf_momentum',
     1)
ON CONFLICT (config_key) DO NOTHING;
