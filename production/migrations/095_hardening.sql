-- Migration 095: Operational Hardening
-- Context: 213 GB dead-tuple bloat on 2026-05-21 from OOM kills aborting INSERT transactions.
-- Fixes: autovacuum tuning on feature_snapshots_shadow; compression on 4 uncompressed hypertables.
-- Idempotency: ALTER TABLE SET is safe to re-run; compression ALTER is idempotent if already set.

BEGIN;

-- feature_snapshots_shadow: 12 GB, high insert rate, no prior autovacuum tuning
ALTER TABLE feature_snapshots_shadow SET (
    autovacuum_vacuum_scale_factor  = 0.01,
    autovacuum_analyze_scale_factor = 0.005,
    autovacuum_vacuum_cost_delay    = 2
);

COMMIT;

-- Enable compression on hypertables missing it.
-- Must run outside transaction block.

ALTER TABLE signal_lineage SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

ALTER TABLE signal_transform_log SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'ts DESC',
    timescaledb.compress_segmentby = 'segment_key'
);

ALTER TABLE ctx_events SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'event_ts DESC',
    timescaledb.compress_segmentby = 'event_type'
);

ALTER TABLE alpha_multiplier_shadow SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'ts DESC',
    timescaledb.compress_segmentby = 'symbol'
);

-- Add compression policies: compress chunks older than 7 days
SELECT add_compression_policy('signal_lineage',        INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('signal_transform_log',  INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('ctx_events',            INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_compression_policy('alpha_multiplier_shadow', INTERVAL '7 days', if_not_exists => TRUE);
