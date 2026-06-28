#!/usr/bin/env bash
#
# debug_db_verify.sh — database schema verification
#
# Verifies TimescaleDB schema integrity including tables, indexes, hypertables, and continuous aggregates.
# Run after database setup or migrations to confirm all objects are properly configured.
# Requires psql client and database connection.
#

set -euo pipefail

DB_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/indicagent}"

echo "=== IndicAgent DB Verify ==="

psql "$DB_URL" -X -q -t -A <<'SQL'
SELECT 'table_market_data_ohlcv_exists', to_regclass('public.market_data_ohlcv') IS NOT NULL;
SELECT 'table_technical_indicators_exists', to_regclass('public.technical_indicators') IS NOT NULL;
SELECT 'uniq_ohlcv', EXISTS (
  SELECT 1 FROM pg_indexes WHERE indexname = 'uq_market_data_ohlcv_ts_symbol_tf'
);
SELECT 'uniq_indicators', EXISTS (
  SELECT 1 FROM pg_indexes WHERE indexname = 'uq_technical_indicators_ts_symbol_tf_name'
);
SELECT 'ohlcv_types',
  (SELECT data_type FROM information_schema.columns WHERE table_name='market_data_ohlcv' AND column_name='open') = 'double precision'
  AND (SELECT data_type FROM information_schema.columns WHERE table_name='market_data_ohlcv' AND column_name='close') = 'double precision';
SELECT 'hypertable_ohlcv', EXISTS (SELECT 1 FROM _timescaledb_catalog.hypertable WHERE table_name='market_data_ohlcv');
SELECT 'hypertable_indicators', EXISTS (SELECT 1 FROM _timescaledb_catalog.hypertable WHERE table_name='technical_indicators');
SELECT 'cagg_5m', EXISTS (SELECT 1 FROM _timescaledb_catalog.continuous_agg WHERE user_view_name='backtesting_data_5m');
SELECT 'cagg_15m', EXISTS (SELECT 1 FROM _timescaledb_catalog.continuous_agg WHERE user_view_name='ohlcv_15m');
SELECT 'cagg_1h', EXISTS (SELECT 1 FROM _timescaledb_catalog.continuous_agg WHERE user_view_name='ohlcv_1h');
SELECT 'cagg_4h', EXISTS (SELECT 1 FROM _timescaledb_catalog.continuous_agg WHERE user_view_name='ohlcv_4h');
SELECT 'cagg_1d', EXISTS (SELECT 1 FROM _timescaledb_catalog.continuous_agg WHERE user_view_name='ohlcv_1d');
SQL

echo "✅ Verification queries completed"

