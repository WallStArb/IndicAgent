-- IndicAgent Database Schema
-- Creates TimescaleDB tables for market data and indicators
-- Version: 2.1.0
-- Last Updated: 2025-08-08
-- Status: Current ✅

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Market Data OHLCV Table
CREATE TABLE IF NOT EXISTS market_data_ohlcv (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    open DOUBLE PRECISION NOT NULL,
    high DOUBLE PRECISION NOT NULL,
    low DOUBLE PRECISION NOT NULL,
    close DOUBLE PRECISION NOT NULL,
    volume BIGINT NOT NULL,
    source TEXT DEFAULT 'unknown',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create hypertable for market data (1-day chunks)
SELECT create_hypertable('market_data_ohlcv', 'timestamp', 
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Technical Indicators Table
CREATE TABLE IF NOT EXISTS technical_indicators (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    indicator_name TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    source TEXT DEFAULT 'talib',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create hypertable for indicators
SELECT create_hypertable('technical_indicators', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Trading Signals Table
CREATE TABLE IF NOT EXISTS trading_signals (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    direction TEXT NOT NULL,
    strength DOUBLE PRECISION NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    source TEXT DEFAULT 'pattern_engine',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create hypertable for trading signals
SELECT create_hypertable('trading_signals', 'timestamp',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists => TRUE
);

-- Instruments Table (for contract details)
CREATE TABLE IF NOT EXISTS instruments (
    symbol TEXT PRIMARY KEY,
    contract_details JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Uniques to support upsert patterns
ALTER TABLE IF EXISTS market_data_ohlcv
  ADD CONSTRAINT IF NOT EXISTS uq_ohlcv_ts_symbol_tf UNIQUE (timestamp, symbol, timeframe);

ALTER TABLE IF EXISTS technical_indicators
  ADD CONSTRAINT IF NOT EXISTS uq_ind_ts_symbol_tf_name UNIQUE (timestamp, symbol, timeframe, indicator_name);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_market_data_symbol_timeframe_timestamp 
    ON market_data_ohlcv (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_indicators_sym_tf_name_time 
    ON technical_indicators (symbol, timeframe, indicator_name, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_timeframe_timestamp 
    ON trading_signals (symbol, timeframe, timestamp DESC);

-- Create continuous aggregates for performance (5m bars from 1m)
CREATE MATERIALIZED VIEW IF NOT EXISTS backtesting_data_5m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('5 minutes', timestamp) AS timestamp,
    symbol,
    '5m' AS timeframe,
    FIRST(open, timestamp) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, timestamp) AS close,
    SUM(volume) AS volume,
    source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('5 minutes', timestamp), symbol, source
WITH NO DATA;

-- Refresh policy for continuous aggregate
SELECT add_continuous_aggregate_policy('backtesting_data_5m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- Optional: add 15m from 1m to mirror production migrations
CREATE MATERIALIZED VIEW IF NOT EXISTS ohlcv_15m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('15 minutes', timestamp) AS timestamp,
    symbol,
    '15m' AS timeframe,
    FIRST(open, timestamp) AS open,
    MAX(high) AS high,
    MIN(low) AS low,
    LAST(close, timestamp) AS close,
    SUM(volume) AS volume,
    source
FROM market_data_ohlcv
WHERE timeframe = '1m'
GROUP BY time_bucket('15 minutes', timestamp), symbol, source
WITH NO DATA;

SELECT add_continuous_aggregate_policy('ohlcv_15m',
    start_offset => INTERVAL '1 hour',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists => TRUE
);

-- Signal Ledger Table (I7 Phase 1.5 — lifecycle tracking for ML calibration)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS signal_ledger (
    signal_id       UUID NOT NULL DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    setup_plugin    TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    direction       SMALLINT NOT NULL,
    entry_price     DOUBLE PRECISION NOT NULL,
    stop_loss       DOUBLE PRECISION NOT NULL,
    targets         JSONB NOT NULL,
    confidence      DOUBLE PRECISION NOT NULL,
    confluence_score DOUBLE PRECISION NOT NULL,
    regime_context  TEXT NOT NULL,
    supporting_factors JSONB NOT NULL,
    was_selected    BOOLEAN NOT NULL,
    num_signals_bar INTEGER NOT NULL,
    num_agreeing    INTEGER NOT NULL,
    num_conflicting INTEGER NOT NULL,
    resolution_method TEXT NOT NULL,
    composite_rank  SMALLINT NOT NULL,
    market_context  JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    activated_at    TIMESTAMPTZ,
    exit_at         TIMESTAMPTZ,
    exit_price      DOUBLE PRECISION,
    exit_reason     TEXT,
    pnl_ticks       DOUBLE PRECISION,
    pnl_r           DOUBLE PRECISION,
    pnl_dollars     DOUBLE PRECISION,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_id, timestamp)
);

SELECT create_hypertable('signal_ledger', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

CREATE INDEX IF NOT EXISTS idx_ledger_symbol_tf_ts
    ON signal_ledger (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_status
    ON signal_ledger (status, symbol) WHERE status IN ('pending', 'active');

NOTIFY pgsql, 'Schema created successfully';