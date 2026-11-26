-- 620: two more d2_landed named exceptions (lead ruling 2026-11-26; same class as 617; recent-window seam check, real moves).
--
-- Appends ADI and NTNX unexplained_seam to infra.corpus_rerun.d2_landed.held_verdicts (migration
-- 609 pattern): real moves on the 2026-11-20 to 2026-11-25 Alpaca bars, witnessed by Yahoo on open,
-- close and volume, with no recognised split ratio. The check reads a recent window and clears as
-- the bar ages out; both entries can be removed once the bars leave the check's window. Idempotent (an entry already present is not added again); no table is
-- rewritten, so no VACUUM clause is owed.

BEGIN;

WITH new_entries AS (
    SELECT value AS entry FROM jsonb_array_elements($json$[
      {"symbol": "ADI", "check": "unexplained_seam", "evidence": "Alpaca bars 2026-11-20 to 2026-11-25: close 377.44, 345.92, 378.75, 312.95, 333.105 (log steps -0.087, +0.091, -0.191, +0.062) on volume 10.2M, 8.9M, 13.1M and 9.2M vs about 3.5M shares, large moves with volume spikes and no recognised split ratio (a split would step by ln 2 or more and Yahoo lists no split in two years). Yahoo agrees on every session, for 2026-11-24 open 328.00, close 312.95 and volume 13.10M; real moves, not a scale break (cause not recorded). Disposition: recent-window seam check, real move; removable once the bars age out of the window."},
            {"symbol": "NTNX", "check": "unexplained_seam", "evidence": "Alpaca bar 2026-11-25: close 54.59 to 46.30 (log step -0.165) on volume 13.6M vs about 2M shares, a large move with a volume spike and no recognised split ratio (a split would step by ln 2 or more and Yahoo lists no split in two years). Yahoo agrees on open 45.745, close 46.30 and volume 13.60M; a real move, not a scale break (cause not recorded). Disposition: recent-window seam check, real move; removable once the bar ages out of the window."}
    ]$json$::jsonb)
)
UPDATE config_state
   SET config_value = (
           (config_value::jsonb) || COALESCE((
               SELECT jsonb_agg(n.entry) FROM new_entries n
                WHERE NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(config_state.config_value::jsonb) e
                     WHERE e->>'symbol' = n.entry->>'symbol' AND e->>'check' = n.entry->>'check')
           ), '[]'::jsonb)
       )::text,
       version = version + 1
 WHERE config_key = 'infra.corpus_rerun.d2_landed.held_verdicts'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                    WHERE h.config_key = config_state.config_key AND h.changed_by = 'migration_620');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_620',
       'Hold ADI and NTNX unexplained_seam (real 2026-11 moves, Yahoo witnessed on open, close and volume, no split in two years; corpus run 04db3930 pin gate; lead ruling 2026-11-26)'
  FROM config_state
 WHERE config_key = 'infra.corpus_rerun.d2_landed.held_verdicts'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                    WHERE h.config_key = config_state.config_key AND h.changed_by = 'migration_620');

COMMIT;
