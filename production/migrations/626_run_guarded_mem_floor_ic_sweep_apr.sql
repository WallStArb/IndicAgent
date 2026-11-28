-- 626: the MemAvailable floor of the guarded IC sweep launcher (scripts/ops/ic_sweep_launch.sh, todo 690).
--
-- The launcher runs the sweep recorder's dry runs and real blocks and the todo 670 StepM check under the host gate. Like
-- migrations 622 and 623 it reads its floor from APR instead of the 40 GiB hard-coded in guarded_run_common.sh. Seeded
-- 40, the same as the IC measure's seed, until the 25-name recorder dry run measures its peak (todo 671 checklist); the
-- lead then sets it through ConfigService with a changed_by and reason. Read only by the launcher: no unit identity,
-- corpus apr_hash (a fixed list of pinned keys) or spec hash moves. Idempotent; no table is rewritten, so no VACUUM is owed.
-- Reverse: DELETE the three rows of this key from config_history, config_state and config_schema.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.run_guarded.mem_floor_gib.ic_sweep', 'int', '40', 8, 512,
 '[initial_estimate] Smallest MemAvailable in GiB at which scripts/ops/ic_sweep_launch.sh starts a sweep recorder dry run or block, or the todo 670 StepM check. Seeded at the IC measure seed; set it from the measured 25-name recorder peak extrapolated to the full universe, never below the measured peak. Not a learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.run_guarded.mem_floor_gib.ic_sweep', '40', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_626',
       'Initial value for the IC sweep launcher memory floor [initial_estimate]'
  FROM config_state
 WHERE config_key = 'infra.run_guarded.mem_floor_gib.ic_sweep'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_626');

COMMIT;
