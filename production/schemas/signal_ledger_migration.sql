-- Signal Ledger Migration
-- I7 Phase 1.5: Full signal lifecycle tracking for ML calibration
-- Run: PGPASSWORD=postgres psql -h localhost -U postgres -d indicagent -f production/schemas/signal_ledger_migration.sql

CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS signal_ledger (
    -- Identity
    signal_id       UUID NOT NULL DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,

    -- Signal details (from signal.v1 schema)
    setup_plugin    TEXT NOT NULL,
    signal_type     TEXT NOT NULL,
    direction       SMALLINT NOT NULL,          -- +1 or -1
    entry_price     DOUBLE PRECISION NOT NULL,
    stop_loss       DOUBLE PRECISION NOT NULL,
    targets         JSONB NOT NULL,             -- [t1, t2, t3]
    confidence      DOUBLE PRECISION NOT NULL,
    confluence_score DOUBLE PRECISION NOT NULL,
    regime_context  TEXT NOT NULL,
    supporting_factors JSONB NOT NULL,

    -- Aggregation context
    was_selected    BOOLEAN NOT NULL,           -- Did this win aggregation?
    num_signals_bar INTEGER NOT NULL,           -- How many signals fired this bar
    num_agreeing    INTEGER NOT NULL,           -- Same-direction count
    num_conflicting INTEGER NOT NULL,           -- Opposite-direction count
    resolution_method TEXT NOT NULL,            -- "sole" | "priority" | "majority" | "regime_tiebreak" | "no_signal"
    composite_rank  SMALLINT NOT NULL,          -- 1 = winner, 2 = runner-up, etc.

    -- Market context snapshot (feature vector for future ML)
    market_context  JSONB NOT NULL DEFAULT '{}',

    -- Lifecycle tracking
    status          TEXT NOT NULL DEFAULT 'pending',
    activated_at    TIMESTAMPTZ,
    exit_at         TIMESTAMPTZ,
    exit_price      DOUBLE PRECISION,
    exit_reason     TEXT,                       -- "stop_loss" | "target_1" | "target_2" | "target_3" | "ttl_expired" | "invalidated"

    -- P&L (filled on exit)
    pnl_ticks       DOUBLE PRECISION,
    pnl_r           DOUBLE PRECISION,           -- R-multiple
    pnl_dollars     DOUBLE PRECISION,

    -- Metadata
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_id, timestamp)
);

-- Convert to hypertable (7-day chunks for signal-volume data)
SELECT create_hypertable('signal_ledger', 'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Compression: segment by symbol + setup_plugin
ALTER TABLE signal_ledger SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,setup_plugin',
    timescaledb.compress_orderby = 'timestamp DESC'
);
SELECT add_compression_policy('signal_ledger', INTERVAL '30 days');

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ledger_symbol_tf_ts
    ON signal_ledger (symbol, timeframe, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_ledger_status
    ON signal_ledger (status, symbol) WHERE status IN ('pending', 'active');

CREATE INDEX IF NOT EXISTS idx_ledger_selected
    ON signal_ledger (was_selected, symbol, timestamp DESC) WHERE was_selected = TRUE;

CREATE INDEX IF NOT EXISTS idx_ledger_setup_plugin
    ON signal_ledger (setup_plugin, timestamp DESC);
