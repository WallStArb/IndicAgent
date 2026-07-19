-- Migration 126: Seed Phase 125 APR keys — CIS gate constants, zone entry width gate, VWAP reversion weights.
--
-- Covers three clusters:
--   1. CIS gate constants (3 keys): fire_threshold, bucket_agree_min, bucket_noise_floor
--   2. Zone entry width gate (4 keys): min_zone_width_atr + asset-class variants
--   3. AnchoredVWAPReversion confidence weights (3 keys): sigma_magnitude, hurst_quality, vol_stability
--
-- Seed values match existing module-level constants exactly (zero behaviour change at rollout).
-- Plans B, D, and E in Phase 125 read these keys via ConfigService.get_sync().
-- Phase 126 consumption code for zone-width keys ships after this migration.
-- All keys are new — DO NOT confuse feature.zone_engine.min_zone_width_atr with the
-- existing feature.zone_engine.min_width_atr (seeded at 0.25 in migration 129).

-- schema entries

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
('threshold.cis.fire_threshold', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] Min filtered_cis score for the CIS dual gate to allow a signal to fire. Kalman-smoothed CIS must exceed this value. ML learning target.'),
('threshold.cis.bucket_agree_min', 'int', '3', 1, 6,
 '[initial_estimate] Min number of CIS buckets that must contribute a non-zero score before signal fires. Prevents thin-bucket noise signals. ML learning target.'),
('threshold.cis.bucket_noise_floor', 'float', '0.1', 0.0, 1.0,
 '[initial_estimate] Min per-bucket score to count as a contributing bucket in the bucket_agree_min gate. Scores below this are treated as zero. ML learning target.'),
('feature.zone_engine.min_zone_width_atr', 'float', '1.5', 0.0, 10.0,
 '[rca_analysis] Default min zone width in ATR multiples across all asset classes. Phase 126 zone entry width gate. Noise-band analysis. Not a learning target until Phase 126 consumption code ships.'),
('feature.zone_engine.min_zone_width_atr.equity', 'float', '1.5', 0.0, 10.0,
 '[rca_analysis] Phase 126 zone entry width gate for equity instruments. Noise-band analysis. Not a learning target until Phase 126 consumption code ships.'),
('feature.zone_engine.min_zone_width_atr.fx', 'float', '1.0', 0.0, 10.0,
 '[rca_analysis] Phase 126 zone entry width gate for FX instruments. Tighter spread; calibrated lower than futures/equity. Not a learning target until Phase 126 consumption code ships.'),
('feature.zone_engine.min_zone_width_atr.futures', 'float', '1.5', 0.0, 10.0,
 '[rca_analysis] Phase 126 zone entry width gate for futures instruments. Noise-band analysis. Not a learning target until Phase 126 consumption code ships.'),
('weights.vwap_reversion.sigma_magnitude', 'float', '0.40', 0.0, 1.0,
 '[initial_estimate] sigma_magnitude factor weight in AnchoredVWAPReversionPlugin confidence calculation. ML learning target.'),
('weights.vwap_reversion.hurst_quality', 'float', '0.35', 0.0, 1.0,
 '[initial_estimate] hurst_quality factor weight in AnchoredVWAPReversionPlugin confidence calculation. ML learning target.'),
('weights.vwap_reversion.vol_stability', 'float', '0.25', 0.0, 1.0,
 '[initial_estimate] vol_stability factor weight in AnchoredVWAPReversionPlugin confidence calculation. ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

-- live state entries

INSERT INTO config_state (config_key, config_value, version) VALUES
('threshold.cis.fire_threshold',                        '0.35',  1),
('threshold.cis.bucket_agree_min',                      '3',     1),
('threshold.cis.bucket_noise_floor',                    '0.1',   1),
('feature.zone_engine.min_zone_width_atr',              '1.5',   1),
('feature.zone_engine.min_zone_width_atr.equity',        '1.5',   1),
('feature.zone_engine.min_zone_width_atr.fx',           '1.0',   1),
('feature.zone_engine.min_zone_width_atr.futures',      '1.5',   1),
('weights.vwap_reversion.sigma_magnitude',              '0.40',  1),
('weights.vwap_reversion.hurst_quality',                '0.35',  1),
('weights.vwap_reversion.vol_stability',                '0.25',  1)
ON CONFLICT (config_key) DO NOTHING;

-- config_history seed

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
(NOW(), 'threshold.cis.fire_threshold',                      1, '0.35',  'migration_132', 'Phase 125 APR seed: CIS gate constants'),
(NOW(), 'threshold.cis.bucket_agree_min',                    1, '3',     'migration_132', 'Phase 125 APR seed: CIS gate constants'),
(NOW(), 'threshold.cis.bucket_noise_floor',                  1, '0.1',   'migration_132', 'Phase 125 APR seed: CIS gate constants'),
(NOW(), 'feature.zone_engine.min_zone_width_atr',            1, '1.5',   'migration_132', 'Phase 125 APR seed: zone entry width gate'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.equity',      1, '1.5',   'migration_132', 'Phase 125 APR seed: zone entry width gate'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.fx',         1, '1.0',   'migration_132', 'Phase 125 APR seed: zone entry width gate'),
(NOW(), 'feature.zone_engine.min_zone_width_atr.futures',    1, '1.5',   'migration_132', 'Phase 125 APR seed: zone entry width gate'),
(NOW(), 'weights.vwap_reversion.sigma_magnitude',            1, '0.40',  'migration_132', 'Phase 125 APR seed: AnchoredVWAPReversion weights'),
(NOW(), 'weights.vwap_reversion.hurst_quality',              1, '0.35',  'migration_132', 'Phase 125 APR seed: AnchoredVWAPReversion weights'),
(NOW(), 'weights.vwap_reversion.vol_stability',              1, '0.25',  'migration_132', 'Phase 125 APR seed: AnchoredVWAPReversion weights');
