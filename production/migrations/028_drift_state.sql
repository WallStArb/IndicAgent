-- Migration 028: Add drift_state table for KS and CUSUM drift severity
-- Replaces Redis keys: drift:ks:SYMBOL:TF and drift:cusum:setup_plugin
-- Part of Phase 30 Redpanda migration (DragonflyDB removal).
--
-- Key design:
--   KS rows:    symbol=SYMBOL, tf=TF (e.g. "ES", "1m")
--   CUSUM rows: symbol=setup_plugin_name, tf='_cusum' (sentinel)
-- Both share the same PRIMARY KEY (symbol, tf).

CREATE TABLE IF NOT EXISTS drift_state (
    symbol     TEXT        NOT NULL,
    tf         TEXT        NOT NULL,
    ks_severity    TEXT    NOT NULL DEFAULT 'none',
    cusum_severity TEXT    NOT NULL DEFAULT 'none',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, tf)
);

COMMENT ON TABLE drift_state IS
    'KS distribution drift and CUSUM performance drift severity per symbol/TF or setup_plugin. '
    'Written by drift_monitor_service; read by signal_generator_service at startup and every 4h.';
