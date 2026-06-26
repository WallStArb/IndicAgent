-- Migration 173: context_features table + APR key for daily-cadence IC gate.
--
-- context_features: daily-cadence macro features (vix_z, flight_quality, yield_slope_z).
-- These features have the same value for all intraday bars of a calendar day.
-- Storing them separately prevents the IC engine from measuring artificial autocorrelation
-- (~78 identical observations per day for 5m TF) as if they were independent bar-level signals.
--
-- The empty-string sentinel convention for market-wide features (symbol='') avoids
-- PostgreSQL NULL != NULL behavior in unique constraints. Application code must
-- pass symbol='' for market-wide features.
--
-- APR key alpha.ic.min_obs_daily_features: lower observation gate for daily-cadence features.
-- Daily features have ~252 obs/year; the 20K intraday gate cannot be met with daily data.
-- 1000 obs ~ 4 years of trading days. [initial_estimate]

BEGIN;

-- context_features: one row per (feature_date, feature_name, symbol)
-- symbol DEFAULT '' is the empty-string sentinel for market-wide features
-- (VIX proxy, yield curve slope, flight-to-quality divergence).
-- symbol is non-empty for symbol-scoped context features (future use: earnings surprise, etc.).
CREATE TABLE IF NOT EXISTS context_features (
    feature_date   DATE                     NOT NULL,
    feature_name   TEXT                     NOT NULL,
    symbol         TEXT                     NOT NULL DEFAULT '',
    value          DOUBLE PRECISION         NOT NULL,
    source         TEXT                     NOT NULL CHECK (source IN ('ibkr', 'fred', 'derived')),
    computed_at    TIMESTAMPTZ              NOT NULL DEFAULT now(),
    PRIMARY KEY (feature_date, feature_name, symbol)
);

COMMENT ON TABLE context_features IS
    'Daily-cadence macro and context features. One row per (feature_date, feature_name, symbol). '
    'Market-wide features (VIX proxy, yield curve, flight-quality) use symbol='''' (empty string) '
    'as a sentinel to satisfy the NOT NULL PK constraint while expressing market-wide scope. '
    'IC engine JOINs this table with DISTINCT ON (DATE(fv.bar_ts)) to produce one IC observation '
    'per calendar day, avoiding the ~78x intraday duplication in feature_vectors for 5m TF.';

COMMENT ON COLUMN context_features.symbol IS
    'Empty string for market-wide features. Non-empty for symbol-scoped features (future use). '
    'NOT NULL DEFAULT '''' — empty string sentinel intentional for unique constraint correctness.';

-- Index for IC engine join pattern:
-- WHERE feature_name = $1 AND feature_date = DATE($bar_ts) AND symbol = ''
CREATE INDEX IF NOT EXISTS context_features_name_date
    ON context_features (feature_name, feature_date, symbol);

-- APR key: lower observation gate for daily-cadence features.
-- Daily features have ~252 obs/year; at 5 years = ~1260 obs. The 20K intraday gate
-- was calibrated for 5m bars (78 bars/day), not daily observation frequency, and
-- would permanently block measurement of daily-cadence features.
-- 1000 obs ~ 4 years of daily data. Tradeoff: lower statistical power, wider bootstrap CI,
-- higher type-II error risk vs. intraday features. [initial_estimate]
INSERT INTO config_schema (config_key, value_type, default_value, min_value, description)
VALUES (
    'alpha.ic.min_obs_daily_features',
    'integer',
    '1000',
    1.0,
    '[initial_estimate] Minimum independent observations for IC Sharpe gate applied exclusively '
    'to features sourced from context_features (daily cadence). Daily features have ~252 obs/year; '
    'this gate is ~4 years of history. Do NOT apply the intraday 20K gate to daily-cadence '
    'features — calibrated for different observation frequency. Not an ML learning target '
    '(depends on available history length, not model quality).'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.min_obs_daily_features', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
