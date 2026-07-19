-- Migration 106: recreate signal_ledger_full VIEW to expose feature_schema_version
--
-- Dependency audit run 2026-06-02: no dependent views or grants found.
-- (Query: pg_depend JOIN pg_rewrite for referenced_class.relname = 'signal_ledger_full'
--  returned 0 rows — safe to DROP CASCADE without restoring any dependent objects.)
--
-- The explicit column enumeration is copied from migration 097 verbatim, with
-- sl.feature_schema_version inserted adjacent to sl.signal_schema_version.
-- SELECT * is NOT used (forbidden per plan spec).

BEGIN;

DROP VIEW IF EXISTS signal_ledger_full CASCADE;

CREATE VIEW signal_ledger_full AS
SELECT
    sl.signal_id, sl.timestamp, sl.symbol, sl.timeframe,
    sl.setup_plugin, sl.signal_type, sl.direction,
    sl.was_selected, sl.is_shadow, sl.is_backfill,
    sl.signal_schema_version, sl.feature_schema_version, sl.signal_computed_at,
    sl.feature_ts, sl.feature_tf,
    sl.hmm_regime_at_fire, sl.garch_sigma_at_fire,
    sl.ttl_bars, sl.expires_at, sl.entry_price, sl.stop_loss, sl.targets,
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
