-- Migration 137: 3-Table Signal Architecture — Schema DDL
--
-- Creates the three-table signal architecture:
--   - signal_events (TimescaleDB hypertable): one row per I7 plugin fire event
--   - trade_frames (regular table): one row per entry_type per signal fire
--   - trade_executions (regular table): one row per live trade execution
--
-- SCHEMA ONLY. Phase 129 executes the data migration from signal_ledger.
-- No data is moved here. signal_ledger is NOT dropped in this migration.
--
-- FK design note: trade_frames.FK uses FOREIGN KEY (signal_id, signal_ts)
-- REFERENCES signal_events (signal_id, ts) because TimescaleDB hypertable PKs
-- are composite — a single-column FK on signal_id alone would fail at DDL time.
-- signal_ts is a first-class column on trade_frames (not just a convenience
-- denormalization) — it is the FK anchor required by PostgreSQL.
--
-- Phase 129 maps signal_ledger columns to the 3-table schema. Columns dropped:
--   signal_type, feature_tf, pipeline_lag_ms, feature_schema_version,
--   staleness_score, staleness_trigger_reason (no home in new schema).
-- Stop architecture fields (stop_basis, stop_type_col, etc.) migrate to
-- trade_frames.frame_details JSONB. Shadow P&L fields archive to frame_details.
--
-- View: signal_ledger_full is the Phase 128 backward-compat surface.
-- signal_ledger_full (migration 095) is superseded after Phase 129 completes
-- the data migration and the legacy signal_ledger monolith is dropped.

-- -------------------------------------------------------------------------
-- signal_events (hypertable)
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS signal_events (
    signal_id               uuid            NOT NULL,
    ts                      timestamptz     NOT NULL, -- Bar timestamp at fire time — hypertable partition dimension
    symbol                  text            NOT NULL,
    tf                      text            NOT NULL,
    setup_plugin            text            NOT NULL,
    direction               text            NOT NULL, -- long / short — converted from integer 1/-1 in Phase 129
    raw_confidence          float8          NOT NULL, -- Intrinsic composite; immutable after emit
    calibrated_confidence   float8,                   -- Nullable; async-populated by calibration pipeline
    cis_score               float8,
    weights_version         int4,
    factor_scores           jsonb,                    -- Per-plugin factor breakdown; ML weight optimization
    context_features        jsonb,                    -- Full flat_features snapshot; SignalRanker feature matrix
    ctf_score               float8,
    ctf_confirmed           bool,
    zone_friction_score     float8,
    hmm_regime_at_fire      int4,
    plugin_regime_type      text,
    garch_sigma_at_fire     float8,
    is_shadow               bool            NOT NULL DEFAULT false,
    is_backfill             bool            NOT NULL DEFAULT false,
    status                  text            NOT NULL DEFAULT 'pending', -- pending / active / regime_suppressed / expired
    signal_schema_version   int4,                     -- int4 not text — correction from signal_ledger.signal_schema_version text
    ttl_bars                int4,
    expires_at              timestamptz,
    signal_computed_at      timestamptz,              -- Pipeline write wall-clock from payload; latency = signal_computed_at - ts
    created_at              timestamptz     NOT NULL DEFAULT now(), -- DB insertion time — distinct from signal_computed_at
    -- Feature context linkage
    feature_ts              timestamptz,              -- Anchor to intelligence_features row; JOIN on (symbol, tf, ts = feature_ts)
    -- Cross-signal context at fire time (populated by SignalAggregator/RankerWriter)
    concurrent_signal_count int4,                     -- Count of other active signals at fire time; crowding indicator
    concurrent_plugins      text[]                    -- setup_plugin values of concurrent active signals; ML-queryable
);

SELECT create_hypertable('signal_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

ALTER TABLE signal_events ADD PRIMARY KEY (signal_id, ts);

ALTER TABLE signal_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'ts DESC'
);

SELECT add_compression_policy('signal_events', INTERVAL '7 days');

