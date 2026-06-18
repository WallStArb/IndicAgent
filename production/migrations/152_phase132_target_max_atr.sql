-- Migration 152: Phase 132 Plan 05 — APR migration for ATR_TARGET_MAX_MULTIPLIER
-- Seeds feature.trade_framer.target_max_atr (default) and per-TF overrides.
-- These are ML learning targets: ML discovery can tune per-TF max target distances
-- once sufficient trade_frames outcomes are available per timeframe.
--
-- Note: target_max_atr_ (empty-TF suffix) is not seeded because trade_framer code
-- falls back to target_max_atr default when timeframe is missing, so no DB row needed.
--
-- Idempotent: ON CONFLICT (config_key) DO NOTHING on config_schema/config_state.
-- config_history rows are single-insert audit entries (no conflict guard needed).
--
-- Provenance: [initial_estimate] — seed values match former module-level constants.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('feature.trade_framer.target_max_atr', 'float', '8.0', 1.0, 20.0,
 '[initial_estimate] Maximum target distance from entry in ATR units (default fallback when no per-TF override). '
 'ML learning target: tune per-TF max target distances after 30+ outcomes.'),
('feature.trade_framer.target_max_atr_1m', 'float', '3.0', 1.0, 10.0,
 '[initial_estimate] Maximum target distance for 1m signals in ATR units. ML learning target.'),
('feature.trade_framer.target_max_atr_5m', 'float', '5.0', 1.0, 15.0,
 '[initial_estimate] Maximum target distance for 5m signals in ATR units. ML learning target.'),
('feature.trade_framer.target_max_atr_15m', 'float', '7.0', 1.0, 20.0,
 '[initial_estimate] Maximum target distance for 15m signals in ATR units. ML learning target.'),
('feature.trade_framer.target_max_atr_1h', 'float', '8.0', 1.0, 20.0,
 '[initial_estimate] Maximum target distance for 1h signals in ATR units. ML learning target.'),
('feature.trade_framer.target_max_atr_4h', 'float', '8.0', 1.0, 20.0,
 '[initial_estimate] Maximum target distance for 4h signals in ATR units. ML learning target.'),
('feature.trade_framer.target_max_atr_1d', 'float', '8.0', 1.0, 20.0,
 '[initial_estimate] Maximum target distance for 1d signals in ATR units. ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('feature.trade_framer.target_max_atr',    '8.0', 1),
('feature.trade_framer.target_max_atr_1m', '3.0', 1),
('feature.trade_framer.target_max_atr_5m', '5.0', 1),
('feature.trade_framer.target_max_atr_15m','7.0', 1),
('feature.trade_framer.target_max_atr_1h', '8.0', 1),
('feature.trade_framer.target_max_atr_4h', '8.0', 1),
('feature.trade_framer.target_max_atr_1d', '8.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.trade_framer.target_max_atr',    1, '8.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER'),
(NOW(), 'feature.trade_framer.target_max_atr_1m', 1, '3.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF'),
(NOW(), 'feature.trade_framer.target_max_atr_5m', 1, '5.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF'),
(NOW(), 'feature.trade_framer.target_max_atr_15m',1, '7.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF'),
(NOW(), 'feature.trade_framer.target_max_atr_1h', 1, '8.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF'),
(NOW(), 'feature.trade_framer.target_max_atr_4h', 1, '8.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF'),
(NOW(), 'feature.trade_framer.target_max_atr_1d', 1, '8.0',  'migration_152', 'Phase 132 Plan 05 APR seed — trade_framer ATR_TARGET_MAX_MULTIPLIER_BY_TF');

COMMIT;
