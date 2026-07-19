-- 5m and 15m TimescaleDB continuous aggregates
-- Version: 1.2.0
-- Added: 2026-02-21
--
-- These views auto-materialize as new 1m bars are inserted into market_data_ohlcv.
-- Python aggregate_1m_to_tf() is no longer needed for these timeframes.
-- 1h/4h/1d continuous aggregates already exist (migration 005).
--
-- Query: SELECT * FROM market_data_5m WHERE symbol = 'ESH6' ORDER BY timestamp DESC LIMIT 100;

-- 5-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', timestamp) AS timestamp,
    symbol,
    first(open, timestamp)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    last(close, timestamp)  AS close,
    sum(volume)             AS volume
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('5 minutes', timestamp), symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_data_5m',
    start_offset      => INTERVAL '2 hours',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => true);

-- 15-minute bars
CREATE MATERIALIZED VIEW IF NOT EXISTS market_data_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', timestamp) AS timestamp,
    symbol,
    first(open, timestamp)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    last(close, timestamp)  AS close,
    sum(volume)             AS volume
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('15 minutes', timestamp), symbol
WITH NO DATA;

SELECT add_continuous_aggregate_policy('market_data_15m',
    start_offset      => INTERVAL '2 hours',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => true);