-- -------------------------------------------------------------------------
-- signal_events indexes
-- -------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_signal_events_symbol_ts
    ON signal_events (symbol, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_setup_plugin_ts
    ON signal_events (setup_plugin, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_ctf
    ON signal_events (ctf_confirmed, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_regime
    ON signal_events (hmm_regime_at_fire, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_shadow
    ON signal_events (ts DESC) WHERE is_shadow = true;

CREATE INDEX IF NOT EXISTS idx_signal_events_backfill
    ON signal_events (ts DESC) WHERE is_backfill = true;

CREATE INDEX IF NOT EXISTS idx_signal_events_status_ts
    ON signal_events (status, ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_events_expires
    ON signal_events (expires_at) WHERE expires_at IS NOT NULL;

-- -------------------------------------------------------------------------
-- trade_frames (regular table)
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trade_frames (
    frame_id                    uuid        NOT NULL PRIMARY KEY,
    signal_id                   uuid        NOT NULL,
    signal_ts                   timestamptz NOT NULL, -- Denormalized from signal_events; required for FK to hypertable composite PK
    entry_type                  text        NOT NULL, -- at_close / at_pullback / at_limit / at_reclaim / zone_proximal
    direction                   text        NOT NULL, -- long / short
    entry_price                 float8,
    stop_price                  float8,
    target_price                float8,
    r_multiple                  float8,               -- (target - entry) / (entry - stop); standard R-multiple
    ttl_bars                    int4,
    expires_at                  timestamptz,
    counterfactual_pnl_r        float8,               -- Always populated by CounterfactualTracker; ML target variable
    counterfactual_mfe          float8,
    counterfactual_mae          float8,
    counterfactual_bars         int4,
    counterfactual_exit_reason  text,                 -- target_hit / stop_hit / ttl_expired
    counterfactual_measured_at  timestamptz,
    was_selected                bool        NOT NULL DEFAULT false,
    frame_details               jsonb,                -- Stop architecture provenance: stop_basis, stop_type_col,
                                                      -- structural_stop_distance_atr, adaptive_buffer_mult,
                                                      -- stop_structure_type, stop_structure_age_bars,
                                                      -- chandelier_vol_source, trailing_stop_price,
                                                      -- trailing_stop_tightening_rate, entry_zone_low,
                                                      -- entry_zone_high. Also archives historical shadow_mae,
                                                      -- shadow_mfe, shadow_outcome, shadow_tracking_start_ts
                                                      -- during Phase 129 migration.
    created_at                  timestamptz NOT NULL DEFAULT now(),
    regime_at_activation        int4,                     -- HMM regime at entry condition trigger; NULL for at_close (fires immediately)

    CONSTRAINT fk_trade_frames_signal
        FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
);

-- -------------------------------------------------------------------------
-- trade_frames indexes
-- -------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_trade_frames_signal
    ON trade_frames (signal_id, signal_ts);

CREATE INDEX IF NOT EXISTS idx_trade_frames_entry_type_pnl
    ON trade_frames (entry_type, counterfactual_pnl_r);

CREATE INDEX IF NOT EXISTS idx_trade_frames_selected_pnl
    ON trade_frames (was_selected, counterfactual_pnl_r);

-- -------------------------------------------------------------------------
-- trade_executions (regular table)
-- -------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS trade_executions (
    execution_id            uuid        NOT NULL PRIMARY KEY,
    frame_id                uuid        NOT NULL,
    actual_fill_price       float8,
    actual_exit_price       float8,
    actual_pnl_r            float8,
    actual_mfe              float8,
    actual_mae              float8,
    actual_bars             int4,
    market_entry_price      float8,
    market_entry_gap_bars   int4,
    exit_reason             text,
    executed_at             timestamptz,
    exited_at               timestamptz,
    regime_at_exit          int4,                     -- HMM regime at position exit; enables regime-transition analysis

    CONSTRAINT fk_trade_executions_frame
        FOREIGN KEY (frame_id) REFERENCES trade_frames (frame_id)
);

-- -------------------------------------------------------------------------
-- trade_executions indexes
-- -------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_trade_executions_frame
    ON trade_executions (frame_id);

CREATE INDEX IF NOT EXISTS idx_trade_executions_executed_at
    ON trade_executions (executed_at);

-- -------------------------------------------------------------------------
-- signal_ledger_full view (backward-compat surface)
--
-- This view is the Phase 128 join view across all three tables.
-- signal_ledger_full from migration 095 is superseded after Phase 129
-- completes the data migration from the legacy signal_ledger monolith.
-- -------------------------------------------------------------------------

-- DROP both views: signal_ledger_shadow depends on the old signal_ledger_full (migration 095).
-- Phase 129 owns recreating signal_ledger_shadow once data migration is complete.
DROP VIEW IF EXISTS signal_ledger_shadow;
DROP VIEW IF EXISTS signal_ledger_full;
CREATE VIEW signal_ledger_full AS
SELECT
    se.signal_id,
    se.ts,
    se.ts AS timestamp,                                          -- Legacy alias; ts is canonical
    se.symbol,
    se.tf,
    se.tf AS timeframe,                                          -- Legacy alias; tf is canonical
    se.setup_plugin,
    se.direction,
    se.raw_confidence,
    se.calibrated_confidence,
    se.cis_score,
    se.factor_scores,
    se.context_features,
    se.ctf_score,
    se.ctf_confirmed,
    se.zone_friction_score,
    se.hmm_regime_at_fire,
    se.plugin_regime_type,
    se.is_shadow,
    se.is_backfill,
    se.feature_ts,
    se.concurrent_signal_count,
    se.concurrent_plugins,
    se.status,
    se.signal_schema_version,
    se.ttl_bars,
    se.expires_at,
    COALESCE(se.signal_computed_at, se.ts) AS signal_computed_at, -- Never null; callers need not apply COALESCE
    se.signal_computed_at AS signal_computed_at_raw,              -- Nullable original; use for latency queries
    tf.frame_id,
    tf.entry_type,
    tf.entry_price,
    tf.stop_price,
    tf.target_price,
    tf.r_multiple,
    tf.counterfactual_pnl_r,
    tf.counterfactual_mfe,
    tf.counterfactual_mae,
    tf.counterfactual_exit_reason,
    tf.was_selected,
    tf.regime_at_activation,
    te.execution_id,
    te.actual_pnl_r,
    te.actual_fill_price,
    te.actual_exit_price,
    te.exit_reason,
    te.executed_at,
    te.exited_at,
    te.regime_at_exit
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
LEFT JOIN trade_executions te ON te.frame_id = tf.frame_id;
