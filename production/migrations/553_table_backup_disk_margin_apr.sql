-- Migration 553: seed the generic pre-drop backup tool's disk-margin key (todo 578).
--
-- scripts/ops/db/ops_table_backup.py is the successor of scripts/ops/bars/ops_old_store_backup.py
-- (plan 191-16), which is deleted with the Tradier backup retention on 2026-11-12 (todo 574). The
-- old key infra.old_store_backup.disk_margin (migration 498) stays until that deletion -- the old
-- script still reads it -- and retires with todo 574; the new tool reads this key with the same
-- value and default, so behavior is unchanged whether or not this row exists.

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'infra.table_backup.disk_margin',
        'int',
        '2',
        1, NULL,
        '[initial_estimate] Free-disk multiplier for the generic pre-drop COPY backup (scripts/ops/db/ops_table_backup.py, todo 578): a dump needs free space >= estimated output (pg_total_relation_size of the named tables) times this margin. Same role as infra.old_store_backup.disk_margin (migration 498), whose reader retires 2026-11-12 (todo 574). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.table_backup.disk_margin', '2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (now(), 'infra.table_backup.disk_margin', 1, '2', 'migration_553',
        'seed: free-disk margin for the generic pre-drop COPY backup (todo 578)');

COMMIT;
