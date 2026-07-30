-- Migration 273: infra.ic_engine.per_symbol_bootstrap_threads.{5m,15m,1h,1d}
-- (todo 215, corpus compute-speed investigation)
--
-- services/ic_engine.py's per-symbol path (_compute_one_regime_cell ->
-- _subsample_and_rank -> _blocked_bootstrap_ci) hardcoded max_workers=1 (no
-- threading) on the stated theory that threading on top of the n_workers-way
-- ProcessPoolExecutor pool it already runs inside would oversubscribe cores
-- rather than speed anything up. That theory was asserted, never measured --
-- see migration 274 for the correction to migration 250's persisted
-- description, which made the same unqualified claim.
--
-- Live py-spy profiling of the running corpus pipeline's ic_engine step
-- (2026-07-30) found _blocked_bootstrap_ci's bootstrap-resample loop as the
-- dominant cost, and a follow-up isolated-single-worker benchmark found
-- scipy's rankdata/argsort releases the GIL: threading the SAME call with
-- 2/4/8 threads gave a real ~2.4x/4x/5.9x wall-time reduction with verified
-- byte-identical output.
--
-- 4 flat per-tf keys, mirroring alpha.ic.cross_sectional_bootstrap_threads.{tf}
-- (migration 250) exactly, seeded at 1 (serial) for every tf -- NOT the
-- benchmarked value: the isolated-worker test doesn't establish whether a
-- given thread count nets positive once ALL infra.ic_engine.workers processes
-- are threading simultaneously and genuinely contending for the same cores --
-- that requires its own multi-worker contention benchmark, deliberately not
-- run live while a corpus pipeline pass was in flight (see STATE.md). This
-- key exists so that benchmark's answer can be deployed via config alone once
-- it exists, no code change required.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ic_engine.per_symbol_bootstrap_threads.5m',
    'int',
    '1',
    1, 16,
    '[rca_analysis] ThreadPoolExecutor size for the per-symbol path''s bootstrap '
    'CI resampling at tf=5m (_blocked_bootstrap_ci via _subsample_and_rank, '
    'services/ic_engine.py, todo 215). Seeded at 1 (serial, byte-identical to '
    'the pre-215 hardcoded behavior) pending a multi-worker contention '
    'benchmark -- an isolated single-worker test found scipy rankdata/argsort '
    'releases the GIL and threading gives a real 2-6x wall-time reduction with '
    'verified byte-identical output, but that does not establish the right '
    'value once all infra.ic_engine.workers processes thread simultaneously. '
    'Not an ML learning target. Pure infrastructure throughput knob -- output '
    'is guaranteed invariant to this value, verified by '
    'test_subsample_and_rank_threaded_matches_serial.'
),
(
    'infra.ic_engine.per_symbol_bootstrap_threads.15m',
    'int',
    '1',
    1, 16,
    '[rca_analysis] Same as infra.ic_engine.per_symbol_bootstrap_threads.5m, tf=15m. '
    'Not an ML learning target.'
),
(
    'infra.ic_engine.per_symbol_bootstrap_threads.1h',
    'int',
    '1',
    1, 16,
    '[rca_analysis] Same as infra.ic_engine.per_symbol_bootstrap_threads.5m, tf=1h. '
    'Not an ML learning target.'
),
(
    'infra.ic_engine.per_symbol_bootstrap_threads.1d',
    'int',
    '1',
    1, 16,
    '[rca_analysis] Same as infra.ic_engine.per_symbol_bootstrap_threads.5m, tf=1d. '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ic_engine.per_symbol_bootstrap_threads.5m', '1', 1),
    ('infra.ic_engine.per_symbol_bootstrap_threads.15m', '1', 1),
    ('infra.ic_engine.per_symbol_bootstrap_threads.1h', '1', 1),
    ('infra.ic_engine.per_symbol_bootstrap_threads.1d', '1', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ic_engine.per_symbol_bootstrap_threads.5m', 1, '1', 'migration_273',
     'Seed per-symbol bootstrap CI thread count at the safe serial default, '
     'pending a multi-worker contention benchmark, todo 215 [rca_analysis]'),
    (NOW(), 'infra.ic_engine.per_symbol_bootstrap_threads.15m', 1, '1', 'migration_273',
     'Same as .5m, todo 215 [rca_analysis]'),
    (NOW(), 'infra.ic_engine.per_symbol_bootstrap_threads.1h', 1, '1', 'migration_273',
     'Same as .5m, todo 215 [rca_analysis]'),
    (NOW(), 'infra.ic_engine.per_symbol_bootstrap_threads.1d', 1, '1', 'migration_273',
     'Same as .5m, todo 215 [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
