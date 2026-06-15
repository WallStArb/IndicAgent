-- Migration 132: Seed Phase 126 zone width gate and stop distance floor parameters into APR.
--
-- Covers zone width per-asset-class thresholds (Root Crime 1 fix) and absolute stop
-- distance floor for non-zone ATR-fallback path. APR keys use the feature.zone_engine.*
-- namespace; asset-class suffixes match AssetClass enum string values in src/core/models.py:
-- equity="equity", fx="fx", futures="futures".
--
-- Thresholds derived from noise-band analysis (P126-01 Task 1):
--   zone_width + buffer (0.25xATR) >= 2.0xATR  =>  zone_width >= 1.75xATR
--   rounded to 1.5 as practical starting point.
-- Empirical confirmation (P126-01 diagnostic): equity_etf p50 ratios 0.35-0.68x ATR
-- for most plugins; forex p50 0.40-1.49x ATR. Initial estimates consistent with data.
-- Futures: no live data yet; initial estimate retained.
-- All are ML learning targets post Phase 127 replay.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('feature.zone_engine.min_zone_width_atr', 'float', '1.5', 0.1, 10.0,
 '[initial_estimate — noise band analysis: zone_width + buffer (0.25xATR) >= 2.0xATR -> zone_width >= 1.75xATR; rounded to 1.5. ML learning target post Phase 127 replay.] Universal default minimum zone width as ATR multiple. Prevents sub-ATR zones from generating dead-on-arrival signals (Root Crime 1).'),
('feature.zone_engine.min_zone_width_atr.equity', 'float', '1.5', 0.1, 10.0,
 '[initial_estimate — noise band analysis: zone_width + buffer (0.25xATR) >= 2.0xATR -> zone_width >= 1.75xATR; rounded to 1.5. ML learning target post Phase 127 replay.] Equity asset class override for min_zone_width_atr.'),
('feature.zone_engine.min_zone_width_atr.fx', 'float', '1.0', 0.1, 10.0,
 '[initial_estimate — noise band analysis: forex zones structurally larger relative to ATR (EURUSD/USDCHF p50 ~1.41-1.43x). Threshold set at 1.0 to pass structurally meaningful forex zones. ML learning target post Phase 127 replay.] FX asset class override for min_zone_width_atr.'),
('feature.zone_engine.min_zone_width_atr.futures', 'float', '1.5', 0.1, 10.0,
 '[initial_estimate — noise band analysis: no live futures zone data; initial estimate retained, same reasoning as equity. ML learning target post Phase 127 replay.] Futures asset class override for min_zone_width_atr.'),
('feature.zone_engine.min_stop_distance_atr', 'float', '0.5', 0.05, 5.0,
 '[initial_estimate] Absolute floor on stop distance from entry as ATR multiple. Independent of MIN_STOP_ATR_MULTIPLIER — ML may tune that parameter but cannot breach this floor without an operator override.'),
('feature.zone_engine.min_stop_distance_atr.equity', 'float', '0.5', 0.05, 5.0,
 '[initial_estimate] Absolute floor on stop distance from entry as ATR multiple. Independent of MIN_STOP_ATR_MULTIPLIER — ML may tune that parameter but cannot breach this floor without an operator override. Equity asset class override.'),
('feature.zone_engine.min_stop_distance_atr.fx', 'float', '0.3', 0.05, 5.0,
 '[initial_estimate] Absolute floor on stop distance from entry as ATR multiple. Independent of MIN_STOP_ATR_MULTIPLIER — ML may tune that parameter but cannot breach this floor without an operator override. FX asset class override; lower due to structurally tighter forex spreads.'),
('feature.zone_engine.min_stop_distance_atr.futures', 'float', '0.4', 0.05, 5.0,
 '[initial_estimate] Absolute floor on stop distance from entry as ATR multiple. Independent of MIN_STOP_ATR_MULTIPLIER — ML may tune that parameter but cannot breach this floor without an operator override. Futures asset class override.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.zone_engine.min_zone_width_atr',          '1.5', 1),
('feature.zone_engine.min_zone_width_atr.equity',   '1.5', 1),
('feature.zone_engine.min_zone_width_atr.fx',       '1.0', 1),
('feature.zone_engine.min_zone_width_atr.futures',  '1.5', 1),
('feature.zone_engine.min_stop_distance_atr',          '0.5', 1),
('feature.zone_engine.min_stop_distance_atr.equity',   '0.5', 1),
('feature.zone_engine.min_stop_distance_atr.fx',       '0.3', 1),
('feature.zone_engine.min_stop_distance_atr.futures',  '0.4', 1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.zone_engine.min_zone_width_atr',         1, '1.5', 'initial_estimate', 'Migration 132 seed — Phase 126 zone width gate'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.equity',  1, '1.5', 'initial_estimate', 'Migration 132 seed — Phase 126 zone width gate'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.fx',      1, '1.0', 'initial_estimate', 'Migration 132 seed — Phase 126 zone width gate; forex zones structurally larger vs ATR'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.futures', 1, '1.5', 'initial_estimate', 'Migration 132 seed — Phase 126 zone width gate; no data yet'),
(NOW(), 'feature.zone_engine.min_stop_distance_atr',         1, '0.5', 'initial_estimate', 'Migration 132 seed — Phase 126 stop distance floor'),
(NOW(), 'feature.zone_engine.min_stop_distance_atr.equity',  1, '0.5', 'initial_estimate', 'Migration 132 seed — Phase 126 stop distance floor'),
(NOW(), 'feature.zone_engine.min_stop_distance_atr.fx',      1, '0.3', 'initial_estimate', 'Migration 132 seed — Phase 126 stop distance floor; tighter forex spreads'),
(NOW(), 'feature.zone_engine.min_stop_distance_atr.futures', 1, '0.4', 'initial_estimate', 'Migration 132 seed — Phase 126 stop distance floor');
