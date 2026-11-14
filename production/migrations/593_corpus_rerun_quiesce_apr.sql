-- 593: APR seeds for `corpus_rerun --quiesce` (todo 614 row 15).
--
-- services/corpus_rerun_apr.py load_quiesce_apr reads both keys: how long the command waits for
-- the blocking timers' running services to finish, and how often it looks. They are read by the
-- operator command only and are not part of the pinned run snapshot (APR_KEYS).
-- Idempotent; no table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.corpus_rerun.quiesce.wait_seconds', 'float', '3600', 1, 86400,
 '[user_preference] Seconds `corpus_rerun --quiesce` waits for a blocking timer''s service to reach inactive or failed after disabling it, before it stops with the record kept. Not an ML learning target.'),
('infra.corpus_rerun.quiesce.poll_seconds', 'float', '5', 0.1, 600,
 '[conventional] Seconds between looks at the services during `corpus_rerun --quiesce`. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.corpus_rerun.quiesce.wait_seconds', '3600', 1),
    ('infra.corpus_rerun.quiesce.poll_seconds', '5', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_593',
       'Initial value for corpus_rerun --quiesce (todo 614 row 15)'
  FROM config_state
 WHERE config_key LIKE 'infra.corpus_rerun.quiesce.%'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_593');

COMMIT;
