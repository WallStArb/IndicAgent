-- intelligence_features hypertable — tiered JSONB feature store
-- Version: 1.1.0
-- Last Updated: 2026-03-11
-- Status: Current
--
-- Purpose:
--   Durable persistence layer for IntelligenceEvent data produced by
--   market_analysis_service.py. One row per (ts, symbol, tf) bar. Each
--   IntelligenceEvent sub-model is stored in its own JSONB column (tiered),
--   enabling per-tier GIN queries without schema migrations as plugins evolve.
--
-- Design decisions:
--   - NO add_retention_policy — indefinite retention for seasonal ML analysis
--   - 7-day compression policy — balances write freshness with storage efficiency
--   - compress_orderby = 'ts ASC' — forward scan performance (see migration 007)
--   - NOT NULL DEFAULT '{}' on all JSONB tiers — GIN indexes safe, no column-level NULLs
--   - ON CONFLICT (ts, symbol, tf) DO NOTHING in INSERT SQL — idempotent writes
--   - NO GIN indexes on i1–i8 tiers — no production query uses JSONB @> filtering.
--     GIN maintenance on a 1661 MB / 379-chunk hypertable adds write overhead for
--     zero benefit. Add per-tier GIN only when a concrete analytics query requires it.
--     (i1–i6 GINs removed 2026-03-11 via migration 025; i7/i8 columns do not exist)

CREATE TABLE IF NOT EXISTS intelligence_features (
    ts              TIMESTAMPTZ     NOT NULL,
    symbol          TEXT            NOT NULL,
    tf              TEXT            NOT NULL,
    platform        TEXT            NOT NULL DEFAULT 'futures',
    source          TEXT            NOT NULL DEFAULT 'live',   -- 'live' | 'backfill'
    schema_version  TEXT            NOT NULL DEFAULT '1.0',
    -- Tiered JSONB columns — one per IntelligenceEvent sub-model
    -- NOT NULL with empty default ensures GIN indexes never encounter column-level NULL
    bar             JSONB           NOT NULL DEFAULT '{}'::jsonb,
    i1              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    i3              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    i4              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    i5              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    smc             JSONB           NOT NULL DEFAULT '{}'::jsonb,
    i6              JSONB           NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (ts, symbol, tf)
);

SELECT create_hypertable(
    'intelligence_features', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Composite index for common query pattern: symbol + timeframe + time range
CREATE INDEX IF NOT EXISTS idx_intel_features_sym_tf_ts
    ON intelligence_features (symbol, tf, ts DESC);

-- Compression: segment by symbol+tf, order ASC (never DESC — see migration 007)
ALTER TABLE intelligence_features SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby   = 'ts ASC'
);

-- 7-day compression policy
DO $$ BEGIN
  PERFORM add_compression_policy('intelligence_features', INTERVAL '7 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- NO add_retention_policy — indefinite retention is the design decision (seasonal ML analysis)
