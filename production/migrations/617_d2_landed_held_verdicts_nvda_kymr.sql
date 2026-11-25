-- 617: two more d2_landed named exceptions (ledger 2026-11-24k).
--
-- Appends NVDA and KYMR unexplained_seam to infra.corpus_rerun.d2_landed.held_verdicts (migration
-- 609 pattern): real one-session moves on the 2026-11-23 Alpaca bar, witnessed by Yahoo on open,
-- close and volume, with no recognised split ratio. The check reads a recent window and clears as
-- the bar ages out. Idempotent (an entry already present is not added again); no table is
-- rewritten, so no VACUUM clause is owed.

BEGIN;

WITH new_entries AS (
    SELECT value AS entry FROM jsonb_array_elements($json$[
      {"symbol": "NVDA", "check": "unexplained_seam", "evidence": "Alpaca bar 2026-11-23: close 125.53 to 165.05 (log step +0.274) on volume 784M vs 335M shares, a large move with a volume spike and no recognised split ratio (a split would step by ln 2 or more). Yahoo agrees on open 167.04, close 165.05 and volume 782.6M; a real move, not a scale break. The check reads only a recent window and clears as it ages out."},
      {"symbol": "KYMR", "check": "unexplained_seam", "evidence": "Alpaca bar 2026-11-23: close 115.31 to 150.37 (log step +0.265) on volume 7.87M vs 1.28M shares, a large move with a volume spike and no recognised split ratio (a split would step by ln 2 or more). Yahoo agrees on open 138.00, close 150.37 and volume 7.87M; a real move, not a scale break. The check reads only a recent window and clears as it ages out."}
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
                    WHERE h.config_key = config_state.config_key AND h.changed_by = 'migration_617');

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_617',
       'Hold NVDA and KYMR unexplained_seam (real 2026-11-23 moves, Yahoo witnessed; ledger 2026-11-24k)'
  FROM config_state
 WHERE config_key = 'infra.corpus_rerun.d2_landed.held_verdicts'
   AND NOT EXISTS (SELECT 1 FROM config_history h
                    WHERE h.config_key = config_state.config_key AND h.changed_by = 'migration_617');

COMMIT;
