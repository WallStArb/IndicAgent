-- 623: the MemAvailable floor of the guarded first-IC-measure launcher (scripts/ops/ic_measure_launch.sh).
--
-- guarded_run_common.sh hard-codes a 40 GiB MemAvailable floor in mem_gate, sized for the 16-worker batteries, and
-- the host rests at 38.6 to 40.7 GiB, so the IC measure would refuse most launches on a floor its own memory does
-- not need (block 9.2 GB, targets 2.3 GB, long form about 3 GB at width 16: todo 471). The launcher reads its floor
-- from this key and sets it before host_gate, the pattern of migration 622 for the stage. Seeded 40, so behaviour
-- does not change at landing; the lead sets the value through ConfigService with a changed_by and reason from the
-- measured stage_1d and IC peaks. Read only by the launcher: no unit identity or apr_hash moves. Idempotent; no
-- table is rewritten, so no VACUUM clause is owed.
-- Reverse: DELETE the three rows of this key from config_history, config_state and config_schema.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.run_guarded.mem_floor_gib.ic_measure', 'int', '40', 8, 512,
 '[rca_analysis] Smallest MemAvailable in GiB at which scripts/ops/ic_measure_launch.sh starts the corpus run''s ic_measure step. The shared 40 GiB floor was sized for 16-worker batteries; the IC measure at width 16 needs about 15 GiB plus the interpreter (todo 471). Set it from the measured stage_1d and IC peaks, never below the measured peak. Not a learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.run_guarded.mem_floor_gib.ic_measure', '40', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_623',
       'Initial value for the IC measure launcher memory floor [rca_analysis]'
  FROM config_state
 WHERE config_key = 'infra.run_guarded.mem_floor_gib.ic_measure'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_623');

COMMIT;
