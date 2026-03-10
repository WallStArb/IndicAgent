-- Version: 1.0.0
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Enable TimescaleDB (idempotent)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Convert tables to hypertables (time partition by timestamp; space partition by symbol)
SELECT create_hypertable('features', 'timestamp', 'symbol', number_partitions => 8, if_not_exists => TRUE);
SELECT create_hypertable('intelligence', 'timestamp', 'symbol', number_partitions => 8, if_not_exists => TRUE);

-- Enable native compression and add policies
ALTER TABLE features SET (timescaledb.compress = true);
ALTER TABLE intelligence SET (timescaledb.compress = true);

-- Compress chunks older than 7 days (tune per environment)
SELECT add_compression_policy('features', INTERVAL '7 days');
SELECT add_compression_policy('intelligence', INTERVAL '7 days');

-- Optional retention (uncomment and tune as needed)
-- SELECT add_retention_policy('features', INTERVAL '180 days');
-- SELECT add_retention_policy('intelligence', INTERVAL '365 days');


