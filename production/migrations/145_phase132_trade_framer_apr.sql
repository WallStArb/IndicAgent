-- Migration 145: Seed Phase 132 APR keys for trade_framer module-level constants.
--
-- Covers the 19 module-level numeric constants in trade_framer.py that are
-- being migrated to APR per CLAUDE.md architecture mandate.
--
-- Split: Plan 02 (module-level constants, this file) — Plans 03/04 cover
-- adaptive buffer coefficients and per-asset-class stop-floor keys.
--
-- All 19 keys seeded at their current hardcoded values so seed == fallback.
-- Behavioral change at deployment is zero; ML tuning only after corpus rebuild.
--
-- Idempotent: ON CONFLICT (config_key) DO NOTHING on config_schema/config_state.
-- config_history rows are single-insert audit entries (no conflict guard needed).
--
-- Provenance: [initial_estimate] — first real values come after Phase 133
-- corpus rebuild with counterfactual_pnl_r data.
--
-- ML learning targets: all stop/target/zone ATR multipliers are ML targets.
-- ADAPTIVE_BUFFER_HARD_CAP and STRUCTURE_SNAP_PROXIMITY_ATR are operator-preference
-- and structural-classification respectively (not ML targets).

-- -------------------------------------------------------------------------
-- config_schema entries (metadata + validation bounds)
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
-- Stop buffer ATR multipliers (structural stop placement, all ML targets)
('feature.trade_framer.stop_demand_buffer_atr', 'float', '0.25', 0.05, 2.0,
 '[initial_estimate] ATR multiplier added below demand zone low as stop buffer. '
 'Stop = nearest_demand_low - ATR x value. ML learning target: correlate with '
 'counterfactual_pnl_r per asset class after 30+ outcomes. Bounded below by '
 'feature.zone_engine.min_stop_distance_atr.'),
('feature.trade_framer.stop_sweep_buffer_atr', 'float', '0.30', 0.05, 2.0,
 '[initial_estimate] ATR multiplier below sweep level as stop buffer. '
 'Stop = sweep_level - ATR x value. ML learning target after 30+ outcomes.'),
('feature.trade_framer.stop_ob_buffer_atr', 'float', '0.20', 0.05, 2.0,
 '[initial_estimate] ATR multiplier below/above order block bottom/top as stop buffer. '
 'Used for both FVG and OB stop placements. ML learning target after 30+ outcomes.'),
('feature.trade_framer.stop_swing_buffer_atr', 'float', '0.25', 0.05, 2.0,
 '[initial_estimate] ATR multiplier below swing low (above swing high for shorts) as stop buffer. '
 'Also used for EMA-21 support/resistance stop placements. ML learning target.'),
('feature.trade_framer.stop_sr_buffer_atr', 'float', '0.50', 0.05, 2.0,
 '[initial_estimate] ATR multiplier below S/R nearest support (above resistance for shorts). '
 'Wider buffer reflects S/R level imprecision vs structural levels. ML learning target.'),
('feature.trade_framer.stop_fallback_atr', 'float', '2.0', 0.5, 5.0,
 '[initial_estimate] ATR multiplier for pure ATR fallback stop when no structural level exists. '
 'Stop = entry - ATR x value (longs). Also used as cap override when structural stop '
 'exceeds per-TF max_stop. ML learning target after 30+ outcomes.'),

-- Zone bound ATR multipliers
('feature.trade_framer.zone_sweep_atr', 'float', '0.76', 0.1, 2.0,
 '[initial_estimate] ATR multiplier for sweep/reclaim entry zone half-width. '
 'Zone = entry +/- ATR x value (total width 1.52x ATR, passes 1.5x ATR gate). '
 'ML learning target after 30+ outcomes.'),
('feature.trade_framer.zone_low_atr', 'float', '1.0', 0.1, 3.0,
 '[initial_estimate] ATR multiplier for ATR fallback zone lower bound below entry. '
 'Zone_low = entry - ATR x value. Used when no structural zone is available. '
 'ML learning target after 30+ outcomes.'),
('feature.trade_framer.zone_high_atr', 'float', '0.5', 0.1, 3.0,
 '[initial_estimate] ATR multiplier for ATR fallback zone upper bound above entry. '
 'Zone_high = entry + ATR x value. Asymmetric: lower bound wider by design. '
 'ML learning target after 30+ outcomes.'),
('feature.trade_framer.target_min_atr', 'float', '0.5', 0.1, 3.0,
 '[initial_estimate] Minimum target distance from entry as ATR multiple. '
 'Filters structural candidate targets closer than this from the entry. '
 'ML learning target after 30+ outcomes.'),
('feature.trade_framer.zone_plugin_fallback_atr', 'float', '0.2', 0.05, 2.0,
 '[initial_estimate] Narrow ATR fallback zone half-width for plugins that bypass frame_trade(). '
 'Structural fallback — not an ML learning target. Operator preference.'),

-- Volume profile proximity gate
('feature.trade_framer.vp_proximity_atr', 'float', '0.5', 0.05, 2.0,
 '[initial_estimate] ATR distance threshold for volume profile proximity gate. '
 'Price within VAH or VAL +/- ATR x value activates VP regime for target selection. '
 'ML learning target after 30+ outcomes.'),

