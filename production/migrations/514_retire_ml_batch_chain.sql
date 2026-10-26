-- Migration 514: retire what deleting the ML batch chain orphaned (todo 509 item 3, owner
-- decision 2026-10-26).
--
-- The chain (ml-training, ml-orchestrator, ml-discovery, ml-data-quality, hmm-training: its
-- services, units, timers, src/intelligence/services/{ml,hmm}_trainer.py, src/intelligence/ml/
-- and src/core/ml/) trained on v2.x signal outcomes and intelligence_features, which have had no
-- writer since plan 185-45. The live regime HMM is the registry kernel
-- (src/intelligence/features/kernels/_hmm.py), which never imported hmm_trainer. Revival
-- starts from git: e4d2345c2 is the last commit that holds the chain.
--
-- Tables: ml_models (ModelRegistry), ml_discovery_runs and ml_data_quality_runs had only the
-- deleted writers. All three are empty (0 rows, checked 2026-10-26), no view or foreign key
-- depends on them, and each was dumped to data/backups/509-ml-chain/ (SHA256SUMS there).
--
-- APR keys: feature.hmm.lookback_days.{1m,5m,15m,1h,4h,1d} and
-- feature.hmm.min_rows_for_training were read only by hmm_trainer. Retired in the order
-- history, state, schema. Rerun semantics: the DELETEs match nothing and the DROPs are IF
-- EXISTS. No compressed hypertable column is altered, so no VACUUM clause is owed.

BEGIN;

DROP TABLE IF EXISTS ml_models;
DROP TABLE IF EXISTS ml_discovery_runs;
DROP TABLE IF EXISTS ml_data_quality_runs;

DELETE FROM config_history
 WHERE config_key IN ('feature.hmm.lookback_days.1m',
                      'feature.hmm.lookback_days.5m',
                      'feature.hmm.lookback_days.15m',
                      'feature.hmm.lookback_days.1h',
                      'feature.hmm.lookback_days.4h',
                      'feature.hmm.lookback_days.1d',
                      'feature.hmm.min_rows_for_training');
DELETE FROM config_state
 WHERE config_key IN ('feature.hmm.lookback_days.1m',
                      'feature.hmm.lookback_days.5m',
                      'feature.hmm.lookback_days.15m',
                      'feature.hmm.lookback_days.1h',
                      'feature.hmm.lookback_days.4h',
                      'feature.hmm.lookback_days.1d',
                      'feature.hmm.min_rows_for_training');
DELETE FROM config_schema
 WHERE config_key IN ('feature.hmm.lookback_days.1m',
                      'feature.hmm.lookback_days.5m',
                      'feature.hmm.lookback_days.15m',
                      'feature.hmm.lookback_days.1h',
                      'feature.hmm.lookback_days.4h',
                      'feature.hmm.lookback_days.1d',
                      'feature.hmm.min_rows_for_training');

COMMIT;
