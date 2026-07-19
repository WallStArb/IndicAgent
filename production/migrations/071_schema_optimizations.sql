-- 065_schema_optimizations.sql
-- Schema optimization pass: compression, hypertable conversion, index cleanup.
--
-- Changes:
--   1. Enable compression on signal_ledger with proper segmentby/orderby
--   2. Enable compression on service_health_events with proper segmentby/orderby
--   3. Convert signal_metrics_dq_failures to hypertable + 90-day retention policy
--   4. Drop redundant indexes (covered by composite indexes on same tables)

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. signal_ledger compression
--    539MB hypertable; policy (job 1019) was configured but compression was
--    never enabled, making the policy a no-op.
--    Segment by (symbol, timeframe) matches all query patterns.
-- ---------------------------------------------------------------------------
ALTER TABLE signal_ledger SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby   = 'timestamp DESC'
);

-- ---------------------------------------------------------------------------
-- 2. service_health_events compression
--    Same issue — compression policy exists but compression_enabled = false.
--    Segment by service; event_type has low cardinality so leave in orderby.
-- ---------------------------------------------------------------------------
ALTER TABLE service_health_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'service',
    timescaledb.compress_orderby   = 'ts DESC'
);

-- Add a compression policy (30 days, same as drift_monitor)
-- Use if_not_exists for idempotency (migration can be safely rerun)
SELECT add_compression_policy('service_health_events', INTERVAL '30 days', if_not_exists => true);

-- ---------------------------------------------------------------------------
-- 3. signal_metrics_dq_failures → hypertable
--    Plain table growing at ~200k rows/day. Converting to hypertable on
--    created_at enables compression and retention. 51MB currently — safe to
--    migrate in place (no chunk data to move).
--    Retention: 90 days (3 months of DQ audit history is sufficient).
--
--    TimescaleDB requires the partitioning column to be part of any unique
--    index. Drop the existing PK and recreate with created_at included.
--    (signal_id, reason_code, created_at) is still a valid uniqueness key —
--    a given signal can only fail a given reason_code once at a given time.
-- ---------------------------------------------------------------------------
ALTER TABLE signal_metrics_dq_failures DROP CONSTRAINT signal_metrics_dq_failures_pkey;
ALTER TABLE signal_metrics_dq_failures ADD PRIMARY KEY (signal_id, reason_code, created_at);

SELECT create_hypertable(
    'signal_metrics_dq_failures',
    'created_at',
    chunk_time_interval => INTERVAL '7 days',
    migrate_data        => true
);

ALTER TABLE signal_metrics_dq_failures SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'setup_plugin, reason_code',
    timescaledb.compress_orderby   = 'created_at DESC'
);

SELECT add_compression_policy('signal_metrics_dq_failures', INTERVAL '7 days');
SELECT add_retention_policy('signal_metrics_dq_failures', INTERVAL '90 days');

-- ---------------------------------------------------------------------------
-- 4. Drop redundant indexes
--    service_health_events: bare ts DESC index is covered by both composite
--    indexes (service+ts and event_type+ts) — no query benefits from it alone.
--    intelligence_metrics: bare measured_at DESC is covered by the composite
--    (symbol, timeframe, measured_at DESC) for any selective query; a table
--    scan is used for unfiltered "latest" anyway due to tiny row count.
-- ---------------------------------------------------------------------------
DROP INDEX IF EXISTS service_health_events_ts_idx;
DROP INDEX IF EXISTS intelligence_metrics_measured_at_idx;

COMMIT;
