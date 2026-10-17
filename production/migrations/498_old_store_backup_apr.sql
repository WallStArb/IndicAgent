-- Migration 498: seed infra.old_store_backup.disk_margin (phase 191 plan 16).
--
-- The old-store COPY backup script (scripts/ops/bars/ops_old_store_backup.py, plan 16 task 1)
-- refuses to start a dump when the backup volume's free space is below the estimated output
-- (the two tables' total relation size) times this margin. The backup it guards is the one
-- that precedes dropping ohlcv_observation and ohlcv_intraday_raw_archive (migration 499) and
-- is kept to the retention date 2026-11-12.
--
-- The key's only reader is that script; plan 17 keeps the script until the retention date and
-- plan 18 deletes it with the backup (the pending-retirement entry in
-- tests/unit/test_table_and_apr_key_readers.py carries the retire clause).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.old_store_backup.disk_margin',
        'int',
        '2',
        1, NULL,
        '[initial_estimate] Free-disk multiplier for the old-store COPY backup dump (phase 191 plan 16): a dump needs free space >= estimated output (pg_total_relation_size of ohlcv_observation plus ohlcv_intraday_raw_archive) times this margin. 2 covers the gzip output against the on-disk estimate. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.old_store_backup.disk_margin', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (now(), 'infra.old_store_backup.disk_margin', 1, '2', 'migration_498',
        'seed: free-disk margin for the old-store COPY backup (phase 191 plan 16, design step 8)');

COMMIT;
