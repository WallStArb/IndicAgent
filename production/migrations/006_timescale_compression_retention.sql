-- Version: 1.0.0
-- Last Updated: 2025-08-09
-- Status: Current ✅

-- Ensure TimescaleDB is enabled
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Enable compression with segment/order keys and add policies
-- Market OHLCV
ALTER TABLE IF EXISTS market_data_ohlcv
  SET (timescaledb.compress = true,
       timescaledb.compress_segmentby = 'symbol,timeframe',
       timescaledb.compress_orderby = 'timestamp');
SELECT add_compression_policy('market_data_ohlcv', INTERVAL '7 days');

-- Technical Indicators
ALTER TABLE IF EXISTS technical_indicators
  SET (timescaledb.compress = true,
       timescaledb.compress_segmentby = 'symbol,timeframe,indicator_name',
       timescaledb.compress_orderby = 'timestamp');
SELECT add_compression_policy('technical_indicators', INTERVAL '7 days');

-- Trading Signals
ALTER TABLE IF EXISTS trading_signals
  SET (timescaledb.compress = true,
       timescaledb.compress_segmentby = 'symbol,timeframe,signal_type',
       timescaledb.compress_orderby = 'timestamp');
SELECT add_compression_policy('trading_signals', INTERVAL '7 days');

-- Retention policies for base tables
SELECT add_retention_policy('market_data_ohlcv', INTERVAL '90 days');
SELECT add_retention_policy('technical_indicators', INTERVAL '60 days');
SELECT add_retention_policy('trading_signals', INTERVAL '60 days');

-- Retention for continuous aggregates
SELECT add_retention_policy('backtesting_data_5m', INTERVAL '365 days');
SELECT add_retention_policy('ohlcv_15m', INTERVAL '365 days');


