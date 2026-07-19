-- Migration 099: split signal_ledger into immutable hypertable + signal_outcomes
-- CLEAN BREAK: drops and recreates signal_ledger. No data migration needed (replay regenerates).
-- Run ONLY after stopping all L6+ services (signal-writer, lifecycle-writer, signal-tracker,
-- signal-auditor, signal-metrics-compute, graduation-compute, swarm-ledger-writer).

BEGIN;

-- ── Drop existing table and dependent objects ─────────────────────────────────
DROP TABLE IF EXISTS signal_ledger CASCADE;
DROP TABLE IF EXISTS signal_outcomes CASCADE;
DROP VIEW IF EXISTS signal_ledger_full CASCADE;

-- ── signal_ledger: fire-time immutable data ───────────────────────────────────
CREATE TABLE signal_ledger (
    signal_id               uuid            NOT NULL,
    timestamp               timestamptz     NOT NULL,
    symbol                  text            NOT NULL,
    timeframe               text            NOT NULL,
    setup_plugin            text            NOT NULL,
    signal_type             text            NOT NULL,
    direction               integer         NOT NULL,
    was_selected            boolean         NOT NULL DEFAULT false,
    is_shadow               boolean         NOT NULL DEFAULT false,
    is_backfill             boolean         NOT NULL DEFAULT false,
    signal_schema_version   text            NOT NULL,
    signal_computed_at      timestamptz,
    feature_ts              timestamptz,
    feature_tf              text,
    hmm_regime_at_fire      integer,
    garch_sigma_at_fire     double precision,
    ttl_bars                integer,
    entry_price             numeric,
    stop_loss               numeric,
    targets                 jsonb,
    entry_zone_low          numeric,
    entry_zone_high         numeric,
    market_entry_price      double precision,
    cis_score               double precision,
    bucket_scores           jsonb,
    weights_version         integer,
    pipeline_lag_ms         double precision,
    PRIMARY KEY (signal_id, timestamp)
);

SELECT create_hypertable('signal_ledger', 'timestamp', chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE);

ALTER TABLE signal_ledger SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, timeframe',
    timescaledb.compress_orderby = 'timestamp DESC'
);
SELECT add_compression_policy('signal_ledger', INTERVAL '7 days', if_not_exists => TRUE);
SELECT add_retention_policy('signal_ledger', INTERVAL '1 year', if_not_exists => TRUE);

CREATE INDEX idx_signal_ledger_symbol_tf ON signal_ledger (symbol, timeframe, timestamp DESC);
CREATE INDEX idx_signal_ledger_signal_id ON signal_ledger (signal_id);

-- ── signal_outcomes: mutable lifecycle state ──────────────────────────────────
CREATE TABLE signal_outcomes (
    signal_id                       uuid            PRIMARY KEY,
    status                          text            NOT NULL DEFAULT 'pending',
    activated_at                    timestamptz,
    activation_price                double precision,
    zone_entry_pct                  double precision,
    bars_to_activation              integer,
    exit_at                         timestamptz,
    exit_price                      double precision,
    exit_reason                     text,
    pnl_ticks                       double precision,
    pnl_r                           double precision,
    pnl_dollars                     double precision,
    signal_quality                  double precision,
    mae                             double precision,
    mfe                             double precision,
    bars_in_trade                   integer,
    outcome                         text,
    market_entry_at                 timestamptz,
    market_entry_exit_price         double precision,
    market_entry_exit_at            timestamptz,
    market_entry_outcome            text,
    market_entry_pnl_r              double precision,
    market_entry_mae                double precision,
    market_entry_mfe                double precision,
    market_entry_bars_in_trade      integer,
    market_entry_gap_bars           integer,
    trailing_stop_price             jsonb,
    trailing_stop_tightening_rate   double precision,
    staleness_score                 double precision,
    staleness_trigger_reason        text,
    chandelier_vol_source           text,
    shadow_tracking_start_ts        timestamptz,
    shadow_mae                      double precision,
    shadow_mfe                      double precision,
    shadow_outcome                  text,
    effective_ts                    timestamptz
);

CREATE INDEX idx_signal_outcomes_status ON signal_outcomes (status) WHERE exit_at IS NULL;

-- ── signal_ledger_full: read-only join view for all consumers ─────────────────
CREATE VIEW signal_ledger_full AS
SELECT
    sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
    sl.setup_plugin, sl.signal_type, sl.direction,
    sl.was_selected, sl.is_shadow, sl.is_backfill,
    sl.signal_schema_version, sl.signal_computed_at,
    sl.feature_ts, sl.feature_tf,
    sl.hmm_regime_at_fire, sl.garch_sigma_at_fire,
    sl.ttl_bars, sl.entry_price, sl.stop_loss, sl.targets,
    sl.entry_zone_low, sl.entry_zone_high,
    sl.market_entry_price, sl.cis_score, sl.bucket_scores,
    sl.weights_version, sl.pipeline_lag_ms,
    -- lifecycle columns from signal_outcomes (NULL until lifecycle events occur)
    so.status, so.activated_at, so.activation_price,
    so.zone_entry_pct, so.bars_to_activation,
    so.exit_at, so.exit_price, so.exit_reason,
    so.pnl_ticks, so.pnl_r, so.pnl_dollars, so.signal_quality,
    so.mae, so.mfe, so.bars_in_trade, so.outcome,
    so.market_entry_at, so.market_entry_exit_price, so.market_entry_exit_at,
    so.market_entry_outcome, so.market_entry_pnl_r, so.market_entry_mae,
    so.market_entry_mfe, so.market_entry_bars_in_trade, so.market_entry_gap_bars,
    so.trailing_stop_price, so.trailing_stop_tightening_rate,
    so.staleness_score, so.staleness_trigger_reason, so.chandelier_vol_source,
    so.shadow_tracking_start_ts, so.shadow_mae, so.shadow_mfe, so.shadow_outcome,
    so.effective_ts
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id;

COMMIT;
