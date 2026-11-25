-- 618: the per-session cross-section floor of an IC sweep cell (todo 671, ledger 2026-11-24i).
--
-- services/ic_sweep_recorder.py records every measured level 1 IC cell as counted attempts (E21).
-- A cell's series is its per-session rank IC across names (src/intelligence/measure/session_ic.py);
-- a session with fewer finite (feature, target) pairs than this key has no IC, never a thin one.
-- The key is read only by the recorder, so no ic_measure unit identity moves. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('alpha.ic_sweep.min_names_per_session', 'int', '30', 3, 100000,
 '[initial_estimate] Fewest names with a finite feature and a finite target in one session for that session to carry a rank IC in an IC sweep cell series. A cross-section under 30 gives a rank correlation too noisy to enter the StepM universe as a session. Changing it changes every sweep series, so it is part of a block''s spec hash. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic_sweep.min_names_per_session', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_618',
       'Initial value for the sweep cell session floor [initial_estimate]'
  FROM config_state
 WHERE config_key = 'alpha.ic_sweep.min_names_per_session'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_618');

COMMIT;
