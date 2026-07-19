-- Migration 176: HMM quality refinements — full covariance, min hold, held-out validation.
--
-- Three new APR keys for regime_writer improvements (2026-06-28):
--   feature.hmm.covariance_type  — "full" captures feature cross-correlations vs "diag"
--   feature.hmm.min_hold_bars    — minimum consecutive bars before confirming state transition
--   feature.hmm.heldout_fraction — fraction of bars reserved for out-of-sample LL scoring
--
-- After applying this migration, truncate feature_vectors.regime and re-run regime_writer.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, allowed_values, description)
VALUES
  (
    'feature.hmm.covariance_type',
    'str',
    'full',
    '{full,diag,tied}',
    'GaussianHMM covariance structure. "full" captures cross-correlations between obs dims; '
    '"diag" assumes independence (faster, less expressive); "tied" shares one matrix. '
    'Falls back to "diag" if n_obs < full_cov_min_obs. [initial_estimate]'
  ),
  (
    'feature.hmm.min_hold_bars',
    'int',
    '3',
    NULL,
    'Minimum consecutive bars a new decoded state must persist before the transition is '
    'confirmed. Prevents single-bar flips when alpha is diffuse. Introduces at most '
    'min_hold_bars of lag on genuine transitions. [initial_estimate]'
  ),
  (
    'feature.hmm.heldout_fraction',
    'float',
    '0.2',
    NULL,
    'Fraction of bars (last N%) withheld from HMM fit for held-out log-likelihood scoring. '
    'Model is fit on the full series; held-out LL is logged as a diagnostic only — does not '
    'gate the write. [conventional]'
  ),
  (
    'feature.hmm.full_cov_min_obs',
    'int',
    '500',
    NULL,
    'Minimum observation count required to use covariance_type=full. Below this threshold '
    'regime_writer falls back to "diag" to avoid overfitting. [initial_estimate]'
  );

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('feature.hmm.covariance_type', 'full',  1),
  ('feature.hmm.min_hold_bars',   '3',     1),
  ('feature.hmm.heldout_fraction','0.2',   1),
  ('feature.hmm.full_cov_min_obs','500',   1);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'feature.hmm.covariance_type',  1, 'full',  'migration_179', 'Initial: full covariance captures obs feature cross-correlations [initial_estimate]'),
  (NOW(), 'feature.hmm.min_hold_bars',    1, '3',     'migration_179', 'Initial: 3-bar hold prevents single-bar flips in diffuse alpha [initial_estimate]'),
  (NOW(), 'feature.hmm.heldout_fraction', 1, '0.2',   'migration_179', 'Initial: 20% held-out for LL diagnostic [conventional]'),
  (NOW(), 'feature.hmm.full_cov_min_obs', 1, '500',   'migration_179', 'Initial: min obs to trust full covariance estimate [initial_estimate]');

COMMIT;
