-- Version: 1.0.0
-- Last Updated: 2025-08-08
-- Status: Optional (TimescaleDB) ✅

-- Uncomment if TimescaleDB extension is available
-- CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Features hypertable (time-partitioned)
-- SELECT create_hypertable('features', 'timestamp', if_not_exists => TRUE);

-- Intelligence hypertable (time-partitioned)
-- SELECT create_hypertable('intelligence', 'timestamp', if_not_exists => TRUE);


