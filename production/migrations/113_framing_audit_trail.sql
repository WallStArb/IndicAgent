-- Migration 113: framing audit trail columns on signal_ledger
-- Captures stop/target decision metadata at fire time for outcome segmentation.
-- All columns nullable: historical rows predate this feature.

ALTER TABLE signal_ledger
    ADD COLUMN IF NOT EXISTS stop_basis                   text,
    ADD COLUMN IF NOT EXISTS stop_type_col                text,
    ADD COLUMN IF NOT EXISTS structural_stop_distance_atr double precision,
    ADD COLUMN IF NOT EXISTS adaptive_buffer_mult         double precision,
    ADD COLUMN IF NOT EXISTS plugin_regime_type           text;

COMMENT ON COLUMN signal_ledger.stop_basis IS '"structure_snap"|"garch_adaptive"|"atr_static"';
COMMENT ON COLUMN signal_ledger.stop_type_col IS 'which structural level anchored the stop (swing_low, ob_bottom, etc.)';
COMMENT ON COLUMN signal_ledger.structural_stop_distance_atr IS 'distance of structural stop from ATR fallback, in ATR units';
COMMENT ON COLUMN signal_ledger.adaptive_buffer_mult IS 'GARCH x Hurst multiplier applied at fire time (base_mult=1.0)';
COMMENT ON COLUMN signal_ledger.plugin_regime_type IS '"trend"|"mean_reversion"|"any"';

-- Recreate signal_ledger_full to expose the 5 new columns.
-- New framing audit columns are appended at the end to satisfy CREATE OR REPLACE VIEW
-- column immutability constraint (existing column positions must not change).
CREATE OR REPLACE VIEW signal_ledger_full AS
SELECT
    sl.signal_id,
    sl.timestamp,
    sl.symbol,
    sl.timeframe,
    sl.setup_plugin,
    sl.signal_type,
    sl.direction,
    sl.was_selected,
    sl.is_shadow,
    sl.is_backfill,
    sl.signal_schema_version,
    sl.feature_schema_version,
    sl.signal_computed_at,
    sl.feature_ts,
    sl.feature_tf,
    sl.hmm_regime_at_fire,
    sl.garch_sigma_at_fire,
    sl.ttl_bars,
    sl.expires_at,
    sl.entry_price,
    sl.stop_loss,
    sl.targets,
    sl.entry_zone_low,
    sl.entry_zone_high,
    sl.market_entry_price,
    sl.cis_score,
    sl.bucket_scores,
    sl.weights_version,
    sl.pipeline_lag_ms,
    -- lifecycle fields from signal_outcomes (existing columns — order preserved)
    so.status,
    so.activated_at,
    so.activation_price,
    so.zone_entry_pct,
    so.bars_to_activation,
    so.exit_at,
    so.exit_price,
    so.exit_reason,
    so.pnl_ticks,
    so.pnl_r,
    so.pnl_dollars,
    so.signal_quality,
    so.mae,
    so.mfe,
    so.bars_in_trade,
    so.outcome,
    so.market_entry_at,
    so.market_entry_exit_price,
    so.market_entry_exit_at,
    so.market_entry_outcome,
    so.market_entry_pnl_r,
    so.market_entry_mae,
    so.market_entry_mfe,
    so.market_entry_bars_in_trade,
    so.market_entry_gap_bars,
    so.trailing_stop_price,
    so.trailing_stop_tightening_rate,
    so.staleness_score,
    so.staleness_trigger_reason,
    so.chandelier_vol_source,
    so.shadow_tracking_start_ts,
    so.shadow_mae,
    so.shadow_mfe,
    so.shadow_outcome,
    so.effective_ts,
    -- framing audit trail columns (Phase 115) — appended at end per CREATE OR REPLACE VIEW rules
    sl.stop_basis,
    sl.stop_type_col,
    sl.structural_stop_distance_atr,
    sl.adaptive_buffer_mult,
    sl.plugin_regime_type
FROM signal_ledger sl
LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id;
