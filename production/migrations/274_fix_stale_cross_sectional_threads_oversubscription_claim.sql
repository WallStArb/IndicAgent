-- Migration 274: correct migration 250's stale oversubscription claim
-- (todo 215, corpus compute-speed investigation)
--
-- migration 250's config_schema.description for
-- alpha.ic.cross_sectional_bootstrap_threads.5m asserted "never applies to
-- the per-symbol path, which stays serial inside its own ProcessPoolExecutor
-- pool" as settled fact. That claim (threading on top of the per-symbol
-- ProcessPoolExecutor pool "would oversubscribe cores instead of speeding
-- anything up") was asserted at filing time, never measured. Todo 215
-- (2026-07-30) live-benchmarked the structurally equivalent
-- _blocked_bootstrap_ci in an isolated single-worker test and found the
-- opposite: scipy's rankdata/argsort releases the GIL, giving a real 2-6x
-- wall-time reduction with verified byte-identical output. The per-symbol
-- path's thread count is now configurable (migration 273,
-- infra.ic_engine.per_symbol_bootstrap_threads.{tf}), seeded at 1 (serial)
-- pending a multi-worker contention benchmark -- this migration only
-- corrects the persisted, dashboard-visible (/config/parameters) description
-- text on the pre-existing key; it does not change any config_state value.
--
-- Migrations are append-only (never edit a historical migration file in
-- place) -- this UPDATE is the correction mechanism for a persisted
-- description that turned out to be a factual claim, not just documentation.

BEGIN;

UPDATE config_schema
SET description = '[initial_estimate] ThreadPoolExecutor size for the cross-sectional '
    'circular-block-bootstrap-CI re-rank+IC step at tf=5m (services/ic_engine.py, '
    'todo 133). 5m cross-sectional cells are the largest (up to ~599K rows) and '
    'benefit from threaded dispatch. Cross-sectional pass ONLY -- this key does not '
    'apply to the per-symbol path, which has its own sibling key '
    '(infra.ic_engine.per_symbol_bootstrap_threads.{tf}, migration 273). CORRECTED '
    '2026-07-30 (todo 215): this description previously claimed threading the '
    'per-symbol path "would oversubscribe cores instead of speeding anything up" as '
    'settled fact -- that was asserted, never measured, and a live isolated-'
    'single-worker benchmark of the structurally equivalent per-symbol bootstrap '
    'found the opposite (real 2-6x speedup, GIL released by scipy rankdata/argsort). '
    'Thread count changes wall time only, never output (162-01 precomputed '
    'resample-index matrix). Not an ML learning target.'
WHERE config_key = 'alpha.ic.cross_sectional_bootstrap_threads.5m';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_274',
       'Correct stale oversubscription claim in description text, todo 215 -- no value change'
FROM config_state
WHERE config_key = 'alpha.ic.cross_sectional_bootstrap_threads.5m';

COMMIT;
