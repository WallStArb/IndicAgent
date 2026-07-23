-- Migration 249: alpha.ic.feature_block_columns + alpha.ic.max_cell_rows APR keys
-- (162-01 Task 3, todos 139/140)
--
-- alpha.ic.feature_block_columns: number of feature columns processed per block in
-- the feature-blocked rank/IC/CI/fold rewrite (_subsample_and_rank,
-- services/ic_engine.py). Bounds peak transient memory to O(n_sub x block) instead
-- of O(n_sub x n_features) -- rankdata() always returns float64 regardless of input
-- dtype, so ranking the whole feature matrix at once was the single largest live
-- allocation for the biggest cross-sectional cells (confirmed root cause of the
-- 2026-07-18 OOM kill on the 5m/low_bull cell, ~599K rows, ~20.5GB anon-rss). A
-- peak-memory-vs-loop-overhead knob, not a statistic -- [initial_estimate], not an
-- ML learning target.
--
-- alpha.ic.max_cell_rows: crash-loud row-count ceiling. A cell whose raw row count
-- exceeds this value raises CellTooLargeError rather than silently routing to an
-- alternate (unblocked, or otherwise degraded) compute path -- "silent wrong
-- answers are worse than loud crashes" (CLAUDE.md north star). Sized ~2x today's
-- largest known cell (5m/low_bull cross-sectional, ~599K observations per the
-- 2026-07-18 incident) -- [rca_analysis], not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.feature_block_columns',
    'int',
    '32',
    4, 256,
    '[initial_estimate] Number of feature columns processed per block in the '
    'feature-blocked rank/IC/CI/fold compute (_subsample_and_rank, '
    'services/ic_engine.py, todos 139/140). Bounds peak transient memory to '
    'O(n_sub x block) instead of O(n_sub x n_features) -- a peak-memory-vs-'
    'loop-overhead knob, not a statistical concept. Not an ML learning target.'
),
(
    'alpha.ic.max_cell_rows',
    'int',
    '1200000',
    100000, 10000000,
    '[rca_analysis] Crash-loud row-count ceiling for a single IC compute cell '
    '(symbol|POOLED, tf, regime). A cell above this raises CellTooLargeError '
    'rather than silently routing to an alternate algorithm -- see the '
    '2026-07-18 OOM incident (5m/low_bull cross-sectional cell, ~599K '
    'observations, ~20.5GB anon-rss). Sized ~2x that largest known cell. Not '
    'an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.feature_block_columns', '32', 1),
    ('alpha.ic.max_cell_rows', '1200000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.feature_block_columns', 1, '32', 'migration_249',
     'Seed feature-axis chunk size for the feature-blocked rank/IC/CI/fold rewrite, '
     'todos 139/140 [initial_estimate]'),
    (NOW(), 'alpha.ic.max_cell_rows', 1, '1200000', 'migration_249',
     'Seed crash-loud row-count ceiling, ~2x the 2026-07-18 OOM incident cell size, '
     'todo 140 [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
