-- Migration 594: retire the alert.lag.bar-writer APR key with the BarWriter deletion (todo 614
-- row 7, commits aebdf0f86 and 6530b07de). The service, its unit and its _DAG_ORDER entry are gone,
-- so nothing reads its consumer-lag threshold.
--
-- Deliberate departure from the earlier retirement migrations (412 to 591), which delete the key's
-- config_history first: here the earlier history is kept and a final row (this migration as
-- changed_by, the reason, the last value) records the retirement; then config_state, then config_schema.
-- The dated fixture tests/integration/fixtures/seed_config_2026-11-05.sql keeps its snapshot row.
--
-- Rerun semantics: the history row is guarded by NOT EXISTS and the DELETEs match nothing. No
-- table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version + 1, s.config_value, 'migration_594',
       'Retired: the BarWriter service was deleted (todo 614 row 7); no reader remains'
  FROM config_state s
 WHERE s.config_key = 'alert.lag.bar-writer'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = s.config_key AND h.changed_by = 'migration_594');

DELETE FROM config_state WHERE config_key = 'alert.lag.bar-writer';
DELETE FROM config_schema WHERE config_key = 'alert.lag.bar-writer';

COMMIT;
