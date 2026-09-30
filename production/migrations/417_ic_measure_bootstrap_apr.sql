-- Migration 417: APR keys for the IC writer's bootstrap kernel (phase 186 plan 14, pass 2, todo 469)
--
-- services/ic_measure.py bootstraps each cell's confidence interval with the counting-rank numba
-- kernel (src/intelligence/statistics/ic_bootstrap_jit.py). Two infrastructure performance
-- constants (APR category 3), both operational: neither enters a stored value or a unit identity
-- (every resample is independent and the block-start draws are one stream whatever the slicing,
-- asserted by tests/unit/measure/test_bootstrap_kernel.py). Seeds use ON CONFLICT DO NOTHING.
--
-- Threads: 12 of the host's 24 cores, measured on a 50,000 x 32 cell with 2000 resamples (see
-- todo 469): 1 thread 5.9 s, 2 threads 3.1 s, 6 threads 1.8 s, 12 threads 1.0 s.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    ('infra.ic_measure.bootstrap_threads', 'int', '12', '1', NULL,
     '[initial_estimate] Numba threads of the IC writer''s block bootstrap kernel (one cell at a time). Throughput only: each resample row is independent, so the count never changes a value and never enters a unit identity. Not an ML learning target.'),
    ('infra.ic_measure.bootstrap_chunk_resamples', 'int', '250', '1', NULL,
     '[initial_estimate] Bootstrap resamples drawn and run per slice in the IC writer; bounds the block-start matrix (resamples x blocks int64) to one slice, about 100 MB at 500,000 rows. Never changes a value (batched draws equal sequential draws) and never enters a unit identity. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('infra.ic_measure.bootstrap_threads', '12', 1),
    ('infra.ic_measure.bootstrap_chunk_resamples', '250', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (NOW(), 'infra.ic_measure.bootstrap_threads', 1, '12', 'migration_417', 'Initial value [initial_estimate]'),
    (NOW(), 'infra.ic_measure.bootstrap_chunk_resamples', 1, '250', 'migration_417', 'Initial value [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
