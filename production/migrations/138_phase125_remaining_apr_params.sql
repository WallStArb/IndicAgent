-- Migration 138: Seed APR parameters for remaining module-level constants and plugin dataclasses.
--
-- Wires 8 files that were using hardcoded module-level constants:
--   - confidence_utils: CONF_CEIL (global ceiling)
--   - microstructure_utils: _SPIKE_THRESHOLD (shared spike gate)
--   - state_utils: _DEDUP_MIN_BARS (shared dedup window)
--   - delta_exhaustion: 2 gates + 4 confidence weights
--   - cvd_divergence: 2 gates + 1 feature ref + 1 dual-flag threshold
--   - dual_divergence: confirmation_bars (thresholds already seeded in migration 129)
--   - divergence_stack: 2 gates + 1 norm constant + 5 confidence weights
--   - vwap_reclaim: vol_threshold (weights already seeded in migration 129)
--
-- All weights are ML learning targets post Phase 127 replay.
-- Thresholds carry [conventional] or [rca_analysis] provenance as noted.

-- -------------------------------------------------------------------------
-- config_schema
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES

-- confidence_utils: global confidence ceiling
('threshold.global.conf_ceil', 'float', '0.95', 0.50, 1.0,
 '[conventional] Maximum allowed raw confidence for any I7 signal before compose_confidence() clamp. 0.95 preserves discrimination at the top; hard ceiling prevents over-confidence. Operator preference; not ML learning target.'),

-- microstructure_utils: shared OFI/CVD spike detection gate
('threshold.microstructure.spike_z', 'float', '2.0', 0.5, 5.0,
 '[conventional] Minimum abs z-score to classify a microstructure bar as a spike (OFISpike, CVDSpike). 2.0σ is the standard statistical outlier threshold. ML learning target post Phase 127 replay.'),

-- state_utils: shared dedup window
('feature.state.dedup_min_bars', 'int', '20', 1, 100,
 '[conventional] Minimum active-condition bars between re-fires of the same event_id in deduplicate_event(). 20 bars (~20 minutes on 1m) prevents rapid re-fire on persistent upstream events. ML learning target.'),

-- delta_exhaustion: detection gates
('threshold.delta_exhaustion.spike_z', 'float', '1.5', 0.5, 5.0,
 '[conventional] Minimum abs(cvd_spike_z) to enter DeltaExhaustion detection. 1.5σ is lower than OFI/CVD spike (2.0σ) — exhaustion fires on weaker spikes since price failure is the confirming gate. ML learning target post Phase 127 replay.'),
('threshold.delta_exhaustion.price_follow_atr', 'float', '0.3', 0.05, 2.0,
 '[conventional] Maximum abs(price_change)/ATR for price to be classified as "failed to follow" CVD spike. 0.3 ATR = weak follow-through; above this threshold the spike is price-confirmed (not exhausted). ML learning target post Phase 127 replay.'),

-- delta_exhaustion: confidence weights
('weights.delta_exhaustion.cvd_z', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] DeltaExhaustion confidence weight: CVD spike magnitude above threshold. ML learning target.'),
('weights.delta_exhaustion.price_fail', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] DeltaExhaustion confidence weight: price failure score (1.0 = zero follow-through). ML learning target.'),
('weights.delta_exhaustion.hmm_ranging', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] DeltaExhaustion confidence weight: HMM ranging regime alignment magnitude. ML learning target.'),
('weights.delta_exhaustion.persistence', 'float', '0.10', 0.0, 1.0,
 '[initial_estimate] DeltaExhaustion confidence weight: CVD spike persistence proxy. ML learning target.'),

-- cvd_divergence: confirmation gate + divergence thresholds
('feature.cvd_divergence.confirmation_bars', 'int', '5', 1, 20,
 '[rca_analysis] Consecutive bars of CVD-vs-price divergence required before CVDDivergence fires. 5 bars chosen from 90d replay analysis (n=227836 firings); balances persistence signal vs latency. ML learning target post Phase 127 replay.'),
('threshold.cvd_divergence.div_threshold', 'float', '1.0', 0.0, 3.0,
 '[rca_analysis] Minimum abs(cvd_divergence) to pass detection gate. 1.0 = p75 of abs distribution (90d, n=227836); filters zero-divergence noise while keeping top quartile. ML learning target.'),
('feature.cvd_divergence.div_upper_ref', 'float', '2.0', 1.0, 5.0,
 '[rca_analysis] Upper reference for CVD divergence confidence normalization. 2.0 = p90 of abs distribution (90d, n=227836); maps full divergence (slope_dir opposite price_dir) to 1.0 confidence factor. Not a gate; normalization constant. Not a primary ML target.'),
('threshold.cvd_divergence.ofi_dual_threshold', 'float', '1.0', 0.0, 3.0,
 '[conventional] Minimum abs(ofi_divergence) required to flag dual_divergence=True on a CVDDivergence signal. 1.0 matches div_threshold — both measures must be at the same significance level for dual confirmation. Operator preference; not ML target.'),

-- dual_divergence: confirmation gate (thresholds already in migration 129)
('feature.dual_divergence.confirmation_bars', 'int', '3', 1, 10,
 '[conventional] Consecutive bars of simultaneous OFI+CVD divergence required before DualDivergence fires. 3 bars (tighter than CVDDivergence 5-bar) reflects the higher intrinsic signal quality of dual confirmation. ML learning target post Phase 127 replay.'),

