-- Add compression policy to ml_signal_training (missed in Phase 104)
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/093_ml_signal_training_compression.sql

BEGIN;

ALTER TABLE ml_signal_training SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe, setup_plugin',
    timescaledb.compress_orderby = 'ts DESC'
);

-- Compress chunks older than 7 days (training data is write-once after signal resolution)
SELECT add_compression_policy('ml_signal_training', INTERVAL '7 days', if_not_exists => true);

COMMIT;
