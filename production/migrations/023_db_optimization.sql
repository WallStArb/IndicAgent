-- Migration 023: Database optimization pass (2026-03-07)
-- 1. Drop redundant indexes (covered by composite/unique indexes)
-- 2. llm_calls: enable compression (no retention — keep forever)
-- 3. Remove any retention policies from signal-bearing tables (keep forever)
-- 4. Tighten signal_ledger compression to 7d
-- 5. Fix market_data_ohlcv chunk interval (4h -> 1d)
-- 6. Tune autovacuum on high-write hypertables
--
-- PHILOSOPHY: We do not drop signal-bearing data. Storage is cheap.
-- Labeled signal outcomes and feature vectors are irreplaceable training data.
-- Retention policies exist only for confirmed-unused legacy tables.

-- Drop redundant indexes
DROP INDEX IF EXISTS intelligence_features_ts_idx;       -- covered by PK (ts, symbol, tf)
DROP INDEX IF EXISTS market_data_ohlcv_timestamp_idx;    -- covered by unique (timestamp, symbol, timeframe)
DROP INDEX IF EXISTS technical_indicators_timestamp_idx; -- covered by unique (timestamp, symbol, timeframe, indicator_name)

-- llm_calls: enable compression — NO retention policy (keep forever)
ALTER TABLE llm_calls SET (
  timescaledb.compress,
  timescaledb.compress_orderby = 'called_at DESC',
  timescaledb.compress_segmentby = 'model, call_type',
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02
);
SELECT add_compression_policy('llm_calls', INTERVAL '7 days', if_not_exists => true);

-- Remove retention policies from all signal-bearing tables (keep forever)
SELECT remove_retention_policy('market_data_ohlcv', if_exists => true);
SELECT remove_retention_policy('signal_ledger', if_exists => true);
SELECT remove_retention_policy('intelligence_features', if_exists => true);
SELECT remove_retention_policy('llm_calls', if_exists => true);
-- technical_indicators retention (60d) intentionally kept — confirmed unused legacy EAV table

-- signal_ledger: tighten compression (signals resolve in hours, not weeks)
SELECT remove_compression_policy('signal_ledger', if_exists => true);
SELECT add_compression_policy('signal_ledger', INTERVAL '7 days', if_not_exists => true);

-- market_data_ohlcv: fix chunk interval for future chunks (was 4h, now 1d)
SELECT set_chunk_time_interval('market_data_ohlcv', INTERVAL '1 day');

-- Tune autovacuum on high-write hypertables (vacuum at 5% vs default 20%)
ALTER TABLE intelligence_features SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02
);
ALTER TABLE signal_ledger SET (
  autovacuum_vacuum_scale_factor = 0.05,
  autovacuum_analyze_scale_factor = 0.02
);
