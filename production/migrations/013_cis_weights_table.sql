-- Create cis_weights table for adaptive weight learning
-- Version: 1.0.0
-- Last Updated: 2026-02-28
-- Status: Current
--
-- Purpose:
--   Stores versioned weight sets for the CIS bucket scorer.
--   version=1 is the bootstrap 'designed' row; higher versions are 'learned' rows.
--   Active weights = MAX(version) WHERE symbol = 'global'.
--   Per-symbol rows deferred until >=100 resolved signals per symbol.
--
-- Design decisions:
--   - Plain table (NOT hypertable) — version-keyed by integer, not time-series.
--   - Bootstrap row seeded in this migration — CIS aggregator always has fallback weights.
--   - threshold column allows per-version fire threshold tuning.

CREATE TABLE IF NOT EXISTS cis_weights (
    id                  SERIAL PRIMARY KEY,
    version             INTEGER NOT NULL,
    weights_type        TEXT NOT NULL CHECK (weights_type IN ('designed', 'learned', 'blended')),
    symbol              TEXT NOT NULL DEFAULT 'global',
    timeframe           TEXT NOT NULL DEFAULT 'global',
    trend_w             FLOAT NOT NULL,
    momentum_w          FLOAT NOT NULL,
    structure_w         FLOAT NOT NULL,
    pattern_w           FLOAT NOT NULL,
    institutional_w     FLOAT NOT NULL,
    regime_w            FLOAT NOT NULL,
    threshold           FLOAT NOT NULL DEFAULT 0.35,
    n_training_samples  INTEGER,
    signal_quality_mean FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_cis_weights_version_symbol
    ON cis_weights (version, symbol, timeframe);

-- Seed bootstrap designed weights (version=1)
-- These are active from day 1 until learned weights are ready.
-- Weights match BOOTSTRAP_WEIGHTS in src/intelligence/trading/cis_scorer.py.
INSERT INTO cis_weights (version, weights_type, symbol, timeframe,
    trend_w, momentum_w, structure_w, pattern_w, institutional_w, regime_w, threshold)
VALUES (1, 'designed', 'global', 'global', 0.20, 0.20, 0.15, 0.05, 0.25, 0.15, 0.35)
ON CONFLICT (version, symbol, timeframe) DO NOTHING;
