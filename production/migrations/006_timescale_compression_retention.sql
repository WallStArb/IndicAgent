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
SELECT add_compression_policy('market_data_ohlcv', INTERVAL '7 days', if_not_exists => true);

-- Technical Indicators
ALTER TABLE IF EXISTS technical_indicators
  SET (timescaledb.compress = true,
       timescaledb.compress_segmentby = 'symbol,timeframe,indicator_name',
       timescaledb.compress_orderby = 'timestamp');
SELECT add_compression_policy('technical_indicators', INTERVAL '7 days', if_not_exists => true);

-- Trading Signals (only if table exists)
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'trading_signals') THEN
    ALTER TABLE trading_signals
      SET (timescaledb.compress = true,
           timescaledb.compress_segmentby = 'symbol,timeframe,signal_type',
           timescaledb.compress_orderby = 'timestamp');
    PERFORM add_compression_policy('trading_signals', INTERVAL '7 days', if_not_exists => true);
    PERFORM add_retention_policy('trading_signals', INTERVAL '60 days', if_not_exists => true);
  END IF;
END $$;

-- Retention policies for base tables
SELECT add_retention_policy('market_data_ohlcv', INTERVAL '90 days', if_not_exists => true);
SELECT add_retention_policy('technical_indicators', INTERVAL '60 days', if_not_exists => true);

-- Retention for continuous aggregates (only if they exist)
DO $$
BEGIN
  IF EXISTS (SELECT FROM pg_matviews WHERE schemaname = 'public' AND matviewname = 'backtesting_data_5m') THEN
    PERFORM add_retention_policy('backtesting_data_5m', INTERVAL '365 days', if_not_exists => true);
  END IF;
END $$;
SELECT add_retention_policy('ohlcv_15m', INTERVAL '365 days', if_not_exists => true);


