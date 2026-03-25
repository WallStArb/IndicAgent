-- intelligence_metrics hypertable — audit metrics for Renaissance validation
-- Version: 1.0.0
-- Created: 2026-03-25
-- Purpose: Persist computational correctness, cross-tier consistency, and latency metrics

CREATE TABLE IF NOT EXISTS intelligence_metrics (
    id SERIAL,
    measured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,

    -- Computational correctness metrics (validated against reference implementations)
    i1_rsi_correct BOOLEAN,
    i1_macd_correct BOOLEAN,
    i1_atr_correct BOOLEAN,
    i4_volatility_correct BOOLEAN,
    i4_regime_correct BOOLEAN,
    i4_vwap_correct BOOLEAN,
    i6_confluence_correct BOOLEAN,
    i7_signal_logic_correct BOOLEAN,

    -- Cross-tier consistency metrics
    i1_i4_correlation FLOAT,
    i6_i7_completeness FLOAT,
    i4_i7_regime_agreement FLOAT,

    -- Data quality metrics
    null_count INT,
    nan_count INT,
    out_of_bounds_count INT,

    -- Metadata
    audit_version TEXT DEFAULT '1.0',

    PRIMARY KEY (measured_at, id)
);

-- Convert to hypertable for time-series optimization
SELECT create_hypertable('intelligence_metrics', 'measured_at', if_not_exists => TRUE);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_intel_metrics_sym_tf_ts
    ON intelligence_metrics (symbol, timeframe, measured_at DESC);

-- Compression policy (compress data older than 30 days)
DO $$ BEGIN
  PERFORM add_compression_policy('intelligence_metrics', INTERVAL '30 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- Retention policy: keep data for 1 year
DO $$ BEGIN
  PERFORM add_retention_policy('intelligence_metrics', INTERVAL '1 year', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;
