-- 622: the MemAvailable floor of the guarded stage launcher (scripts/ops/corpus_stage_launch.sh).
--
-- guarded_run_common.sh hard-codes a 40 GiB MemAvailable floor in mem_gate, sized for the 16-worker
-- batteries. The stage launcher reads its own floor from this key and sets it before host_gate, so the floor
-- is an operator-visible APR value (CLAUDE.md, APR) and one launcher can run on a smaller floor than a battery.
-- Seeded 40, so behaviour does not change at landing; the lead lowers it through ConfigService with a
-- changed_by and reason. Read only by the launcher: no unit identity or apr_hash moves. Idempotent; no
-- table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.run_guarded.mem_floor_gib.stage_1d', 'int', '40', 8, 512,
 '[rca_analysis] Smallest MemAvailable in GiB at which scripts/ops/corpus_stage_launch.sh starts the corpus run''s stage_1d and feature_complete steps. The shared 40 GiB floor was sized for 16-worker batteries; the corpus pilot at 4 workers peaked at 1.90 GiB in its cgroup (run dcb7caa4, run_resource gauge), while the idle host reads 38.6 to 40.7 GiB because Postgres holds 15 GiB of non-reclaimable shared memory on 59.4 GiB. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.run_guarded.mem_floor_gib.stage_1d', '40', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_622',
       'Initial value for the stage launcher memory floor [rca_analysis]'
  FROM config_state
 WHERE config_key = 'infra.run_guarded.mem_floor_gib.stage_1d'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_622');

COMMIT;
