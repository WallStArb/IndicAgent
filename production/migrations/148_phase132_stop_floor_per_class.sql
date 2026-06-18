-- Migration 148: Per-asset-class minimum stop floor APR keys (Phase 132 A3).
--
-- Adds four asset-class-scoped minimum stop floor keys for trade_framer.py.
-- These keys sit above the universal min_stop_atr (1.0 ATR) floor and are
-- routed via _min_stop_multiplier_floor(asset_class) in _resolve_stop_long /
-- _resolve_stop_short.
--
-- Seed values derived empirically from intelligence_features.technical_indicators
-- ->>'atr_14' median per asset class, divided by tick_size per instrument.
-- Source: 5M intelligence_features rows queried 2026-06-17.
--
-- Asset class -> instrument mapping:
--   fx                  → EURUSD, GBPUSD, USDCHF, USDJPY (class median ATR/tick ~8.9x)
--   commodity_small_tick→ SI, NG, HG, CL (class median ATR/tick ~3.8x; NG only 1.5x)
--   equity_etf          → QQQ, SPY, IWM, XLE, SMH (class median ATR/tick ~15.2x)
--   futures_large_tick  → ES, NQ, YM, RTY (class median ATR/tick ~7.7x)
--
-- NG (natural gas) has only 1.5x ATR/tick headroom → commodity_small_tick floor
-- set at 1.5 ATR for safety. All others have sufficient headroom at 1.0 ATR.
--
-- All keys are [initial_estimate] — first real values come after Phase 133
-- corpus rebuild and ML tuning via counterfactual_pnl_r per asset class.
--
-- All inserts are idempotent: ON CONFLICT (config_key) DO NOTHING.
-- Safe to re-run; no DROP or UPDATE statements in this file.
--
-- Prerequisite: migrations 146 + 147 (trade_framer module-level and adaptive
-- buffer APR keys) must have been applied.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'feature.trade_framer.stop_multiplier_floor.fx',
    'float',
    '1.0',
    0.5, 3.0,
    '[initial_estimate] Per-asset-class minimum stop floor for FX instruments (EURUSD, GBPUSD, USDCHF, USDJPY). Expressed as ATR multiplier. Overrides universal min_stop_atr for FX. Seed derived from intelligence_features.technical_indicators->>''atr_14'' median per symbol / tick_size; class median ATR/tick ~8.9x. ML learning target: tune per asset class after Phase 133 corpus rebuild (n >= 30 trade_frames with counterfactual_pnl_r). First real value after Phase 133.'
),
(
    'feature.trade_framer.stop_multiplier_floor.commodity_small_tick',
    'float',
    '1.5',
    0.5, 3.0,
    '[initial_estimate] Per-asset-class minimum stop floor for commodity instruments with small tick sizes (SI, NG, HG, CL). Expressed as ATR multiplier. Seed = 1.5 because NG has only ~1.5x ATR/tick headroom, making a 1.0 ATR floor insufficient for minimum viable stop distance in absolute terms. ML learning target: tune per asset class after Phase 133 corpus rebuild. First real value after Phase 133.'
),
(
    'feature.trade_framer.stop_multiplier_floor.equity_etf',
    'float',
    '1.0',
    0.5, 3.0,
    '[initial_estimate] Per-asset-class minimum stop floor for equity ETF instruments (QQQ, SPY, IWM, XLE, SMH). Expressed as ATR multiplier. Class median ATR/tick ~15.2x — strong headroom, universal 1.0 ATR floor is sufficient as starting point. ML learning target: tune per asset class after Phase 133 corpus rebuild. First real value after Phase 133.'
),
(
    'feature.trade_framer.stop_multiplier_floor.futures_large_tick',
    'float',
    '1.0',
    0.5, 3.0,
    '[initial_estimate] Per-asset-class minimum stop floor for large-tick index futures (ES, NQ, YM, RTY). Expressed as ATR multiplier. Class median ATR/tick ~7.7x — all major contracts have adequate headroom at 1.0 ATR. ML learning target: tune per asset class after Phase 133 corpus rebuild. First real value after Phase 133.'
)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.trade_framer.stop_multiplier_floor.fx',                   '1.0', 1),
('feature.trade_framer.stop_multiplier_floor.commodity_small_tick', '1.5', 1),
('feature.trade_framer.stop_multiplier_floor.equity_etf',           '1.0', 1),
('feature.trade_framer.stop_multiplier_floor.futures_large_tick',   '1.0', 1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.trade_framer.stop_multiplier_floor.fx',                   1, '1.0', 'migration_148', 'Phase 132 A3 per-asset-class stop floor seed — FX class median ATR/tick ~8.9x'),
(NOW(), 'feature.trade_framer.stop_multiplier_floor.commodity_small_tick', 1, '1.5', 'migration_148', 'Phase 132 A3 per-asset-class stop floor seed — NG only 1.5x ATR/tick headroom; higher floor for safety'),
(NOW(), 'feature.trade_framer.stop_multiplier_floor.equity_etf',           1, '1.0', 'migration_148', 'Phase 132 A3 per-asset-class stop floor seed — equity_etf class median ATR/tick ~15.2x'),
(NOW(), 'feature.trade_framer.stop_multiplier_floor.futures_large_tick',   1, '1.0', 'migration_148', 'Phase 132 A3 per-asset-class stop floor seed — futures_large_tick class median ATR/tick ~7.7x');