-- divergence_stack: gates and normalization
('threshold.divergence_stack.score_threshold', 'float', '0.40', 0.0, 1.0,
 '[conventional] Minimum weighted divergence score to pass DivergenceStack detection gate. 0.40 requires at least the top 2-3 inputs to contribute. ML learning target post Phase 127 replay.'),
('feature.divergence_stack.min_agreeing', 'int', '3', 1, 5,
 '[conventional] Minimum number of divergence inputs (of 5) required to agree for DivergenceStack to fire. 3 of 5 = supermajority; prevents low-breadth fires. ML learning target.'),
('feature.divergence_stack.confidence_norm', 'float', '0.60', 0.1, 1.0,
 '[conventional] Denominator for DivergenceStack base_score normalization. 0.60 = practical 3-input maximum (top-3 weights: 0.30+0.25+0.20). Maps realistic max score to 1.0 confidence. Not an ML target; operator preference.'),

-- divergence_stack: confidence weights
('weights.divergence_stack.rsi', 'float', '0.30', 0.0, 1.0,
 '[initial_estimate] DivergenceStack confidence weight: RSI divergence input. Highest weight — RSI is most stable divergence measure. ML learning target.'),
('weights.divergence_stack.macd', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] DivergenceStack confidence weight: MACD divergence input. ML learning target.'),
('weights.divergence_stack.vol', 'float', '0.20', 0.0, 1.0,
 '[initial_estimate] DivergenceStack confidence weight: Volume/OBV divergence input. ML learning target.'),
('weights.divergence_stack.obv', 'float', '0.15', 0.0, 1.0,
 '[initial_estimate] DivergenceStack confidence weight: OBV divergence input. ML learning target.'),
('weights.divergence_stack.cmf', 'float', '0.10', 0.0, 1.0,
 '[initial_estimate] DivergenceStack confidence weight: CMF divergence input. Lowest weight — CMF is noisiest measure. ML learning target.'),

-- vwap_reclaim: volume gate (weights already in migration 129)
('threshold.vwap_reclaim.vol_threshold', 'float', '1.2', 0.5, 5.0,
 '[conventional] Minimum volume expansion ratio (rel_volume or bar/session_avg) for VWAPReclaim gate. 1.2x is a modest expansion threshold appropriate for VWAP crosses. ML learning target post Phase 127 replay.')

ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.global.conf_ceil',                    '0.95', 1),
('threshold.microstructure.spike_z',              '2.0',  1),
('feature.state.dedup_min_bars',                  '20',   1),
('threshold.delta_exhaustion.spike_z',            '1.5',  1),
('threshold.delta_exhaustion.price_follow_atr',   '0.3',  1),
('weights.delta_exhaustion.cvd_z',                '0.35', 1),
('weights.delta_exhaustion.price_fail',           '0.30', 1),
('weights.delta_exhaustion.hmm_ranging',          '0.25', 1),
('weights.delta_exhaustion.persistence',          '0.10', 1),
('feature.cvd_divergence.confirmation_bars',      '5',    1),
('threshold.cvd_divergence.div_threshold',        '1.0',  1),
('feature.cvd_divergence.div_upper_ref',          '2.0',  1),
('threshold.cvd_divergence.ofi_dual_threshold',   '1.0',  1),
('feature.dual_divergence.confirmation_bars',     '3',    1),
('threshold.divergence_stack.score_threshold',    '0.40', 1),
('feature.divergence_stack.min_agreeing',         '3',    1),
('feature.divergence_stack.confidence_norm',      '0.60', 1),
('weights.divergence_stack.rsi',                  '0.30', 1),
('weights.divergence_stack.macd',                 '0.25', 1),
('weights.divergence_stack.vol',                  '0.20', 1),
('weights.divergence_stack.obv',                  '0.15', 1),
('weights.divergence_stack.cmf',                  '0.10', 1),
('threshold.vwap_reclaim.vol_threshold',          '1.2',  1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.global.conf_ceil',                    1, '0.95', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.microstructure.spike_z',              1, '2.0',  'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.state.dedup_min_bars',                  1, '20',   'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.delta_exhaustion.spike_z',            1, '1.5',  'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.delta_exhaustion.price_follow_atr',   1, '0.3',  'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.delta_exhaustion.cvd_z',                1, '0.35', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.delta_exhaustion.price_fail',           1, '0.30', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.delta_exhaustion.hmm_ranging',          1, '0.25', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.delta_exhaustion.persistence',          1, '0.10', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.cvd_divergence.confirmation_bars',      1, '5',    'rca_analysis',     'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.cvd_divergence.div_threshold',        1, '1.0',  'rca_analysis',     'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.cvd_divergence.div_upper_ref',          1, '2.0',  'rca_analysis',     'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.cvd_divergence.ofi_dual_threshold',   1, '1.0',  'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.dual_divergence.confirmation_bars',     1, '3',    'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.divergence_stack.score_threshold',    1, '0.40', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.divergence_stack.min_agreeing',         1, '3',    'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'feature.divergence_stack.confidence_norm',      1, '0.60', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.divergence_stack.rsi',                  1, '0.30', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.divergence_stack.macd',                 1, '0.25', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.divergence_stack.vol',                  1, '0.20', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.divergence_stack.obv',                  1, '0.15', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'weights.divergence_stack.cmf',                  1, '0.10', 'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params'),
(NOW(), 'threshold.vwap_reclaim.vol_threshold',          1, '1.2',  'initial_estimate', 'Migration 138 seed — Phase 125 APR remaining params');
