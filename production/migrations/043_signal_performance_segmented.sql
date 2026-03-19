-- Migration: signal_performance_segmented
-- Phase 039-05 — Per-regime segmented signal performance stats with Information Coefficient
-- Renaissance principle: "A rule that works globally is weaker than one that works in a specific regime"
-- Populated by compute_ic.py; read by aggregator perf_multiplier

BEGIN;

CREATE TABLE IF NOT EXISTS signal_performance_segmented (
    id                   BIGSERIAL PRIMARY KEY,
    setup_plugin         TEXT        NOT NULL,
    timeframe            TEXT        NOT NULL,
    regime_type          TEXT        NOT NULL,  -- 'trend', 'mean_reversion', 'any', or actual regime label
    symbol               TEXT,                  -- NULL = all symbols (global); set = symbol-specific
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Rolling window
    window_days          INTEGER     NOT NULL DEFAULT 30,
    window_start         DATE        NOT NULL,
    window_end           DATE        NOT NULL,
    -- Sample statistics
    sample_size          INTEGER     NOT NULL,
    wins                 INTEGER     NOT NULL,
    win_rate             DOUBLE PRECISION,       -- wins / sample_size
    avg_pnl_r            DOUBLE PRECISION,       -- average R-multiple outcome
    -- Information Coefficient
    ic_score             DOUBLE PRECISION,       -- Pearson r(calibrated_confidence, binary_outcome)
    ic_p_value           DOUBLE PRECISION,       -- p-value from scipy.stats.pearsonr
    ic_n                 INTEGER,                -- sample size used for IC computation
    ic_significant       BOOLEAN                 -- ic_p_value < 0.05 AND ic_score >= 0.05 AND ic_n >= 30
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_sps_plugin_tf_regime
  ON signal_performance_segmented (setup_plugin, timeframe, regime_type, symbol, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_sps_latest
  ON signal_performance_segmented (computed_at DESC);

-- Only rows with sample_size >= 30 are written (FEED-02 gate, per CLAUDE.md)
-- Constraint enforces this invariant at DB level
ALTER TABLE signal_performance_segmented
  ADD CONSTRAINT chk_sps_sample_size CHECK (sample_size >= 30);

COMMENT ON TABLE signal_performance_segmented IS
  'Per-regime segmented signal performance stats with Information Coefficient. '
  'Written by compute_ic.py. Read by aggregator perf_multiplier. '
  'Only rows with sample_size >= 30 written (FEED-02 gate).';

COMMIT;
