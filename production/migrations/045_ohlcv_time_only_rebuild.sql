-- Phase 40.5 PERF-01: Rebuild market_data_ohlcv as time-only hypertable
-- Current: 2D partitioned (Space=symbol, Time=1day), 831 chunks
-- Target: Time-only, 7-day intervals, ~48 chunks for current data
-- Safe: table is backfill-only, no live writes

BEGIN;

-- Step 1: Rename old table (preserves data as fallback)
ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old;

-- Step 2: Create new time-only hypertable with identical schema
CREATE TABLE market_data_ohlcv (
  timestamp timestamptz NOT NULL,
  symbol    text        NOT NULL,
  timeframe text        NOT NULL,
  open      double precision NOT NULL,
  high      double precision NOT NULL,
  low       double precision NOT NULL,
  close     double precision NOT NULL,
  volume    bigint      NOT NULL,
  source    text,
  UNIQUE (timestamp, symbol, timeframe)
);

SELECT create_hypertable('market_data_ohlcv', 'timestamp',
  chunk_time_interval => INTERVAL '7 days',
  if_not_exists => TRUE);

-- Step 3: Enable compression with same segmentby as before
ALTER TABLE market_data_ohlcv SET (
  timescaledb.compress = true,
  timescaledb.compress_segmentby = 'symbol,timeframe',
  timescaledb.compress_orderby   = 'timestamp ASC'
);

-- Step 4: Drop old indexes that moved to market_data_ohlcv_old after rename
-- (Index names are schema-scoped in PostgreSQL; rename doesn't free the names)
DROP INDEX IF EXISTS idx_ohlcv_symbol_tf_time;
DROP INDEX IF EXISTS idx_ohlcv_symbol_trgm;
DROP INDEX IF EXISTS uq_market_data_ohlcv_ts_symbol_tf;

-- Recreate indexes on new hypertable (CLAUDE.md: no CONCURRENTLY on hypertables)
CREATE INDEX idx_ohlcv_symbol_tf_time
  ON market_data_ohlcv (symbol, timeframe, timestamp DESC);

-- pg_trgm already enabled in production
CREATE INDEX idx_ohlcv_symbol_trgm
  ON market_data_ohlcv USING gin (symbol gin_trgm_ops);

-- Step 5: Backfill all rows from old table
INSERT INTO market_data_ohlcv SELECT * FROM market_data_ohlcv_old;

COMMIT;

-- After manual verification of row counts, run separately:
-- DROP TABLE market_data_ohlcv_old;
