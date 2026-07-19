-- Migration 125: Seed Phase 124 plugin parameters into APR.
--
-- Covers all thresholds used by the 5 Phase-124 rewritten I7 plugins:
-- TrendFollowing, OFIContinuation, PatternCompletion, LiquiditySweepReclaim,
-- AnchoredVWAPReversion. Seed values match existing module-level constants
-- exactly — zero behaviour change at rollout.
-- All marked [initial_estimate] or [conventional]; ML learning targets noted.

-- schema entries

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('threshold.trend_following.regime_min', 'float', '0.5', 0.0, 1.0,
 '[initial_estimate] Min |trend_regime| score before TrendFollowingPlugin gates pass. ML learning target.'),
('threshold.trend_following.confidence_min', 'float', '0.4', 0.0, 1.0,
 '[initial_estimate] Min trend_confidence for TrendFollowingPlugin gate. ML learning target.'),
('threshold.trend_following.pullback_min_bars', 'int', '5', 1, 50,
 '[conventional] Min bars below/above SMA before pullback reversal qualifies as structural event. ML learning target.'),
('threshold.trend_following.consolidation_min_bars', 'int', '5', 1, 50,
 '[conventional] Min bars in tight range before breakout qualifies as consolidation event. ML learning target.'),
('threshold.trend_following.consolidation_range_pct', 'float', '0.5', 0.01, 5.0,
 '[initial_estimate] Max high-low range as % of price for a bar to count as consolidation. ML learning target.'),
('threshold.ofi_continuation.min_bars', 'int', '10', 1, 50,
 '[initial_estimate] Min consecutive directional OFI bars before OFIContinuationPlugin can fire. ML learning target.'),
('threshold.ofi_continuation.ewma_min_history', 'int', '5', 2, 20,
 '[conventional] Min EWMA buffer depth before second-derivative acceleration is computable. Structural minimum, not ML target.'),
('threshold.ofi_continuation.volume_spike_ratio', 'float', '2.0', 1.0, 10.0,
 '[initial_estimate] Min volume/volume_sma_20 ratio for volume spike structural trigger. ML learning target.'),
('threshold.ofi_continuation.acceleration_floor_fraction', 'float', '0.10', 0.01, 1.0,
 '[initial_estimate] EWMA acceleration must be >= this fraction of magnitude floor to qualify. ML learning target.'),
('threshold.ofi_continuation.upper_ref_multiplier', 'float', '4.0', 1.0, 20.0,
 '[conventional] Upper OFI reference = magnitude_floor * this multiplier. Structural ratio, ML target per instrument.'),
('threshold.ofi_continuation.magnitude_floors', 'json', '''{\"ES\":500.0,\"NQ\":200.0,\"CL\":1000.0,\"GC\":500.0,\"_default\":500.0}''', null, null,
 '[initial_estimate] Per-symbol OFI magnitude floor (noise rejection gate). JSON dict keyed by base symbol. ML learning target per instrument.'),
('threshold.pattern_completion.confidence_min', 'float', '0.70', 0.0, 1.0,
 '[initial_estimate] Min pattern confidence for PatternCompletionPlugin to fire. ML learning target.'),
('threshold.vwap_reversion.sigma_min', 'float', '1.5', 0.5, 5.0,
 '[conventional] Min |session_vwap_deviation_sigma| to qualify as a departure from VWAP. 1.5 = ~87th percentile. ML learning target.'),
('threshold.vwap_reversion.hurst_max', 'float', '0.55', 0.3, 0.7,
 '[conventional] Max Hurst exponent to confirm mean-reverting regime for AnchoredVWAPReversionPlugin. ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- live state entries

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.trend_following.regime_min',               '0.5',   1),
('threshold.trend_following.confidence_min',           '0.4',   1),
('threshold.trend_following.pullback_min_bars',        '5',     1),
('threshold.trend_following.consolidation_min_bars',   '5',     1),
('threshold.trend_following.consolidation_range_pct',  '0.5',   1),
('threshold.ofi_continuation.min_bars',                '10',    1),
('threshold.ofi_continuation.ewma_min_history',        '5',     1),
('threshold.ofi_continuation.volume_spike_ratio',      '2.0',   1),
('threshold.ofi_continuation.acceleration_floor_fraction', '0.10', 1),
('threshold.ofi_continuation.upper_ref_multiplier',    '4.0',   1),
('threshold.ofi_continuation.magnitude_floors',        '{"ES":500.0,"NQ":200.0,"CL":1000.0,"GC":500.0,"_default":500.0}', 1),
('threshold.pattern_completion.confidence_min',        '0.70',  1),
('threshold.vwap_reversion.sigma_min',                 '1.5',   1),
('threshold.vwap_reversion.hurst_max',                 '0.55',  1)
ON CONFLICT (config_key) DO NOTHING;

-- config_history seed

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.trend_following.regime_min',               1, '0.5',   'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.trend_following.confidence_min',           1, '0.4',   'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.trend_following.pullback_min_bars',        1, '5',     'conventional',     'Migration 131 seed'),
(NOW(), 'threshold.trend_following.consolidation_min_bars',   1, '5',     'conventional',     'Migration 131 seed'),
(NOW(), 'threshold.trend_following.consolidation_range_pct',  1, '0.5',   'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.min_bars',                1, '10',    'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.ewma_min_history',        1, '5',     'conventional',     'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.volume_spike_ratio',      1, '2.0',   'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.acceleration_floor_fraction', 1, '0.10', 'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.upper_ref_multiplier',    1, '4.0',   'conventional',     'Migration 131 seed'),
(NOW(), 'threshold.ofi_continuation.magnitude_floors',        1, '{"ES":500.0,"NQ":200.0,"CL":1000.0,"GC":500.0,"_default":500.0}', 'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.pattern_completion.confidence_min',        1, '0.70',  'initial_estimate', 'Migration 131 seed'),
(NOW(), 'threshold.vwap_reversion.sigma_min',                 1, '1.5',   'conventional',     'Migration 131 seed'),
(NOW(), 'threshold.vwap_reversion.hurst_max',                 1, '0.55',  'conventional',     'Migration 131 seed');
