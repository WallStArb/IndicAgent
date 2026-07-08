-- Migration 209: APR key for the pooled cross-sectional fetch's server-side cursor batch size
--
-- services/ensemble_ic_engine.py's pooled worker fetch (no per-symbol filter, so row count
-- scales with symbols x bars) was switched from psycopg2 fetchall()-before-reduce to a named
-- (server-side) cursor streamed in itersize-sized batches, to bound peak memory against
-- ensemble_alpha's full scored population (2026-07-08 fix -- the same fetchall()-before-reduce
-- shape that OOM'd ic_engine.py's cross-sectional pass twice the same week, and already caused
-- a real "No space left on device" shared-memory failure on 2 of 240 symbol/tf cells during a
-- live corpus run before this fix).
--
-- itersize=50_000 was hardcoded at the call site -- an infrastructure batch-size constant
-- (CLAUDE.md APR mandate category 3: "batch sizes, queue depths, timeouts -> infra.*"), same
-- category as the existing infra.ic_engine.cs_chunk_ts and this file's own
-- infra.ensemble_ic_engine.workers. Migrated same session per "migrate-as-you-go."

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'infra.ensemble_ic_engine.pooled_fetch_itersize',
    'int',
    '50000',
    '[initial_estimate] Row batch size for the named server-side psycopg2 cursor used by '
    'the pooled cross-sectional fetch in services/ensemble_ic_engine.py (no per-symbol '
    'filter, so row count scales with symbols x bars against ensemble_alpha''s full scored '
    'population). Not yet tuned against real corpus-scale throughput -- 50000 matches the '
    'unmeasured value already in place before this key existed; revisit if the pooled '
    'fetch is ever profiled.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ensemble_ic_engine.pooled_fetch_itersize', '50000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'infra.ensemble_ic_engine.pooled_fetch_itersize', 1, '50000', 'migration_209',
    'Initial estimate: matches the unmeasured hardcoded value already in place '
    '[initial_estimate]'
);

COMMIT;
