-- Migration 178: ensemble_trainer ProcessPoolExecutor parallelism
--
-- Add infra.ensemble_trainer.workers APR key for parallel stratum processing.
-- 29 strata × 4 TFs = 116 parallel jobs possible. Default 12 workers balances
-- parallelism with memory footprint (each worker loads feature matrix X).
--
-- After applying this migration, ensemble_trainer.py uses compute/write split:
-- workers (ProcessPoolExecutor) handle CPU-bound numpy operations (Ledoit-Wolf,
-- clustering, matmul), main process batches all DB writes via asyncpg.
--
-- Expected speedup: ~10-20x (25 min → 2-3 min).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, allowed_values, description)
VALUES
  (
    'infra.ensemble_trainer.workers',
    'int',
    '12',
    NULL,
    'Number of ProcessPoolExecutor workers for ensemble_trainer.py stratum-level parallelism. '
    'Each worker processes one (tf, regime) stratum: loads feature matrix X, computes Ledoit-Wolf '
    'shrinkage covariance, performs cluster deflation, and returns serializable weights. '
    'Default 12 = min(24_cores // 2, 16). Not an ML learning target. [initial_estimate]'
  );

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('infra.ensemble_trainer.workers', '12', 1);

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'infra.ensemble_trainer.workers', 1, '12', 'migration_181',
   'Initial: 12 workers for stratum parallelism, ~10-20x speedup over sequential processing [initial_estimate]');

COMMIT;
