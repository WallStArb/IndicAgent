-- Migration 193: alpha.ensemble.weight_stale_max_days APR key (todo 043)
--
-- services/ensemble_trainer.py hardcodes the equal-weight staleness fallback
-- cliff inline: `if days_since > 90:`. Its sibling weight_half_life_days
-- (used for the exponential decay itself) is already APR-backed. This
-- migration closes that gap per CLAUDE.md's migrate-as-you-go mandate.
--
-- No behavior change at the default value (90 == the current literal).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  (
    'alpha.ensemble.weight_stale_max_days',
    'int',
    '90',
    'Days-since-training-window beyond which ensemble reverts IC-derived weights to '
    'equal-weight (IC scores too stale to trust the weight ordering). Sibling of '
    'alpha.ensemble.weight_half_life_days. [conventional]'
  )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.ensemble.weight_stale_max_days', '90', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'alpha.ensemble.weight_stale_max_days', 1, '90', 'migration',
   'todo 043 migrate-as-you-go')
ON CONFLICT DO NOTHING;

COMMIT;
