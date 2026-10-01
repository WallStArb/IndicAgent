-- Migration 429: APR key for the rebuild writer's block size (phase 186 plan 25, todo 339).
--
-- services/backfill_feature_factory.py's rebuild path fetches a symbol's bars through a
-- server-side cursor and writes its unit spools in blocks of this many rows, so a worker's
-- in-memory row buffer is one block however long the symbol's history is (todo 339: the IPC
-- payload must not scale with history length). It also sets the cursor's itersize. One 5m bar
-- row is roughly 3 KB as a spool line, so 10,000 rows is about a 30 MB block.
--
-- Numbered 429 because 428 (this plan's first APR migration) is already committed and applied;
-- this key surfaced in the writer implementation after 428 landed. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.feature_factory.rebuild_block_rows',
    'int',
    '10000',
    1000, 1000000,
    '[initial_estimate] Rows per memory block of the feature_vectors_v2 rebuild (services/backfill_feature_factory.py): one server-cursor fetch round trip and one spool write block, bounding the worker''s in-memory row buffer (todo 339). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.feature_factory.rebuild_block_rows', '10000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.feature_factory.rebuild_block_rows', 1, '10000', 'migration_429',
     'Initial value: 10,000 rows per spool/fetch block, about 30 MB at 5m [initial_estimate]')
ON CONFLICT DO NOTHING;

COMMIT;
