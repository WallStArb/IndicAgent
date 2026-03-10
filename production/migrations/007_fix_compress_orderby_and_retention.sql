-- Fix compress_orderby (DESC → ASC) and add missing retention policies
-- Version: 1.0.0
-- Last Updated: 2026-02-19
-- Status: Current ✅
--
-- Why this migration exists:
--   create_schema.sql and migration 004 both set compress_orderby = 'timestamp DESC'.
--   TimescaleDB compresses chunks by sorting rows on this column. Analytics queries,
--   continuous aggregate refreshes, and indicator computation all scan FORWARD in time
--   (ASC). DESC ordering means every forward scan reads chunk data in reverse — worse
--   locality and decompression performance. Migration 006 was never applied so
--   retention policies are also missing.
--
-- Safe to run on an empty DB (no compressed chunks exist yet).
-- If running on a DB with compressed data, decompress all chunks first.

-- ─── Fix compress_orderby on all hypertables ────────────────────────────────
-- Must remove compression policy, alter settings, then re-add policy.
-- The DO blocks handle the case where the policy was never added (no error).

-- market_data_ohlcv
DO $$ BEGIN
  PERFORM remove_compression_policy('market_data_ohlcv', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

ALTER TABLE IF EXISTS market_data_ohlcv SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,timeframe',
    timescaledb.compress_orderby = 'timestamp ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('market_data_ohlcv', INTERVAL '7 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- technical_indicators
DO $$ BEGIN
  PERFORM remove_compression_policy('technical_indicators', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

ALTER TABLE IF EXISTS technical_indicators SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,timeframe,indicator_name',
    timescaledb.compress_orderby = 'timestamp ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('technical_indicators', INTERVAL '7 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- trading_signals
DO $$ BEGIN
  PERFORM remove_compression_policy('trading_signals', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

ALTER TABLE IF EXISTS trading_signals SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,timeframe,signal_type',
    timescaledb.compress_orderby = 'timestamp ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('trading_signals', INTERVAL '30 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- signal_ledger
DO $$ BEGIN
  PERFORM remove_compression_policy('signal_ledger', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

ALTER TABLE IF EXISTS signal_ledger SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,setup_plugin',
    timescaledb.compress_orderby = 'timestamp ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('signal_ledger', INTERVAL '30 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- ─── Retention policies (missing from initial schema) ───────────────────────
-- Base tables
DO $$ BEGIN
  PERFORM add_retention_policy('market_data_ohlcv', INTERVAL '90 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

DO $$ BEGIN
  PERFORM add_retention_policy('technical_indicators', INTERVAL '60 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

DO $$ BEGIN
  PERFORM add_retention_policy('trading_signals', INTERVAL '60 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

DO $$ BEGIN
  PERFORM add_retention_policy('signal_ledger', INTERVAL '365 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- Continuous aggregates (keep longer than base tables)
DO $$ BEGIN
  PERFORM add_retention_policy('backtesting_data_5m', INTERVAL '365 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

DO $$ BEGIN
  PERFORM add_retention_policy('ohlcv_15m', INTERVAL '365 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;
