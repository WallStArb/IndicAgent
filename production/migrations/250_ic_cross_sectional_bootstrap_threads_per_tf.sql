-- Migration 250: alpha.ic.cross_sectional_bootstrap_threads.{5m,15m,1h,1d} APR keys
-- (162-02 Task 1, todo 133)
--
-- Converts the cross-sectional circular-block-bootstrap-CI thread count from a single
-- scalar (infra.ic_engine.cross_sectional_bootstrap_threads, retired by this migration)
-- into 4 flat per-tf keys, mirroring alpha.ic.bootstrap_block_size.{tf} (migration 157).
--
-- alpha.ic.cross_sectional_bootstrap_threads.5m: 6, [initial_estimate]. 5m cross-sectional
-- cells are the largest (up to ~599K rows, see migration 249) and benefit measurably from
-- ThreadPoolExecutor dispatch across the resample-block re-rank+IC step.
--
-- alpha.ic.cross_sectional_bootstrap_threads.{15m,1h,1d}: 1 (serial), [conventional]. These
-- cells finish in minutes on a single thread; dispatching a 6-way thread pool only adds
-- overhead with no wall-time benefit at that cell size (todo 133's premise).
--
-- Cross-sectional pass ONLY -- the per-symbol path's _compute_one_regime_cell already runs
-- inside an n_workers-way ProcessPoolExecutor pool and hardcodes max_workers=1 for its own
-- _subsample_and_rank call; threading on top of that pool would oversubscribe cores. Nothing
-- in this migration or its config keys applies to that path.
--
-- Thread count changes wall time only, never output: 162-01's precomputed resample-index
-- matrix (starts_matrix, drawn once per scale before the feature-block loop) makes the
-- circular block bootstrap CI bit-identical regardless of how many threads process it.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.cross_sectional_bootstrap_threads.5m',
    'int',
    '6',
    1, 16,
    '[initial_estimate] ThreadPoolExecutor size for the cross-sectional circular-block-'
    'bootstrap-CI re-rank+IC step at tf=5m (services/ic_engine.py, todo 133). 5m cross-'
    'sectional cells are the largest (up to ~599K rows) and benefit from threaded dispatch. '
    'Cross-sectional pass ONLY -- never applies to the per-symbol path, which stays serial '
    'inside its own ProcessPoolExecutor pool. Thread count changes wall time only, never '
    'output (162-01 precomputed resample-index matrix). Not an ML learning target.'
),
(
    'alpha.ic.cross_sectional_bootstrap_threads.15m',
    'int',
    '1',
    1, 16,
    '[conventional] ThreadPoolExecutor size for the cross-sectional circular-block-'
    'bootstrap-CI re-rank+IC step at tf=15m. These cells finish in minutes serially; '
    'threading only adds dispatch overhead. See alpha.ic.cross_sectional_bootstrap_threads.5m '
    'for the shared methodology. Not an ML learning target.'
),
(
    'alpha.ic.cross_sectional_bootstrap_threads.1h',
    'int',
    '1',
    1, 16,
    '[conventional] ThreadPoolExecutor size for the cross-sectional circular-block-'
    'bootstrap-CI re-rank+IC step at tf=1h. These cells finish in minutes serially; '
    'threading only adds dispatch overhead. See alpha.ic.cross_sectional_bootstrap_threads.5m '
    'for the shared methodology. Not an ML learning target.'
),
(
    'alpha.ic.cross_sectional_bootstrap_threads.1d',
    'int',
    '1',
    1, 16,
    '[conventional] ThreadPoolExecutor size for the cross-sectional circular-block-'
    'bootstrap-CI re-rank+IC step at tf=1d. These cells finish in minutes serially; '
    'threading only adds dispatch overhead. See alpha.ic.cross_sectional_bootstrap_threads.5m '
    'for the shared methodology. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.cross_sectional_bootstrap_threads.5m', '6', 1),
    ('alpha.ic.cross_sectional_bootstrap_threads.15m', '1', 1),
    ('alpha.ic.cross_sectional_bootstrap_threads.1h', '1', 1),
    ('alpha.ic.cross_sectional_bootstrap_threads.1d', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.cross_sectional_bootstrap_threads.5m', 1, '6', 'migration_250',
     'Seed per-tf cross-sectional bootstrap thread count, todo 133, threaded (largest cells) '
     '[initial_estimate]'),
    (NOW(), 'alpha.ic.cross_sectional_bootstrap_threads.15m', 1, '1', 'migration_250',
     'Seed per-tf cross-sectional bootstrap thread count, todo 133, serial (finishes in '
     'minutes) [conventional]'),
    (NOW(), 'alpha.ic.cross_sectional_bootstrap_threads.1h', 1, '1', 'migration_250',
     'Seed per-tf cross-sectional bootstrap thread count, todo 133, serial (finishes in '
     'minutes) [conventional]'),
    (NOW(), 'alpha.ic.cross_sectional_bootstrap_threads.1d', 1, '1', 'migration_250',
     'Seed per-tf cross-sectional bootstrap thread count, todo 133, serial (finishes in '
     'minutes) [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
