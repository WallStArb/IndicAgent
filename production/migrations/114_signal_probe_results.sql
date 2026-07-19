-- Migration 114: signal_probe_results table
-- Stores simulated activation outcomes for sampled unselected NEEDS_REFACTOR signals.
-- Used by SignalProbeAuditor (daily oneshot) to generate ground truth for Phase 117.5
-- empirical threshold derivation.
--
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/120_signal_probe_results.sql

CREATE TABLE IF NOT EXISTS signal_probe_results (
    signal_id                uuid            NOT NULL PRIMARY KEY,
    probed_at                timestamptz     NOT NULL DEFAULT now(),
    symbol                   text            NOT NULL,
    timeframe                text            NOT NULL,
    setup_plugin             text            NOT NULL,
    direction                integer         NOT NULL,
    sim_activated            boolean         NOT NULL,
    sim_entry_price          double precision,
    sim_exit_price           double precision,
    sim_pnl_r                double precision,
    sim_mae                  double precision,
    sim_mfe                  double precision,
    sim_bars_in_trade        integer,
    sim_outcome              text,
    bars_forward             integer,
    competing_signals_count  integer
);

-- Phase 117.5 analysis: filter/aggregate by setup and time window.
CREATE INDEX IF NOT EXISTS signal_probe_results_plugin_probed_idx
    ON signal_probe_results (setup_plugin, probed_at DESC);

COMMENT ON TABLE signal_probe_results IS
    'Simulated forward-bar activation outcomes for sampled unselected NEEDS_REFACTOR signals. '
    'Written by SignalProbeAuditor daily. Phase 117.5 derives empirical thresholds from this data.';

COMMENT ON COLUMN signal_probe_results.sim_activated IS
    'True when a forward bar touched the entry zone within MAX_BARS_FORWARD bars.';
COMMENT ON COLUMN signal_probe_results.sim_outcome IS
    '"never_activated" | "window_end" — coarse outcome string (full taxonomy deferred to Phase 117.5).';
COMMENT ON COLUMN signal_probe_results.competing_signals_count IS
    'Count of was_selected=true signals at the same (symbol, timeframe, bar timestamp). '
    'Controls for aggregator competition bias when interpreting probe win rates.';
