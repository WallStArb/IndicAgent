-- Migration 203: APR key for ic_engine's per-symbol feature-vector fetch batch size
--
-- services/ic_engine.py's per-symbol worker fetch (_compute_symbol_tf, inside the
-- ProcessPoolExecutor pass) was switched from a plain psycopg2 cursor -- which pulls the
-- ENTIRE result across the wire into a client-side buffer at execute() time regardless of
-- how the Python side iterates it -- to a named (server-side) cursor streamed in
-- itersize-sized batches. Root cause of the 2026-07-09 corpus rebuild OOM (cgroup
-- oom_kill, "A process in the process pool was terminated abruptly"): QQQ/5m alone
-- (392K rows x 150 features, post-Phase-142.5 schema growth) measured at 4.3 GB peak RSS
-- materialising the full row set as Python lists before converting to numpy; with
-- infra.ic_engine.workers=12 running their 5m pass concurrently that is 50+ GB against a
-- 29 GB box. Chunked server-side fetch measured at ~700 MB peak for the same symbol --
-- same fix shape as infra.ic_engine.cs_chunk_ts (migration 183, the cross-sectional pass)
-- and infra.ensemble_ic_engine.pooled_fetch_itersize (migration 209), both of which fixed
-- the identical fetchall()-before-reduce pattern in sibling code paths but did not cover
-- this one.
--
-- [initial_estimate] [infra.ic_engine] -- tunable but not an ML learning target.
BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'infra.ic_engine.symbol_fetch_chunk_rows',
    'int',
    '5000',
    'Row batch size for the named server-side psycopg2 cursor used by the per-symbol '
    'feature-vector fetch in services/ic_engine.py (_compute_symbol_tf). Bounds peak '
    'memory per ProcessPoolExecutor worker against the largest single symbol/tf cell '
    '(currently ~392K rows at 5m). [initial_estimate] Not yet tuned against real '
    'corpus-scale throughput -- 5000 matches the existing infra.ic_engine.cs_chunk_ts '
    'default for the sibling cross-sectional pass. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ic_engine.symbol_fetch_chunk_rows', '5000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'infra.ic_engine.symbol_fetch_chunk_rows', 1, '5000', 'migration_212',
    'Initial estimate: matches the sibling infra.ic_engine.cs_chunk_ts default '
    '[initial_estimate]'
);

COMMIT;
