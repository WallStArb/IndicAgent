-- Phase 104 Plan 04: ml_signal_training materialized store (typed columns, no JSONB)
-- Nightly populated by indicagent-ml-signal-training-materialize.timer
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f db/migrations/094_create_ml_signal_training.sql

CREATE TABLE IF NOT EXISTS ml_signal_training (
    -- Time dimension for hypertable
    ts                      timestamptz NOT NULL,
    signal_id               uuid        NOT NULL,
    symbol                  text        NOT NULL,
    timeframe               text        NOT NULL,
    setup_plugin            text        NOT NULL,

    -- Outcome labels (from signal_ledger)
    pnl_r                   float8,
    win_label               boolean,
    outcome                 text,

    -- Feature columns (from trading_signals JSONB, typed)
    existing_confidence     float8,
    ctf_score               float8,
    ctf_trend_alignment     float8,
    ctf_structure_alignment float8,
    ctf_regime_agreement    float8,
    ctf_fvg_alignment       float8,
    ctf_ob_alignment        float8,
    vix_level               float8,
    vix_z                   float8,
    eq_spread_z             float8,
    eq_pairs_confirming     float8,
    ctf_momentum_divergence float8,
    ctf_sr_confluence       float8,
    ctf_hmm_regime_agreement float8,
    ctf_volatility_divergence float8,
    ctf_orderflow_alignment float8,
    exhaustion_score        float8,

    -- Categorical (stored as text for simplicity; one-hot at training time)
    profile                 text,
    hmm_regime              int,
    session_type            text,

    -- Bar context (from intelligence_features)
    atr_pct                 float8,
    volume_z_score          float8,
    tod_multiplier          float8,

    -- Metadata
    signal_schema_version   text,
    materialized_at         timestamptz DEFAULT now(),

    PRIMARY KEY (ts, signal_id)
);

SELECT create_hypertable('ml_signal_training', 'ts', if_not_exists => true);

-- Compression: compress chunks after 7 days (hot data stays uncompressed for fast inserts)
SELECT add_compression_policy('ml_signal_training', INTERVAL '7 days', if_not_exists => true);

-- Retention: keep 1 year of training data (aligns with signal_ledger retention)
SELECT add_retention_policy('ml_signal_training', INTERVAL '1 year', if_not_exists => true);

-- Indexes for common query patterns (materialize agent lookups)
CREATE INDEX IF NOT EXISTS ml_signal_training_symbol_tf_idx ON ml_signal_training (symbol, timeframe);
CREATE INDEX IF NOT EXISTS ml_signal_training_outcome_idx ON ml_signal_training (outcome) WHERE outcome IS NOT NULL;
CREATE INDEX IF NOT EXISTS ml_signal_training_win_label_idx ON ml_signal_training (win_label) WHERE win_label IS NOT NULL;
