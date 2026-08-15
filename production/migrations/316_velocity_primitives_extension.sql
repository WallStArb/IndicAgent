-- Migration 316: Velocity Primitives Extension (todo 320)
--
-- Extends the Phase 151 Plan 01 Task 2 velocity construction
-- (first-difference-then-re-z-scored, _vol_velocity_z_series_full) to 6
-- fields the original sweep didn't reach: RSI at all 3 gradients (one
-- shared window, matching momentum_z_velocity's own one-key-for-3-gradients
-- precedent) and the two single-field order-flow z-scores OFI/CVD-slope.
-- volume_z_velocity closes the gap vol_acceleration left (a crude 1-bar
-- V_t/V_{t-1} ratio, not a proper z-scored velocity like every other
-- _velocity field). adx_velocity was considered and dropped: adx has no
-- precomputed full-history array in _precompute_series (sourced from
-- cache.adx, a stateful incremental indicator external to the vectorized
-- batch path) -- reusing this helper on it needs a new _adx_series_full()
-- vectorized implementation first, a separate task.
--
-- Column type: real (float32), matching the current live schema convention
-- established by migration 312 -- every feature_vectors column added since
-- then follows it (no float64 column exists in this table; every
-- consumer already truncates to float32 on read). ADD COLUMN IF NOT EXISTS
-- with no DEFAULT is metadata-only against the compressed hypertable -- no
-- decompress/recompress/VACUUM step required (confirmed via migration
-- 197/206/216/255/266/267/293 precedent; only a decompress -> ALTER COLUMN
-- TYPE -> recompress on EXISTING data needs the VACUUM step documented in
-- docs/foundation/timescaledb-compressed-column-migration.md, not a plain
-- ADD COLUMN).
--
-- feature_registry no longer exists (DROPped by migration 311, Phase 170) --
-- concept_registry is the sole feature-lifecycle system now, so this
-- migration seeds it directly (no feature_registry INSERT + parity-mirror
-- step like migration 293's pattern).

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. feature_vectors: 6 new columns
-- ---------------------------------------------------------------------------

ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_velocity_fast real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_velocity_mid real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS rsi_velocity_slow real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS ofi_z_velocity real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS cvd_slope_z_velocity real;
ALTER TABLE feature_vectors ADD COLUMN IF NOT EXISTS volume_z_velocity real;

COMMENT ON COLUMN feature_vectors.rsi_velocity_fast IS
    'z-score of the rolling velocity (first difference) of rsi_fast over feature.rsi_velocity.window bars. Todo 320.';
COMMENT ON COLUMN feature_vectors.rsi_velocity_mid IS
    'z-score of the rolling velocity (first difference) of rsi_mid over feature.rsi_velocity.window bars. Todo 320.';
COMMENT ON COLUMN feature_vectors.rsi_velocity_slow IS
    'z-score of the rolling velocity (first difference) of rsi_slow over feature.rsi_velocity.window bars. Todo 320.';
COMMENT ON COLUMN feature_vectors.ofi_z_velocity IS
    'z-score of the rolling velocity (first difference) of ofi_z over feature.ofi_velocity.window bars. Todo 320.';
COMMENT ON COLUMN feature_vectors.cvd_slope_z_velocity IS
    'z-score of the rolling velocity (first difference) of cvd_slope_z over feature.cvd_velocity.window bars. Todo 320.';
COMMENT ON COLUMN feature_vectors.volume_z_velocity IS
    'z-score of the rolling velocity (first difference) of volume_z over feature.volume_velocity.window bars. Todo 320.';

-- ---------------------------------------------------------------------------
-- 2. APR keys: feature.rsi_velocity.window, feature.ofi_velocity.window,
--    feature.cvd_velocity.window, feature.volume_velocity.window
-- ---------------------------------------------------------------------------

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'feature.rsi_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for the first-difference-then-z-score construction behind rsi_velocity_fast/mid/slow. Seeded to match feature.vol_velocity.window''s live value (14), same precedent as feature.momentum_velocity.window. Todo 320. ML learning target: yes.'
),
(
    'feature.ofi_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for ofi_z_velocity. Separate key from feature.rsi_velocity.window per naming-system.md section 7 (semantically distinct family). Todo 320. ML learning target: yes.'
),
(
    'feature.cvd_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for cvd_slope_z_velocity. Separate key from feature.ofi_velocity.window per naming-system.md section 7 (semantically distinct family). Todo 320. ML learning target: yes.'
),
(
    'feature.volume_velocity.window',
    'int',
    '14',
    2, 200,
    '[conventional] Bar-lag window for volume_z_velocity. Separate key from feature.cvd_velocity.window per naming-system.md section 7 (semantically distinct family). Todo 320. ML learning target: yes.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.rsi_velocity.window', '14', 1),
    ('feature.ofi_velocity.window', '14', 1),
    ('feature.cvd_velocity.window', '14', 1),
    ('feature.volume_velocity.window', '14', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'feature.rsi_velocity.window', 1, '14', 'migration_316',
     'Seed RSI-velocity z-score window, todo 320 [conventional]'),
    (NOW(), 'feature.ofi_velocity.window', 1, '14', 'migration_316',
     'Seed OFI-velocity z-score window, todo 320 [conventional]'),
    (NOW(), 'feature.cvd_velocity.window', 1, '14', 'migration_316',
     'Seed CVD-slope-velocity z-score window, todo 320 [conventional]'),
    (NOW(), 'feature.volume_velocity.window', 1, '14', 'migration_316',
     'Seed volume-velocity z-score window, todo 320 [conventional]')
