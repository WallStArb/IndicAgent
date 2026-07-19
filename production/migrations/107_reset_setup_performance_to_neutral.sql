-- Migration 107: reset contaminated setup_performance rows to neutral
--
-- DEVIATION FROM SPEC NOTE:
-- The original spec references a WHERE clause filtering on perf_multiplier and
-- signal_schema_version columns. Neither column exists on the live setup_performance
-- table (confirmed via \d setup_performance: columns are setup_plugin, win_rate,
-- avg_pnl_r, sample_size, sharpe_ratio, timeframe, regime, updated_at, direction, symbol).
--
-- EQUIVALENT NEUTRALIZATION:
-- The aggregator's perf_multiplier is NOT stored in this table — it is computed at
-- runtime by run_setup_performance_update() which queries WHERE sample_size >= 30.
-- Resetting sample_size = 0 removes every contaminated setup from the eligibility
-- query, so the computed multiplier defaults to neutral 1.0 until clean outcomes
-- re-accumulate. Setting win_rate, avg_pnl_r, sharpe_ratio to 0.0 ensures a
-- partial-recovery setup cannot rank on stale statistics.
--
-- ALL rows are pre-fix contaminated (no feature_schema_version filter possible);
-- reset without a WHERE clause is correct and intentional.

BEGIN;

UPDATE setup_performance
SET sample_size  = 0,
    win_rate     = 0.0,
    avg_pnl_r    = 0.0,
    sharpe_ratio = 0.0,
    updated_at   = now();

COMMIT;
