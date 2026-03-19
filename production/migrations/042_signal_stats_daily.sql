-- Migration: signal_stats_daily materialized view
-- Phase 39 — DB foundation for fast win-rate aggregations
-- Powers IC calculation in Plan 05; enables O(1) win-rate queries per (setup_plugin, timeframe)

BEGIN;

-- Drop materialized view if exists (for idempotency during development)
DROP MATERIALIZED VIEW IF EXISTS signal_stats_daily;

-- Create materialized view: daily signal stats grouped by setup_plugin and timeframe
-- Aggregates: total_signals, wins, losses, win_rate, avg_pnl_r
-- Refresh strategy: REFRESH CONCURRENTLY allows non-blocking updates
CREATE MATERIALIZED VIEW signal_stats_daily AS
SELECT
    date_trunc('day', feature_ts) AS day,
    setup_plugin,
    timeframe,
    COUNT(*) AS total_signals,
    COUNT(*) FILTER (WHERE outcome IN ('target_1', 'target_1_2', 'target_full')) AS wins,
    COUNT(*) FILTER (WHERE outcome IN ('stopped_at_entry', 'stopped_in_trade', 'never_activated', 'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired')) AS losses,
    ROUND(
      CASE
        WHEN COUNT(*) > 0 THEN
          100.0 * COUNT(*) FILTER (WHERE outcome IN ('target_1', 'target_1_2', 'target_full'))::numeric / COUNT(*)
        ELSE NULL
      END,
      2
    ) AS win_rate_pct,
    ROUND(
      (AVG(pnl_r) FILTER (WHERE pnl_r IS NOT NULL))::numeric,
      4
    ) AS avg_pnl_r,
    ROUND(
      (AVG(pnl_r) FILTER (WHERE outcome IN ('target_1', 'target_1_2', 'target_full')))::numeric,
      4
    ) AS avg_win_pnl_r,
    ROUND(
      (AVG(pnl_r) FILTER (WHERE outcome IN ('stopped_at_entry', 'stopped_in_trade', 'never_activated', 'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired')))::numeric,
      4
    ) AS avg_loss_pnl_r,
    MAX(pnl_r) FILTER (WHERE outcome IN ('target_1', 'target_1_2', 'target_full')) AS max_win_pnl_r,
    MIN(pnl_r) FILTER (WHERE outcome IN ('stopped_at_entry', 'stopped_in_trade', 'never_activated', 'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired')) AS max_loss_pnl_r
FROM signal_ledger
WHERE feature_ts IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;

-- Create unique index on materialized view (required for REFRESH CONCURRENTLY)
CREATE UNIQUE INDEX IF NOT EXISTS idx_signal_stats_daily_day_plugin_tf
  ON signal_stats_daily (day, setup_plugin, timeframe);

-- Create indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_signal_stats_daily_plugin_tf
  ON signal_stats_daily (setup_plugin, timeframe, day DESC);

CREATE INDEX IF NOT EXISTS idx_signal_stats_daily_win_rate
  ON signal_stats_daily (setup_plugin, timeframe, win_rate_pct DESC)
  WHERE total_signals >= 30;  -- IC gate threshold

COMMIT;
