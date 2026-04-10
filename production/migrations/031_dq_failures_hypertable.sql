-- 031: Convert signal_metrics_dq_failures to hypertable with retention
-- Fixes: 43M duplicate rows from re-publishing every 15 min cycle
-- Adds: 30-day auto-retention, 7-day compression, dedup PK

-- 1. Drop old single-column PK (id-based, not useful)
ALTER TABLE signal_metrics_dq_failures DROP CONSTRAINT IF EXISTS signal_metrics_dq_failures_pkey;
ALTER TABLE signal_metrics_dq_failures DROP CONSTRAINT IF EXISTS dq_failures_pk;

-- 2. Truncate existing data (all duplicates from re-processing)
TRUNCATE signal_metrics_dq_failures;

-- 3. Add composite PK including partition column (dedup: same signal+reason only once per timestamp)
ALTER TABLE signal_metrics_dq_failures ADD PRIMARY KEY (signal_id, reason_code, created_at);

-- 4. Convert to hypertable partitioned on created_at
SELECT create_hypertable('signal_metrics_dq_failures', 'created_at', migrate_data => true);

-- 5. Enable compression (segment by reason_code for query patterns)
ALTER TABLE signal_metrics_dq_failures SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'reason_code',
  timescaledb.compress_orderby = 'created_at DESC'
);

-- 6. 30-day retention (auto-drop old chunks)
SELECT add_retention_policy('signal_metrics_dq_failures', INTERVAL '30 days');

-- 7. Compress chunks older than 7 days
SELECT add_compression_policy('signal_metrics_dq_failures', INTERVAL '7 days');
