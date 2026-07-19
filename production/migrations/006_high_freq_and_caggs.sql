-- High-frequency optimizations and full multi-timeframe caggs
-- Version: 2.2.0
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Ensure TimescaleDB is available
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Chunk interval tuning
-- 4-hour chunks for OHLCV (higher write rates); keep 1-day for indicators
SELECT set_chunk_time_interval('market_data_ohlcv', INTERVAL '4 hours');
SELECT set_chunk_time_interval('technical_indicators', INTERVAL '1 day');

-- Add space partitioning by symbol to improve pruning (idempotent via exception handling)
DO $$
BEGIN
  PERFORM add_dimension('market_data_ohlcv', 'symbol', number_partitions => 8);
EXCEPTION WHEN others THEN
  NULL;
END$$;

DO $$
BEGIN
  PERFORM add_dimension('technical_indicators', 'symbol', number_partitions => 8);
EXCEPTION WHEN others THEN
  NULL;
END$$;

-- Continuous aggregates: 1h, 4h, 1d (sourced from 1m)
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1h
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', timestamp) AS timestamp,
  symbol,
  '1h' AS timeframe,
  FIRST(open, timestamp)  AS open,
  MAX(high)               AS high,
  MIN(low)                AS low,
  LAST(close, timestamp)  AS close,
  SUM(volume)             AS volume,
  source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('1 hour', timestamp), symbol, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1h',
  start_offset => INTERVAL '3 hours',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '5 minutes',
  if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_4h
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('4 hours', timestamp) AS timestamp,
  symbol,
  '4h' AS timeframe,
  FIRST(open, timestamp)  AS open,
  MAX(high)               AS high,
  MIN(low)                AS low,
  LAST(close, timestamp)  AS close,
  SUM(volume)             AS volume,
  source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('4 hours', timestamp), symbol, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_4h',
  start_offset => INTERVAL '12 hours',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '15 minutes',
  if_not_exists => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_1d
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', timestamp) AS timestamp,
  symbol,
  '1d' AS timeframe,
  FIRST(open, timestamp)  AS open,
  MAX(high)               AS high,
  MIN(low)                AS low,
  LAST(close, timestamp)  AS close,
  SUM(volume)             AS volume,
  source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('1 day', timestamp), symbol, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_1d',
  start_offset => INTERVAL '2 days',
  end_offset   => INTERVAL '0 minutes',
  schedule_interval => INTERVAL '1 hour',
  if_not_exists => TRUE
);


