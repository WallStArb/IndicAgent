-- Migration 265: fix stale config_schema.description for feature.hmm.n_components
--
-- Found during a Renaissance-rigor audit of APR gate provenance (2026-07-27): the live
-- config_state value has been 5 since migration 172 (2026-06-26 BIC K-selection study on
-- SPY/TLT/GLD/EWT 5m data, unanimous across all 4 symbols) and migration 176 (K-selection
-- finalization), and config_history's own reason text correctly cites that study. But
-- config_schema.description was never updated -- it still reads "[conventional] ... 3 =
-- ranging/trending-up/trending-down", describing the pre-study K=3 model. This is pure
-- documentation drift (the live value and its real empirical backing are both correct and
-- unaffected), not a calibration gap -- but a stale description masks a rare *genuinely
-- validated* gate as a mere convention, which is the opposite of the tagging discipline's
-- purpose (surfacing evidentiary weight honestly). Fixed to describe the real model and
-- cite the actual study, retagged [rca_analysis] (it is one) instead of [conventional].

BEGIN;

UPDATE config_schema
SET description = '[rca_analysis] Number of hidden states in the GaussianHMM. BIC '
    'K-selection study (2026-06-26, migration 172) found K=5 minimizes BIC on SPY/TLT/GLD/EWT '
    '5m data, unanimous across all 4 symbols -- superseded the prior K=3 [initial_estimate] '
    'default. Not an ML learning target (changes model topology, requires full retraining).'
WHERE config_key = 'feature.hmm.n_components';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'feature.hmm.n_components', version, config_value, 'migration_265',
       'Description-only fix: schema description still described the pre-migration-172 K=3 '
       'model despite the live value being 5 since 2026-06-26. No config_value change -- '
       'documentation drift fix, retagged [conventional]->[rca_analysis] to match reality.'
FROM config_state WHERE config_key = 'feature.hmm.n_components';

COMMIT;
