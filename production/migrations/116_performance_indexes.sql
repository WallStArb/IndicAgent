-- Migration 116: performance indexes for Phase 121 replay + API query hot paths
--
-- Addresses four query patterns identified as bottlenecks:
--   1. setup_plugin filter/group-by on signal_ledger (full hypertable scan)
--   2. is_shadow=true filter (shadow validator, shadow view, orchestration)
--   3. regime_suppressed status not covered by existing partial index (lifecycle_replay seq scan)
--   4. Dedicated pending/suppressed index for lifecycle_replay work queue
--
-- Note: signal_ledger is a TimescaleDB hypertable — CONCURRENTLY is not supported.
-- signal_outcomes is a plain table — CONCURRENTLY is safe.

-- 1. setup_plugin on signal_ledger hypertable
--    Covers: WHERE setup_plugin = ANY(...), GROUP BY setup_plugin, COUNT per setup
CREATE INDEX IF NOT EXISTS idx_signal_ledger_setup_plugin
    ON signal_ledger (setup_plugin, timestamp DESC);

-- 2. is_shadow partial index — only shadow signals (small minority of rows)
--    Covers: signal_ledger_shadow view, shadow_validator, orchestration counts
CREATE INDEX IF NOT EXISTS idx_signal_ledger_shadow
    ON signal_ledger (setup_plugin, timestamp DESC)
    WHERE is_shadow = true;

-- 3. Extend signal_outcomes live index to include regime_suppressed.
--    Old index covered only ('pending', 'active') — lifecycle_replay.py queries
--    ('pending', 'regime_suppressed'), causing a full seq scan on 2.87M rows per batch.
DROP INDEX CONCURRENTLY IF EXISTS idx_signal_outcomes_live;
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_outcomes_live
    ON signal_outcomes (signal_id, status)
    WHERE status IN ('pending', 'active', 'regime_suppressed');

-- 4. Status-first index for lifecycle_replay work queue (COUNT GROUP BY symbol/tf)
--    and seeding queries that filter pending/suppressed before joining signal_ledger.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_outcomes_pending_suppressed
    ON signal_outcomes (status, signal_id)
    WHERE status IN ('pending', 'regime_suppressed');
