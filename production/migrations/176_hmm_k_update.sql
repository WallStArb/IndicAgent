-- Migration 176: HMM state count K update — 3 → 5 (BIC K-selection study 2026-06-26).
--
-- BIC study on SPY/TLT/GLD/EWT 5m data (467k+ obs each) found K=5 minimizes BIC
-- unanimously across all 4 symbols. K=3 was the initial estimate with no empirical
-- validation. K=5 captures:
--   trending_up, transition_up, ranging, transition_down, trending_down
-- vs the previous 3-state: trending_up, ranging, trending_down.
--
-- After applying this migration, run:
--   python services/regime_writer.py --workers 12 --refit
-- to re-label all feature_vectors rows with the validated K=5 model.

BEGIN;

UPDATE config_state
SET config_value = '5',
    version      = version + 1
WHERE config_key = 'feature.hmm.n_components';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(),
       'feature.hmm.n_components',
       version,
       '5',
       'migration_176',
       'BIC K-selection study 2026-06-26: K=5 minimizes BIC on SPY/TLT/GLD/EWT 5m data (unanimous across 4 symbols); was K=3 [initial_estimate]'
FROM config_state
WHERE config_key = 'feature.hmm.n_components';

COMMIT;
