-- TimescaleDB schema and policies (idempotent)
-- Version: 1.0.1
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Enable extension
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- OHLCV table
CREATE TABLE IF NOT EXISTS market_data_ohlcv (
  timestamp timestamptz NOT NULL,
  symbol text NOT NULL,
  timeframe text NOT NULL,
  open double precision NOT NULL,
  high double precision NOT NULL,
  low  double precision NOT NULL,
  close double precision NOT NULL,
  volume bigint NOT NULL,
  source text,
  UNIQUE (timestamp, symbol, timeframe)
);

SELECT create_hypertable('market_data_ohlcv','timestamp', if_not_exists => TRUE);

-- Helpful index for queries
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_tf_time ON market_data_ohlcv(symbol, timeframe, timestamp DESC);

CREATE TABLE IF NOT EXISTS technical_indicators (
  timestamp timestamptz NOT NULL,
  symbol text NOT NULL,
  timeframe text NOT NULL,
  indicator_name text NOT NULL,
  value double precision NOT NULL,
  source text,
  UNIQUE (timestamp, symbol, timeframe, indicator_name)
);

SELECT create_hypertable('technical_indicators','timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_indicators_sym_tf_name_time ON technical_indicators(symbol, timeframe, indicator_name, timestamp DESC);

ALTER TABLE market_data_ohlcv SET (timescaledb.compress = TRUE);
ALTER TABLE market_data_ohlcv SET (timescaledb.compress_orderby = 'timestamp DESC');
ALTER TABLE market_data_ohlcv SET (timescaledb.compress_segmentby = 'symbol,timeframe');

ALTER TABLE technical_indicators SET (timescaledb.compress = TRUE);
ALTER TABLE technical_indicators SET (timescaledb.compress_orderby = 'timestamp DESC');
ALTER TABLE technical_indicators SET (timescaledb.compress_segmentby = 'symbol,timeframe,indicator_name');

DO $$
BEGIN
  PERFORM add_compression_policy('market_data_ohlcv', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN
  NULL;
END$$;

DO $$
BEGIN
  PERFORM add_compression_policy('technical_indicators', INTERVAL '7 days');
EXCEPTION WHEN duplicate_object THEN
  NULL;
END$$;
