-- Migration 428: APR keys for the feature_vectors_v2 rebuild writer (phase 186 plan 25, D-28,
-- D-32a, todo 339).
--
-- services/backfill_feature_factory.py run_rebuild_stage splits the universe into symbol chunks
-- and writes one provenance_batch unit per (symbol chunk, tf, calendar-year range). Two tunables
-- of that design are registered here; the unit shape itself (year ranges, group order) is a
-- design choice, not a parameter.
--
-- infra.backfill.insert_batch_size (migration 275, todo 009 Part A) is retired in the same
-- migration: its only reader was the executemany batching of the old compute stage's
-- feature_vectors insert, deleted in this plan (rows now stream through bulk_load's COPY). A
-- repo-wide grep of src, services, scripts and tests found no other reader (the unrelated
-- infra.backfill.ohlcv_insert_batch_size, migration 313, is untouched). config_history first,
-- then config_state, then config_schema, per key (the 311 and 424 pattern). Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.feature_factory.rebuild_symbols_per_chunk',
    'int',
    '25',
    1, 200,
    '[initial_estimate] Symbols per (chunk, tf, time range) unit of the feature_vectors_v2 rebuild (services/backfill_feature_factory.py run_rebuild_stage). A smaller chunk loses less work to a kill and bounds one unit''s spool; a larger one amortizes the per-unit provenance and COPY overhead. Changing it renames every unit, so a resumed run recomputes. Not an ML learning target.'
),
(
    'infra.feature_factory.max_unit_rows',
    'int',
    '1000000',
    10000, NULL,
    '[conventional] Loud refusal bound on one rebuild unit''s row count (todo 339): a unit whose spooled rows exceed it raises before any write instead of exhausting disk or memory. One 25-symbol 5m year is about 0.5 million rows. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.feature_factory.rebuild_symbols_per_chunk', '25', 1),
    ('infra.feature_factory.max_unit_rows', '1000000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.feature_factory.rebuild_symbols_per_chunk', 1, '25', 'migration_428',
     'Initial value: 25 symbols per rebuild unit [initial_estimate]'),
    (NOW(), 'infra.feature_factory.max_unit_rows', 1, '1000000', 'migration_428',
     'Initial value: refuse a unit above one million rows [conventional]')
ON CONFLICT DO NOTHING;

-- Retire infra.backfill.insert_batch_size: no reader remains after plan 186-25.
DELETE FROM config_history WHERE config_key = 'infra.backfill.insert_batch_size';
DELETE FROM config_state WHERE config_key = 'infra.backfill.insert_batch_size';
DELETE FROM config_schema WHERE config_key = 'infra.backfill.insert_batch_size';

COMMIT;
