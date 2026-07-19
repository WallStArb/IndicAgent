-- Migration 232: infra.ic_engine.cross_sectional_bootstrap_threads APR key (todo 131)
--
-- ic_engine.py's cross-sectional pass (_compute_cross_sectional_tf) was the single
-- largest bottleneck in the corpus rebuild: one (regime_group, tf, regime_label) cell
-- at production scale (n~361674 rows, p=154 features) took ~8h53m, almost entirely
-- inside _circular_block_bootstrap_ic's 2000-iteration bootstrap loop
-- (src/intelligence/statistics/ic_math.py). Threading the loop's re-rank+IC step (RNG
-- draw stays serial for determinism, only the pure per-iteration compute is
-- parallelized) speeds this up, but code review (Angle B, removed-behavior auditor)
-- flagged that each concurrent thread holds its own re-ranked (n, p) working set --
-- unlike the old single-connection-idle-across-compute bug this same investigation
-- fixed elsewhere, this is a real per-thread memory cost, not just wall-clock -- and an
-- initial guess of 12 threads was seeded here without measuring it. Direct measurement
-- on this production host at the real cell shape (n=361674, p=154), via
-- resource.getrusage(RUSAGE_SELF).ru_maxrss on the actual function:
--
--   max_workers=1  (serial baseline): peak RSS  3.3 GB, ~3.72h for n_boot=2000
--   max_workers=4:                    peak RSS 11.5 GB, ~1.22h
--   max_workers=6:                    peak RSS 13.6 GB, ~0.99h
--   max_workers=8:                    peak RSS 15.6 GB, ~0.8h (est.)
--   max_workers=12 (original guess):  peak RSS  ~23 GB -- on a host with ~22GB free
--                                      with nothing else running, i.e. ~0 safety
--                                      margin against the other live daemons
--                                      (feature_vector_pipeline, ctx-writer,
--                                      lineage-writer, TimescaleDB, Redpanda) that
--                                      actually run concurrently with this pass.
--
-- Seeding 6, not 12: gets the worst-case cell from ~8h53m to under an hour while
-- leaving a real (~8GB) memory margin, instead of the ~0-margin config that would have
-- shipped un-measured. max_value tightened to 8 (was 24) as a schema-enforced ceiling
-- -- nothing above what's been directly measured and confirmed safe on this host can be
-- set without deliberately widening the schema bound itself.
--
-- Scope: cross-sectional pass ONLY. The per-symbol pass's two
-- _circular_block_bootstrap_ic call sites (_compute_symbol_tf) are NOT wired to this
-- key -- they already run inside an infra.ic_engine.workers-way ProcessPoolExecutor
-- pool, so adding thread-level parallelism on top would oversubscribe cores rather
-- than speed anything up. Those call sites keep the function's max_workers=1 default,
-- byte-for-byte unchanged.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ic_engine.cross_sectional_bootstrap_threads',
    'int',
    '6',
    1, 8,
    '[initial_estimate] Thread pool size for the circular block bootstrap CI''s re-rank+IC step, cross-sectional pass only (ic_engine.py''s _compute_cross_sectional_tf). Directly measured on production host at real cell scale (n~361674, p=154): 6 threads = ~0.99h for n_boot=2000 vs ~3.72h serial, peak RSS ~13.6GB (leaves ~8GB margin against the host's other live daemons). max_value=8 is a deliberate, measurement-backed ceiling, not a placeholder -- 12 threads measured ~23GB peak RSS, ~0 safety margin on this host. Not an ML learning target. Must stay 1 for the per-symbol pass (already inside a process pool -- see migration comment).'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ic_engine.cross_sectional_bootstrap_threads', '6', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ic_engine.cross_sectional_bootstrap_threads', 1, '6', 'migration_239', 'Initial value: directly measured on production host at real cell scale, ~0.99h for n_boot=2000 with ~8GB memory margin [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