-- ATR fallback target multipliers (RR-based targets when no structural levels found)
('feature.trade_framer.fallback_t1_atr', 'float', '2.0', 0.5, 6.0,
 '[initial_estimate] Risk multiplier for ATR fallback T1 target. '
 'T1 = entry + risk x value. Applied when no structural target candidates pass RR gate. '
 'ML learning target after 30+ outcomes.'),
('feature.trade_framer.fallback_t2_atr', 'float', '3.5', 1.0, 8.0,
 '[initial_estimate] Risk multiplier for ATR fallback T2 target. '
 'T2 = entry + risk x value. ML learning target after 30+ outcomes.'),
('feature.trade_framer.fallback_t3_atr', 'float', '5.5', 1.0, 12.0,
 '[initial_estimate] Risk multiplier for ATR fallback T3 target. '
 'T3 = entry + risk x value. ML learning target after 30+ outcomes.'),

-- Minimum stop distance floor
('feature.trade_framer.min_stop_atr', 'float', '1.0', 0.25, 3.0,
 '[initial_estimate] Minimum stop distance as ATR multiple from entry. '
 'Primary ML stop control: ensures stops are at least 1x ATR from entry. '
 'Bounded below by feature.zone_engine.min_stop_distance_atr (0.5 ATR). '
 'ML learning target — primary lever for stopped_at_entry rate reduction.'),

-- RR gate threshold
('threshold.trade_framer.min_rr_t1', 'float', '1.5', 0.5, 5.0,
 '[initial_estimate] Minimum reward-to-risk ratio for T1 target. '
 'Signals with T1 RR below this threshold are rejected as non-viable. '
 'ML learning target after 30+ outcomes.'),

-- Adaptive buffer hard cap (operator preference, not ML target)
('feature.trade_framer.adaptive_buffer_hard_cap', 'float', '1.40', 1.0, 3.0,
 '[initial_estimate] Maximum multiplier expansion factor for the GARCH adaptive buffer. '
 'Caps the vol-driven stop widening: result = min(garch_result, base_mult x value). '
 'Operator preference — not an ML learning target (safety ceiling).'),

-- Structure snap proximity (structural classification, not ML target)
('feature.trade_framer.structure_snap_proximity_atr', 'float', '1.5', 0.25, 5.0,
 '[initial_estimate] ATR distance threshold for stop basis classification. '
 'Structural stops within this many effective-ATR units of the ATR fallback stop '
 'are classified as structure_snap; further stops are garch_adaptive. '
 'Structural classification parameter — not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries (live values — seeded at current hardcoded values)
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
-- Stop buffer multipliers
('feature.trade_framer.stop_demand_buffer_atr',       '0.25', 1),
('feature.trade_framer.stop_sweep_buffer_atr',        '0.30', 1),
('feature.trade_framer.stop_ob_buffer_atr',           '0.20', 1),
('feature.trade_framer.stop_swing_buffer_atr',        '0.25', 1),
('feature.trade_framer.stop_sr_buffer_atr',           '0.50', 1),
('feature.trade_framer.stop_fallback_atr',            '2.0',  1),
-- Zone bound multipliers
('feature.trade_framer.zone_sweep_atr',               '0.76', 1),
('feature.trade_framer.zone_low_atr',                 '1.0',  1),
('feature.trade_framer.zone_high_atr',                '0.5',  1),
('feature.trade_framer.target_min_atr',               '0.5',  1),
('feature.trade_framer.zone_plugin_fallback_atr',     '0.2',  1),
-- VP proximity
('feature.trade_framer.vp_proximity_atr',             '0.5',  1),
-- Fallback targets
('feature.trade_framer.fallback_t1_atr',              '2.0',  1),
('feature.trade_framer.fallback_t2_atr',              '3.5',  1),
('feature.trade_framer.fallback_t3_atr',              '5.5',  1),
-- Stop floor and RR gate
('feature.trade_framer.min_stop_atr',                 '1.0',  1),
('threshold.trade_framer.min_rr_t1',                  '1.5',  1),
-- Buffer cap and snap proximity
('feature.trade_framer.adaptive_buffer_hard_cap',     '1.40', 1),
('feature.trade_framer.structure_snap_proximity_atr', '1.5',  1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed (audit trail)
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'feature.trade_framer.stop_demand_buffer_atr',       1, '0.25', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.stop_sweep_buffer_atr',        1, '0.30', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.stop_ob_buffer_atr',           1, '0.20', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.stop_swing_buffer_atr',        1, '0.25', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.stop_sr_buffer_atr',           1, '0.50', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.stop_fallback_atr',            1, '2.0',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.zone_sweep_atr',               1, '0.76', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.zone_low_atr',                 1, '1.0',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.zone_high_atr',                1, '0.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.target_min_atr',               1, '0.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.zone_plugin_fallback_atr',     1, '0.2',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.vp_proximity_atr',             1, '0.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.fallback_t1_atr',              1, '2.0',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.fallback_t2_atr',              1, '3.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.fallback_t3_atr',              1, '5.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.min_stop_atr',                 1, '1.0',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'threshold.trade_framer.min_rr_t1',                  1, '1.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.adaptive_buffer_hard_cap',     1, '1.40', 'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant'),
(NOW(), 'feature.trade_framer.structure_snap_proximity_atr', 1, '1.5',  'migration_145', 'Phase 132 A5 APR seed — trade_framer module-level constant');
