-- 595: APR seed for the bar replay provider's publish rate (replaces the BAR_REPLAY_BARS_PER_SEC
-- environment variable, which no unit or script ever set).
--
-- services/bar_replay_provider.py reads the key once in _setup. Idempotent; no table is
-- rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.bar_replay.bars_per_sec', 'float', '10', 0.001, 100000,
 '[initial_estimate] Bars per second the one-shot bar replay provider publishes to the pipeline. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.bar_replay.bars_per_sec', '10', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_595',
       'Initial value for the bar replay rate (was an environment variable)'
  FROM config_state
 WHERE config_key = 'infra.bar_replay.bars_per_sec'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_595');

COMMIT;
