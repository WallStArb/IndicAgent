-- 625: the capacity gate of scripts/ops/spawn_worker.sh, the lead's launcher for headless worker sessions
-- (PLANNING-SYSTEM.md, "Spawning workers"; owner ruling 2026-11-27).
--
-- Two keys: the most spawned workers alive at once, and the MemAvailable margin a new worker needs on
-- top of the floor of a live guarded run (the largest infra.run_guarded.mem_floor_gib.* key while a
-- heavy job is live, nothing otherwise). Read only by scripts/ops/spawn_worker.sh, which refuses while either
-- key is missing or outside these bounds. Number 625 because 624 is held by todo 669's unpushed
-- branch. Idempotent; no table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.spawn_worker.max_workers', 'int', '2', 1, 8,
 '[initial_estimate] Most headless worker sessions scripts/ops/spawn_worker.sh keeps alive at once (records in logs/agents/workers.jsonl whose process still runs). Seeded small while the lead learns what the host and review capacity carry; raised by the lead through ConfigService with a reason. Not an ML learning target.'),
('infra.spawn_worker.mem_margin_gib', 'int', '8', 2, 64,
 '[initial_estimate] MemAvailable in GiB a new worker needs on top of the floor of a live guarded run (the largest infra.run_guarded.mem_floor_gib.* value while a heavy job is live). Covers one claude session plus a targeted pytest run. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.spawn_worker.max_workers', '2', 1),
    ('infra.spawn_worker.mem_margin_gib', '8', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_625',
       'Initial value for the spawn_worker capacity gate [initial_estimate]'
  FROM config_state
 WHERE config_key IN ('infra.spawn_worker.max_workers', 'infra.spawn_worker.mem_margin_gib')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_625');

COMMIT;
