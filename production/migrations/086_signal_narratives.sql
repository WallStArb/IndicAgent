-- signal_narratives — one row per narrative generation (idempotent per signal_id)
-- Phase 78 D-29/D-30: narrative moved from Kafka consumer to on-demand API endpoint
--
-- Purpose:
--   Every LLM narrative is persisted. This makes narrative output:
--   1. Idempotent — repeat GET for same signal_id returns cached row, zero LLM cost
--   2. Auditable — full provenance: model, prompt_version, latency, input hash
--   3. Backtestable — JOIN to signal_ledger outcomes, measure narrative quality
--   4. Training data — labeled samples for future narrative quality models
--
-- Design:
--   PRIMARY KEY (signal_id) — one narrative per signal, ever
--   created_at — when generated (not when signal fired)
--   prompt_hash — detects when prompt changes invalidate cached narratives

CREATE TABLE IF NOT EXISTS signal_narratives (
    signal_id       UUID            NOT NULL PRIMARY KEY,
    symbol          TEXT            NOT NULL,
    timeframe       TEXT            NOT NULL,
    narrative       TEXT            NOT NULL,
    model           TEXT            NOT NULL DEFAULT '',
    agent_id        TEXT            NOT NULL DEFAULT '',
    prompt_version  TEXT            NOT NULL DEFAULT '',
    prompt_hash     TEXT            NOT NULL DEFAULT '',
    latency_ms      REAL            NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

SELECT create_hypertable(
    'signal_narratives', 'created_at',
    chunk_time_interval => INTERVAL '30 days',
    if_not_exists => TRUE
);

-- Compression after 7 days (narrative rows are immutable)
ALTER TABLE signal_narratives SET (
    timescaledb.compress = true,
    timescaledb.compress_segmentby = 'symbol',
    timescaledb.compress_orderby   = 'created_at ASC'
);

DO $$ BEGIN
  PERFORM add_compression_policy('signal_narratives', INTERVAL '7 days', if_not_exists => true);
EXCEPTION WHEN others THEN NULL; END $$;

-- FK to signal_ledger — narrative cannot exist without a signal
ALTER TABLE signal_narratives
    ADD CONSTRAINT fk_narrative_signal
    FOREIGN KEY (signal_id) REFERENCES signal_ledger(signal_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_narratives_symbol_tf_created
    ON signal_narratives (symbol, timeframe, created_at DESC);
