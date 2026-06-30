-- Migration 186: APR seeds for Renaissance IC gate redesign (A5)
--
-- Adds two parameters for the new quality_weight formula in ensemble_trainer:
--   quality_weight = ic_ci_lower * max(sharpe_floor, ic_sharpe_hac)
--
-- sharpe_floor ensures features with positive CI but near-zero Sharpe still
-- receive a small positive weight (Renaissance principle: aggregate many weak signals).
--
-- wf_consistency_factor is reserved for future walk-forward consistency weighting
-- and is NOT applied in the current ensemble. Added to APR now to document intent
-- and allow operator tuning without a future migration.

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  (
    'alpha.ensemble.sharpe_floor',
    'float',
    '0.05',
    'Floor for ic_sharpe_hac in quality_weight formula (ic_ci_lower * max(sharpe_floor, ic_sharpe_hac)). Ensures features with positive CI but near-zero Sharpe still receive a small positive weight. [initial_estimate]'
  ),
  (
    'alpha.ensemble.wf_consistency_factor',
    'float',
    '0.5',
    'Weight multiplier applied when wf_pass_count < walk_forward_folds (reserved for future use - not applied in current ensemble). [initial_estimate]'
  )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.ensemble.sharpe_floor',       '0.05', 1),
  ('alpha.ensemble.wf_consistency_factor', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'alpha.ensemble.sharpe_floor',          1, '0.05', 'migration_186', 'Initial estimate: floor for quality_weight formula in ensemble gate redesign [initial_estimate]'),
  (NOW(), 'alpha.ensemble.wf_consistency_factor', 1, '0.5',  'migration_186', 'Reserved: future walk-forward consistency weighting - not applied yet [initial_estimate]');
