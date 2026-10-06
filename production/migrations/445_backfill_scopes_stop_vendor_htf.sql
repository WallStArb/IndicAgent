-- 445: stop fetching vendor 15m and 1h bars (phase 189 plan 07, task 0).
--
-- Data layer integrity design (docs/plans/2026-10-06-data-layer-integrity-design.md, owner-approved
-- 2026-10-06), section 9 step 1: 15m, 1h and 4h are derived from 5m only, so the IBKR history
-- fetcher stops queueing vendor 15m and 1h. The vendor archive stays frozen as the parity reference.
--
-- infra.backfill.default_scopes
--   previous: {"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}
--   new:      {"compute_1d": ["1d", "5m"]}
-- infra.backfill.priority_tf_order
--   previous: ["15m", "1h"]
--   new:      ["5m"]
--
-- The fetcher timer stays disabled until plan 189-10 starts the 5m fetch; this migration only
-- changes what a run would queue.
--
-- Rollback (restores the previous values, then record a config_history row the same way):
--   UPDATE config_state SET config_value = '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}',
--          version = version + 1, updated_at = NOW() WHERE config_key = 'infra.backfill.default_scopes';
--   UPDATE config_state SET config_value = '["15m", "1h"]',
--          version = version + 1, updated_at = NOW() WHERE config_key = 'infra.backfill.priority_tf_order';

BEGIN;

UPDATE config_state
   SET config_value = '{"compute_1d": ["1d", "5m"]}', version = version + 1, updated_at = NOW()
 WHERE config_key = 'infra.backfill.default_scopes'
   AND config_value <> '{"compute_1d": ["1d", "5m"]}';

UPDATE config_state
   SET config_value = '["5m"]', version = version + 1, updated_at = NOW()
 WHERE config_key = 'infra.backfill.priority_tf_order'
   AND config_value <> '["5m"]';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration 445',
       'Data layer integrity design section 9 step 1: vendor 15m and 1h stop being fetched; 15m/1h derive from 5m [user_preference]'
  FROM config_state s
 WHERE s.config_key IN ('infra.backfill.default_scopes', 'infra.backfill.priority_tf_order')
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration 445'
   );

COMMIT;
