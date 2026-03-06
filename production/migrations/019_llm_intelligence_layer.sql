-- 019_llm_intelligence_layer.sql
-- Phase 16: LLM Intelligence Layer — schema foundation
-- Date: 2026-03-05
--
-- Design:
--   llm_calls: hypertable (partitioned by called_at) capturing every LLM invocation —
--     per-signal narratives (ai_narrative_service), group synthesis, and counterfactuals.
--     Outcome columns (pnl_r, mae, mfe, outcome, win) back-filled by llm_writer_service
--     when signal_lifecycle emits an exit event on llm_outcomes:stream.
--
--   llm_model_scores: one row per (model, regime, setup_type, call_type) aggregate.
--     Refreshed periodically by llm_writer_service; is_significant=TRUE only when
--     n_outcomes >= 30 AND p_value < 0.05 (Renaissance significance gate).
--
-- Stream contracts (handled in stream_keys.py):
--   {env}:llm_calls:stream   — emitted by ai_narrative_service after every LLM call
--   {env}:llm_outcomes:stream — emitted by signal_lifecycle_service on signal exit

-- ── llm_calls hypertable ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id         UUID NOT NULL DEFAULT gen_random_uuid(),
    called_at       TIMESTAMPTZ NOT NULL,
    call_type       TEXT NOT NULL,          -- 'per_signal' | 'group_synthesis' | 'counterfactual'
    signal_id       UUID,                                       -- nullable; soft ref to signal_ledger(signal_id)
    group_name      TEXT,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    model           TEXT NOT NULL,
    provider        TEXT NOT NULL,
    prompt          TEXT NOT NULL,
    response        TEXT,                   -- NULL if call failed or counterfactual
    latency_ms      INTEGER,
    tokens_est      INTEGER,
    succeeded       BOOLEAN NOT NULL DEFAULT TRUE,
    regime          TEXT,
    session         TEXT,
    entry_price     DOUBLE PRECISION,
    stop_loss       DOUBLE PRECISION,
    target_price    DOUBLE PRECISION,
    confidence      DOUBLE PRECISION,
    cis_score       DOUBLE PRECISION,
    entry_zone_low  DOUBLE PRECISION,
    entry_zone_high DOUBLE PRECISION,
    setup_type      TEXT,
    outcome         TEXT,
    pnl_r           DOUBLE PRECISION,
    mae             DOUBLE PRECISION,
    mfe             DOUBLE PRECISION,
    bars_in_trade   INTEGER,
    win             BOOLEAN,
    outcome_at      TIMESTAMPTZ,
    PRIMARY KEY (call_id, called_at)
);

SELECT create_hypertable('llm_calls', 'called_at');

COMMENT ON TABLE llm_calls IS
    'Audit log of every LLM call made by the intelligence layer. '
    'Partitioned by called_at for efficient time-range queries. '
    'Outcome columns (pnl_r, mae, mfe, win, outcome, outcome_at) are NULL at insert '
    'and back-filled when signal_lifecycle_service emits an exit event.';

COMMENT ON COLUMN llm_calls.call_type IS
    'Invocation type: per_signal (ai_narrative per setup), group_synthesis (phi4-mini group), counterfactual (shadow/suppressed signal).';

COMMENT ON COLUMN llm_calls.signal_id IS
    'Soft reference to signal_ledger.signal_id (no FK — signal_ledger PK is composite). NULL for group_synthesis calls.';

COMMENT ON COLUMN llm_calls.provider IS
    'LLM provider name, e.g. ''ollama''. Supports multi-provider routing in future.';

COMMENT ON COLUMN llm_calls.succeeded IS
    'FALSE when the LLM call timed out, errored, or returned unparseable output.';

COMMENT ON COLUMN llm_calls.regime IS
    'Market regime at call time: trending | ranging | volatile. Copied from IntelligenceEvent.';

COMMENT ON COLUMN llm_calls.pnl_r IS
    'Final P&L in units of initial risk (R). Back-filled from signal_lifecycle outcome.';

COMMENT ON COLUMN llm_calls.win IS
    'TRUE if trade closed with pnl_r > 0. NULL until outcome is known.';

COMMENT ON COLUMN llm_calls.outcome_at IS
    'Timestamp of signal exit / outcome determination. NULL until back-filled.';

-- ── llm_model_scores aggregate table ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS llm_model_scores (
    model           TEXT NOT NULL,
    regime          TEXT NOT NULL,          -- 'trending' | 'ranging' | 'volatile' | '__all__'
    setup_type      TEXT NOT NULL,          -- setup plugin name or '__all__'
    call_type       TEXT NOT NULL,
    n_calls         INTEGER NOT NULL DEFAULT 0,
    n_outcomes      INTEGER NOT NULL DEFAULT 0,
    win_rate        DOUBLE PRECISION,
    avg_pnl_r       DOUBLE PRECISION,
    avg_latency_ms  INTEGER,
    p_value         DOUBLE PRECISION,
    is_significant  BOOLEAN DEFAULT FALSE,
    score_updated_at TIMESTAMPTZ,
    PRIMARY KEY (model, regime, setup_type, call_type)
);

COMMENT ON TABLE llm_model_scores IS
    'Aggregate performance scores per (model, regime, setup_type, call_type). '
    'Refreshed by llm_writer_service after each outcome back-fill batch. '
    'is_significant=TRUE requires n_outcomes >= 30 AND p_value < 0.05 (Renaissance gate).';

COMMENT ON COLUMN llm_model_scores.regime IS
    'Market regime segment: trending | ranging | volatile | __all__ (global aggregate).';

COMMENT ON COLUMN llm_model_scores.setup_type IS
    'I7 plugin name (e.g. BullishEngulfing) or __all__ for cross-setup aggregate.';

COMMENT ON COLUMN llm_model_scores.is_significant IS
    'TRUE only when n_outcomes >= 30 AND p_value < 0.05. '
    'Follows Renaissance Technologies significance gate — no model is trusted before proof.';

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_llm_calls_signal_id
    ON llm_calls (signal_id);

CREATE INDEX IF NOT EXISTS idx_llm_calls_model_regime
    ON llm_calls (model, regime);

CREATE INDEX IF NOT EXISTS idx_llm_calls_called_at
    ON llm_calls (called_at DESC);
