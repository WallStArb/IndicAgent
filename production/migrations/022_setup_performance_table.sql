-- Migration 022: setup_performance table for adaptive aggregator weights
-- Tracks per-setup win rate, avg pnl_r, sample size, and Sharpe ratio
-- from the rolling 30-day window of resolved signals.
-- Only setups with sample_size >= 30 appear here (promotion gate FEED-02).
-- timeframe and regime columns are nullable — reserved for future segmentation
-- when data volume justifies it.

CREATE TABLE IF NOT EXISTS setup_performance (
    setup_plugin    TEXT        NOT NULL,
    win_rate        FLOAT       NOT NULL,
    avg_pnl_r       FLOAT       NOT NULL,
    sample_size     INTEGER     NOT NULL,
    sharpe_ratio    FLOAT       NOT NULL,
    timeframe       TEXT        NULL,
    regime          TEXT        NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (setup_plugin)
);

COMMENT ON TABLE setup_performance IS
    'Per-setup rolling 30-day performance stats. '
    'Populated nightly by weight_updater job. '
    'Only rows with sample_size >= 30 (FEED-02 promotion gate).';
