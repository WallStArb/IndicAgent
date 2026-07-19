-- Migration 171: market_regimes Table + APR Keys + Cross-Sectional IC Partial Index
--
-- Creates market_regimes: one cross-sectional equity regime label per (asset_class, tf, ts).
-- IC engine joins on (asset_class='equity', tf, DATE_TRUNC(tf_interval, bar_ts)).
-- Per-symbol HMM features (hmm_regime_prob etc.) remain in feature_vectors as signals.
--
-- Also adds feature_ic_scores_cross_sectional_uq partial index for cross-sectional
-- IC rows (symbol='POOLED', is_pooled=true) — these require regime in the conflict key
-- because there are multiple distinct regime_labels per
-- (feature_name, 'POOLED', tf, lookahead_bars, training_window_end).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. market_regimes table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS market_regimes (
    asset_class        TEXT        NOT NULL,
    tf                 TEXT        NOT NULL,
    ts                 TIMESTAMPTZ NOT NULL,
    regime_label       TEXT        NOT NULL,
    regime_prob_vector JSONB,
    PRIMARY KEY (asset_class, tf, ts)
);

COMMENT ON TABLE market_regimes IS
    'Cross-sectional equity regime label per (asset_class, tf, ts). '
    'One row per (tf, bar_timestamp) — not per symbol. '
    'IC engine joins here for regime segmentation when alpha.regime.equity_model_enabled=true. '
    'Per-symbol HMM labels remain in feature_vectors.regime for backward compat.';

COMMENT ON COLUMN market_regimes.regime_label IS
    'Composite label: {vix_bucket}_{breadth_signal}. '
    'vix_bucket: low | mid | high. breadth_signal: bull | neutral | bear. '
    'Example: low_bull, high_bear, mid_neutral.';

COMMENT ON COLUMN market_regimes.regime_prob_vector IS
    'Soft evidence dict: {vix_bucket, breadth_signal, vix_pct, breadth_frac}. '
    'Stored for diagnostics; not used in IC computation.';

-- ---------------------------------------------------------------------------
-- 2. Index for IC engine join pattern
-- ---------------------------------------------------------------------------

-- IC engine join: WHERE asset_class=''equity'' AND tf=$1 AND ts=$2
CREATE INDEX IF NOT EXISTS market_regimes_equity_tf_ts
    ON market_regimes (asset_class, tf, ts);

-- ---------------------------------------------------------------------------
-- 3. Partial index on feature_ic_scores for cross-sectional rows
-- ---------------------------------------------------------------------------

-- Cross-sectional pooling rows use: symbol='POOLED', is_pooled=true, regime=actual_regime_label.
-- The existing _POOLED_INSERT_SQL uses (feature_name, symbol, tf, lookahead_bars, training_window_end)
-- WHERE is_pooled=true -- this is per-symbol cross-REGIME pooling (symbol!=POOLED).
-- Cross-sectional rows (symbol='POOLED') need regime in the conflict key because there are
-- multiple distinct regime_labels per (feature_name, 'POOLED', tf, lookahead_bars, training_window_end).
CREATE UNIQUE INDEX IF NOT EXISTS feature_ic_scores_cross_sectional_uq
    ON feature_ic_scores (feature_name, symbol, tf, regime, lookahead_bars, training_window_end)
    WHERE is_pooled = true AND symbol = 'POOLED';

-- ---------------------------------------------------------------------------
-- 4. APR keys for equity regime model
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, description)
VALUES
  ('alpha.regime.vix_low_pct',
   'float',
   '[initial_estimate] VIX percentile threshold below which market is low-vol regime. '
   'Computed from SPY realized-vol z-score rolling percentile rank. '
   'Candidate ML learning target.'),
  ('alpha.regime.vix_high_pct',
   'float',
   '[initial_estimate] VIX percentile threshold above which market is high-vol regime. '
   'Computed from SPY realized-vol z-score rolling percentile rank. '
   'Candidate ML learning target.'),
  ('alpha.regime.breadth_bear',
   'float',
   '[initial_estimate] Fraction of equity ETFs above 200MA below which breadth is bearish. '
   'Computed from cross-sectional 200MA signal across all 58 equity ETFs. '
   'Candidate ML learning target.'),
  ('alpha.regime.breadth_bull',
   'float',
   '[initial_estimate] Fraction of equity ETFs above 200MA above which breadth is bullish. '
   'Computed from cross-sectional 200MA signal across all 58 equity ETFs. '
   'Candidate ML learning target.'),
  ('alpha.regime.equity_model_enabled',
   'bool',
   '[initial_estimate] If true, IC engine reads regime from market_regimes join AND '
   'computes cross-sectional pooled IC across all equity ETFs. '
   'If false, falls back to feature_vectors.regime and per-symbol IC only. '
   'Allows revert if cross-sectional model fails Phase 141 validation.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.regime.vix_low_pct',          '0.33',  1),
  ('alpha.regime.vix_high_pct',         '0.67',  1),
  ('alpha.regime.breadth_bear',         '0.40',  1),
  ('alpha.regime.breadth_bull',         '0.60',  1),
  ('alpha.regime.equity_model_enabled', 'true',  1)
ON CONFLICT (config_key) DO NOTHING;

COMMIT;
