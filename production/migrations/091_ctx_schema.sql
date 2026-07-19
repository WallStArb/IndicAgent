-- Migration 091: CTX Foundation — ctx_events hypertable, ctx_snapshots, intelligence_features.ctx
-- Purpose: Establish qualitative context (CTX) data collection infrastructure.
--          Phase 82 data collection only — no AIContext prompt rendering until Phase 83.
-- Dependencies: None (standalone migration).
-- Idempotency: All statements use IF NOT EXISTS or if_not_exists => TRUE for safe replay.

-- ctx_events: append-only hypertable for incoming qualitative context events.
-- symbol NULL = global event (e.g. FOMC announcement affecting all symbols).
-- event_type restricted to {'earnings', 'macro', 'news'} at application layer (CtxWriterAgent).
CREATE TABLE IF NOT EXISTS ctx_events (
    event_ts    TIMESTAMPTZ NOT NULL,
    symbol      TEXT,
    event_type  TEXT NOT NULL,
    source      TEXT NOT NULL,
    payload     JSONB NOT NULL
);

-- Partition ctx_events by event_ts (TimescaleDB hypertable).
SELECT create_hypertable('ctx_events', 'event_ts', if_not_exists => TRUE);

-- Index for queries filtering by symbol + event_type + time (most recent first).
CREATE INDEX IF NOT EXISTS ctx_events_symbol_type_idx ON ctx_events (symbol, event_type, event_ts DESC);

-- ctx_snapshots: current and historical qualitative context snapshots per (symbol, event_type).
-- valid_to NULL = currently active snapshot.
-- PRIMARY KEY prevents duplicate snapshot rows for the same (symbol, event_type, valid_from).
CREATE TABLE IF NOT EXISTS ctx_snapshots (
    symbol      TEXT,
    event_type  TEXT NOT NULL,
    valid_from  TIMESTAMPTZ NOT NULL,
    valid_to    TIMESTAMPTZ,
    ctx         JSONB NOT NULL,
    PRIMARY KEY (symbol, event_type, valid_from)
);

-- Index for the as-of join in feature_writer_agent.py:
--   WHERE (symbol = $1 OR symbol IS NULL)
--     AND valid_from <= $bar_ts
--     AND (valid_to IS NULL OR valid_to > $bar_ts)
-- Prevents this query from becoming a hot-path full scan.
CREATE INDEX IF NOT EXISTS ctx_snapshots_lookup_idx ON ctx_snapshots (symbol, valid_from, valid_to);

-- Add nullable ctx JSONB column to intelligence_features.
-- Resolved at bar insert time via as-of join against ctx_snapshots.
-- NULL = no active ctx snapshot for that bar (expected during Phase 82 rollout).
ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS ctx JSONB;
