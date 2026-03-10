-- Core schema reconciliation and optimizations
-- Version: 2.1.0
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Ensure TimescaleDB is available
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Create core tables if missing (authoritative schema)
CREATE TABLE IF NOT EXISTS market_data_ohlcv (
  timestamp timestamptz NOT NULL,
  symbol text NOT NULL,
  timeframe text NOT NULL,
  open double precision NOT NULL,
  high double precision NOT NULL,
  low  double precision NOT NULL,
  close double precision NOT NULL,
  volume bigint NOT NULL,
  source text
);

CREATE TABLE IF NOT EXISTS technical_indicators (
  timestamp timestamptz NOT NULL,
  symbol text NOT NULL,
  timeframe text NOT NULL,
  indicator_name text NOT NULL,
  value double precision NOT NULL,
  source text
);

-- Unify OHLCV types to double precision (services cast to float)
DO $$
DECLARE
  need_alter boolean := false;
  chunk regclass;
BEGIN
  SELECT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'market_data_ohlcv'
      AND column_name IN ('open','high','low','close')
      AND data_type <> 'double precision'
  ) INTO need_alter;

  IF need_alter THEN
    -- Drop compression policy if present
    BEGIN
      PERFORM remove_compression_policy('market_data_ohlcv');
    EXCEPTION WHEN undefined_function THEN
      NULL;
    WHEN others THEN
      NULL;
    END;

    -- Decompress all chunks if any
    FOR chunk IN SELECT show_chunks('market_data_ohlcv') LOOP
      BEGIN
        PERFORM decompress_chunk(chunk);
      EXCEPTION WHEN others THEN
        NULL;
      END;
    END LOOP;

    -- Perform type changes
    EXECUTE '
      ALTER TABLE market_data_ohlcv
        ALTER COLUMN open  TYPE DOUBLE PRECISION USING open::DOUBLE PRECISION,
        ALTER COLUMN high  TYPE DOUBLE PRECISION USING high::DOUBLE PRECISION,
        ALTER COLUMN low   TYPE DOUBLE PRECISION USING low::DOUBLE PRECISION,
        ALTER COLUMN close TYPE DOUBLE PRECISION USING close::DOUBLE PRECISION
    ';
  END IF;
END$$;

-- Ensure unique indexes for upsert patterns (equivalent to unique constraints for ON CONFLICT)
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_data_ohlcv_ts_symbol_tf
  ON market_data_ohlcv (timestamp, symbol, timeframe);

CREATE UNIQUE INDEX IF NOT EXISTS uq_technical_indicators_ts_symbol_tf_name
  ON technical_indicators (timestamp, symbol, timeframe, indicator_name);

-- Drop unused metadata columns if present (services don't read/write them)
ALTER TABLE IF EXISTS technical_indicators
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE IF EXISTS trading_signals
  DROP COLUMN IF EXISTS metadata;

-- Ensure hypertables exist (idempotent)
SELECT create_hypertable('market_data_ohlcv', 'timestamp', if_not_exists => TRUE);
SELECT create_hypertable('technical_indicators', 'timestamp', if_not_exists => TRUE);

-- Helpful composite indexes for query patterns
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_time
  ON market_data_ohlcv (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_indicators_sym_tf_name_time
  ON technical_indicators (symbol, timeframe, indicator_name, timestamp DESC);

-- Enable compression and add policies safely (avoid duplicate policy errors)
ALTER TABLE IF EXISTS market_data_ohlcv SET (timescaledb.compress = TRUE);
ALTER TABLE IF EXISTS market_data_ohlcv SET (timescaledb.compress_orderby = 'timestamp DESC');
ALTER TABLE IF EXISTS market_data_ohlcv SET (timescaledb.compress_segmentby = 'symbol,timeframe');

ALTER TABLE IF EXISTS technical_indicators SET (timescaledb.compress = TRUE);
ALTER TABLE IF EXISTS technical_indicators SET (timescaledb.compress_orderby = 'timestamp DESC');
ALTER TABLE IF EXISTS technical_indicators SET (timescaledb.compress_segmentby = 'symbol,timeframe,indicator_name');

DO $$
BEGIN
  PERFORM add_compression_policy('market_data_ohlcv', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN
  -- Policy already exists; ignore
  NULL;
END$$;

DO $$
BEGIN
  PERFORM add_compression_policy('technical_indicators', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN
  NULL;
END$$;

-- Extend continuous aggregates beyond 5m as example (15m from 1m)
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_15m
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('15 minutes', timestamp) AS timestamp,
  symbol,
  '15m' AS timeframe,
  FIRST(open, timestamp)  AS open,
  MAX(high)               AS high,
  MIN(low)                AS low,
  LAST(close, timestamp)  AS close,
  SUM(volume)             AS volume,
  source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('15 minutes', timestamp), symbol, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_15m',
  start_offset => INTERVAL '1 hour',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists => TRUE
);


