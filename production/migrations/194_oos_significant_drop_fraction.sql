-- Migration 194: alpha.validation.oos_significant_drop_fraction APR key
--
-- scripts/ops/corpus/ops_oos_holdout_eval.py hardcoded the "significant drop"
-- verdict threshold inline: `oos_qualifying < in_sample * 0.5`. Introduced in
-- Phase 141.1 (141.1-01); flagged in the phase's own code review (WR-02) as
-- an unbacked magic number, violating CLAUDE.md's migrate-as-you-go mandate.
--
-- No behavior change at the default value (0.5 == the current literal).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  (
    'alpha.validation.oos_significant_drop_fraction',
    'float',
    '0.5',
    'Fraction of in-sample qualifying-cell count below which the OOS holdout '
    'diagnostic scorer (ops_oos_holdout_eval.py, non-gating) reports a '
    '"significant drop — investigate" verdict for a TF. [initial_estimate]'
  )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('alpha.validation.oos_significant_drop_fraction', '0.5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'alpha.validation.oos_significant_drop_fraction', 1, '0.5', 'migration',
   'Phase 141.1 code review WR-02 migrate-as-you-go')
ON CONFLICT DO NOTHING;

COMMIT;