ON CONFLICT DO NOTHING;

-- ---------------------------------------------------------------------------
-- 3. concept_registry / concept_gate: 6 new rows (domain='feature',
--    tier='0_atomic'). feature_registry no longer exists (migration 311) --
--    concept_registry is seeded directly, no parity-mirror step.
-- ---------------------------------------------------------------------------

INSERT INTO concept_registry
    (domain, name, description, status, enabled, group_name, is_control, added_phase, metadata)
VALUES
    ('feature', 'rsi_velocity_fast', 'zscore(diff(rsi_fast))', 'active', true, 'momentum', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(rsi_fast))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.')),
    ('feature', 'rsi_velocity_mid', 'zscore(diff(rsi_mid))', 'active', true, 'momentum', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(rsi_mid))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.')),
    ('feature', 'rsi_velocity_slow', 'zscore(diff(rsi_slow))', 'active', true, 'momentum', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(rsi_slow))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.')),
    ('feature', 'ofi_z_velocity', 'zscore(diff(ofi_z))', 'active', true, 'quant', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(ofi_z))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.')),
    ('feature', 'cvd_slope_z_velocity', 'zscore(diff(cvd_slope_z))', 'active', true, 'quant', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(cvd_slope_z))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.')),
    ('feature', 'volume_z_velocity', 'zscore(diff(volume_z))', 'active', true, 'volume', false, 'todo320',
     jsonb_build_object('tier', '0_atomic', 'formula_short', 'zscore(diff(volume_z))',
         'normalization', 'z_scored', 'linear_ready', true, 'requires_htf', false,
         'apr_namespace', 'feature.'))
ON CONFLICT (domain, name) DO NOTHING;

INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required, fdr_alpha)
SELECT cr.concept_id, 'ic_sharpe_hac', 'bootstrap_ci', 100, true, 0.05
FROM concept_registry cr
WHERE cr.domain = 'feature'
  AND cr.name IN (
    'rsi_velocity_fast', 'rsi_velocity_mid', 'rsi_velocity_slow',
    'ofi_z_velocity', 'cvd_slope_z_velocity', 'volume_z_velocity'
  )
ON CONFLICT (concept_id) DO NOTHING;

COMMIT;
