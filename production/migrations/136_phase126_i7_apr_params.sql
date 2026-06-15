-- Migration 136: Seed APR parameters for lvn_breakout, ofi_divergence, and failed_breakout.
--
-- Wires three I7 plugins that were using hardcoded module-level constants:
--   - lvn_breakout: vol_threshold gate + 4 confidence weights
--   - ofi_divergence: min_divergence_sigma gate + 4 confidence weights
--   - failed_breakout: max_reversal_bars gate + 4 confidence weights
--
-- All weights are ML learning targets post Phase 127 replay.
-- All threshold initial estimates carry [conventional] provenance — derived from
-- standard technical analysis practice, consistent with peer plugins.

-- -------------------------------------------------------------------------
-- config_schema
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES

-- lvn_breakout thresholds
('threshold.lvn_breakout.vol_threshold', 'float', '1.5', 0.5, 5.0,
 '[conventional] Minimum volume expansion multiple (rel_volume or bar/avg ratio) required for LVN breakout gate. 1.5x is industry-standard volume expansion threshold. ML learning target post Phase 127 replay.'),

-- lvn_breakout weights
('weights.lvn_breakout.vol', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] LVN breakout confidence weight: volume ratio factor. ML learning target.'),
('weights.lvn_breakout.trend_clarity', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] LVN breakout confidence weight: HMM trend clarity (hmm_probability). ML learning target.'),
('weights.lvn_breakout.lvn_inverse', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] LVN breakout confidence weight: LVN inverse width (thinner node = faster move). ML learning target.'),
('weights.lvn_breakout.close_strength', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] LVN breakout confidence weight: bar close strength within range. ML learning target.'),

-- ofi_divergence thresholds
('threshold.ofi_divergence.min_divergence_sigma', 'float', '1.5', 0.5, 5.0,
 '[conventional] Minimum absolute ofi_divergence z-score to pass detection gate. 1.5σ is statistically meaningful divergence (peer: dual_divergence thresholds at 1.0-1.5σ). ML learning target post Phase 127 replay.'),

-- ofi_divergence weights
('weights.ofi_divergence.magnitude', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] OFI divergence confidence weight: peak divergence magnitude. ML learning target.'),
('weights.ofi_divergence.alignment', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] OFI divergence confidence weight: EWMA5/EWMA20 directional alignment. ML learning target.'),
('weights.ofi_divergence.persistence', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] OFI divergence confidence weight: persistence bars beyond minimum. ML learning target.'),
('weights.ofi_divergence.volume', 'float', '0.15', 0.0, 1.0,
 '[initial_estimate] OFI divergence confidence weight: relative volume confirmation. ML learning target.'),

-- failed_breakout thresholds
('threshold.failed_breakout.max_reversal_bars', 'int', '3', 1, 10,
 '[conventional] Maximum bars after BOS detection to wait for a close-back-through reversal. 3 bars reflects tight reversal window — longer windows increase noise. ML learning target post Phase 127 replay.'),

-- failed_breakout weights
('weights.failed_breakout.break_magnitude', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Failed breakout confidence weight: reversal close delta vs ATR. ML learning target.'),
('weights.failed_breakout.rejection_strength', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] Failed breakout confidence weight: speed of reversal (sooner = stronger). ML learning target.'),
('weights.failed_breakout.volume', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] Failed breakout confidence weight: relative volume confirmation. ML learning target.'),
('weights.failed_breakout.structure_quality', 'float', '0.15', 0.0, 1.0,
 '[initial_estimate] Failed breakout confidence weight: BOS structural quality (bos_confidence). ML learning target.')

ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.lvn_breakout.vol_threshold',          '1.5',  1),
('weights.lvn_breakout.vol',                      '0.30', 1),
('weights.lvn_breakout.trend_clarity',            '0.25', 1),
('weights.lvn_breakout.lvn_inverse',              '0.25', 1),
('weights.lvn_breakout.close_strength',           '0.20', 1),
('threshold.ofi_divergence.min_divergence_sigma', '1.5',  1),
('weights.ofi_divergence.magnitude',              '0.40', 1),
('weights.ofi_divergence.alignment',              '0.25', 1),
('weights.ofi_divergence.persistence',            '0.20', 1),
('weights.ofi_divergence.volume',                 '0.15', 1),
('threshold.failed_breakout.max_reversal_bars',   '3',    1),
('weights.failed_breakout.break_magnitude',       '0.35', 1),
('weights.failed_breakout.rejection_strength',    '0.30', 1),
('weights.failed_breakout.volume',                '0.20', 1),
('weights.failed_breakout.structure_quality',     '0.15', 1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.lvn_breakout.vol_threshold',          1, '1.5',  'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.lvn_breakout.vol',                      1, '0.30', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.lvn_breakout.trend_clarity',            1, '0.25', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.lvn_breakout.lvn_inverse',              1, '0.25', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.lvn_breakout.close_strength',           1, '0.20', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'threshold.ofi_divergence.min_divergence_sigma', 1, '1.5',  'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.ofi_divergence.magnitude',              1, '0.40', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.ofi_divergence.alignment',              1, '0.25', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.ofi_divergence.persistence',            1, '0.20', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.ofi_divergence.volume',                 1, '0.15', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'threshold.failed_breakout.max_reversal_bars',   1, '3',    'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.failed_breakout.break_magnitude',       1, '0.35', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.failed_breakout.rejection_strength',    1, '0.30', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.failed_breakout.volume',                1, '0.20', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring'),
(NOW(), 'weights.failed_breakout.structure_quality',     1, '0.15', 'initial_estimate', 'Migration 136 seed — Phase 126 APR wiring');
