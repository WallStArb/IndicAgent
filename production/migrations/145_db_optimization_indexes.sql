-- Migration 145: Database optimization indexes from audit (2026-06-17)
--
-- Findings addressed:
--
-- HIGH: idx_signal_events_signal_id
--   UPDATE signal_events SET status = ... WHERE signal_id = $1 (lifecycle hot path)
--   has no secondary index on signal_id alone. TimescaleDB hypertable partitioned by ts
--   means a signal_id-only WHERE causes a full cross-chunk scan on every lifecycle sweep.
--   Fix: secondary index on signal_id so updates hit a single chunk.
--   (Long-term: thread signal_ts into every UPDATE call to use the PK directly.)
--
-- MEDIUM: idx_signal_events_status_symbol_tf_ts (partial)
--   /signals/active uses DISTINCT ON (symbol, tf) ... WHERE status IN ('pending','active')
--   ORDER BY symbol, tf, ts DESC. Existing idx_signal_events_symbol_tf_ts (migration 140)
--   lacks status as a leading column, so status filter is a post-index recheck over all rows.
--   Partial index on the live-signal subset (tiny fraction of total) makes this index-only.
--
-- MEDIUM: idx_trade_frames_was_selected_signal_ts (partial, time-range)
--   Dashboard /signals/stats, /signals/edge-series aggregate on was_selected=TRUE with a
--   time range. Existing idx_trade_frames_selected_pnl (was_selected, pnl) serves the
--   ML training path but not signal_ts time-range queries. New partial index on signal_ts
--   for the selected subset supports the dashboard aggregate scan.
--
-- MEDIUM: idx_ctx_snapshots_symbol_tf
--   feature_repository hot-path subquery: SELECT jsonb_object_agg(...) FROM ctx_snapshots
--   WHERE (symbol = $2 OR symbol IS NULL) AND tf = $3. Existing index is
--   (symbol, valid_from, valid_to) — tf is not indexed. The tf post-filter scans all
--   symbol rows. This index eliminates the post-filter.

BEGIN;

-- HIGH: lifecycle UPDATE path — secondary index on signal_id
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_signal_id
    ON signal_events (signal_id);

-- MEDIUM: /signals/active DISTINCT ON (symbol, tf) with status pre-filter
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_events_status_symbol_tf_ts
    ON signal_events (status, symbol, tf, ts DESC)
    WHERE status IN ('pending', 'active', 'regime_suppressed');

-- MEDIUM: dashboard was_selected=TRUE time-range aggregates
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_trade_frames_was_selected_signal_ts
    ON trade_frames (signal_ts DESC)
    WHERE was_selected = TRUE;

-- MEDIUM: ctx_snapshots hot-path subquery tf filter
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ctx_snapshots_symbol_tf
    ON ctx_snapshots (symbol, tf);

COMMIT;
