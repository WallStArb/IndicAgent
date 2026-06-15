-- Migration 135: Seed Phase 126 signal quality audit thresholds into APR.
--
-- IC validation thresholds per D-13 in Phase 126 CONTEXT.md.
-- These are initial estimates based on conventional statistical thresholds and
-- Renaissance first-principles analysis (predictive power floor, noise floor).
-- All are ML learning targets post Phase 127 replay.

-- -------------------------------------------------------------------------
-- config_schema entries
-- -------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('threshold.signal_audit.ic_validated_floor', 'float', '0.02', -1.0, 1.0,
 '[conventional — Pearson IC > 0.02 is the standard predictive power threshold for financial ML. ML learning target post Phase 127 replay.] Minimum IC for a plugin to be classified VALIDATED. Plugins above this threshold and with hit_rate CI lower > hit_rate_validated_floor are considered statistically predictive.'),
('threshold.signal_audit.ic_anti_signal_ceiling', 'float', '-0.02', -1.0, 1.0,
 '[conventional — symmetric lower bound to ic_validated_floor. ML learning target post Phase 127 replay.] Maximum IC for a plugin to be classified ANTI-SIGNAL. Plugins below this threshold are negatively predictive and get shadow_only=True pending redesign.'),
('threshold.signal_audit.hit_rate_validated_floor', 'float', '0.45', 0.0, 1.0,
 '[conventional — >45% hit rate CI lower ensures the 95% CI lower bound is above the noise floor. ML learning target post Phase 127 replay.] Minimum bootstrap 95% CI lower bound on hit_rate for VALIDATED classification. Ensures statistical confidence the plugin is above random.'),
('threshold.signal_audit.hit_rate_anti_signal_ceiling', 'float', '0.45', 0.0, 1.0,
 '[conventional — symmetric with hit_rate_validated_floor. ML learning target post Phase 127 replay.] Maximum bootstrap 95% CI upper bound on hit_rate for ANTI-SIGNAL classification. A CI upper bound below 0.45 means even the optimistic estimate is below the noise floor.'),
('threshold.signal_audit.verifiable_population_floor', 'float', '0.90', 0.0, 1.0,
 '[initial_estimate] Minimum fraction of sampled signals with required detection-condition fields populated for VERIFIABLE verdict. Below this threshold: PARTIAL (>=0.50) or UNVERIFIABLE (<0.50).'),
('threshold.signal_audit.partial_population_floor', 'float', '0.50', 0.0, 1.0,
 '[initial_estimate] Minimum fraction for PARTIAL verdict. Below this: UNVERIFIABLE - plugin fires on stale or absent feature data.')
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_state entries
-- -------------------------------------------------------------------------

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.signal_audit.ic_validated_floor',           '0.02',  1),
('threshold.signal_audit.ic_anti_signal_ceiling',       '-0.02', 1),
('threshold.signal_audit.hit_rate_validated_floor',     '0.45',  1),
('threshold.signal_audit.hit_rate_anti_signal_ceiling', '0.45',  1),
('threshold.signal_audit.verifiable_population_floor',  '0.90',  1),
('threshold.signal_audit.partial_population_floor',     '0.50',  1)
ON CONFLICT (config_key) DO NOTHING;

-- -------------------------------------------------------------------------
-- config_history seed
-- -------------------------------------------------------------------------

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.signal_audit.ic_validated_floor',           1, '0.02',  'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit D-13 thresholds'),
(NOW(), 'threshold.signal_audit.ic_anti_signal_ceiling',       1, '-0.02', 'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit D-13 thresholds'),
(NOW(), 'threshold.signal_audit.hit_rate_validated_floor',     1, '0.45',  'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit D-13 thresholds'),
(NOW(), 'threshold.signal_audit.hit_rate_anti_signal_ceiling', 1, '0.45',  'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit D-13 thresholds'),
(NOW(), 'threshold.signal_audit.verifiable_population_floor',  1, '0.90',  'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit verifiability thresholds'),
(NOW(), 'threshold.signal_audit.partial_population_floor',     1, '0.50',  'initial_estimate', 'Migration 135 seed — Phase 126 signal quality audit verifiability thresholds');
