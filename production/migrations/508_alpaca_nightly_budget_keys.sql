-- 508: the alpaca nightly capture leaf's budget keys (todo 521 T4 reopen, owner 2026-10-26:
-- "it should be part of the nightly work"). scripts/ops/bars/ops_bar_nightly.py hardcoded its
-- FetchBudget at 500 requests / 30 minutes, which cannot cover the full active universe in one
-- run (1,529 names x 2 timeframes is about 3,058 minimal requests); a rerun re-asks the same
-- first names because the nightly does no coverage check. APR keys per the migrate-as-you-go
-- rule. Provenance [initial_estimate]; not ML learning targets. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.alpaca.nightly_max_requests', 'integer', '4000', 1, 100000,
 '[initial_estimate] Per-run request ceiling for the alpaca nightly capture leaf (scripts/ops/bars/ops_bar_nightly.py). Sized to the full active universe: 1,529 names x 2 timeframes plus paging headroom. Not an ML learning target.'),
('infra.alpaca.nightly_deadline_minutes', 'integer', '60', 5, 360,
 '[initial_estimate] Wall-clock deadline in minutes for one alpaca nightly capture run. At the seeded rate limit (190 req/min) a full-universe pass needs about 16 minutes plus write time. Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.alpaca.nightly_max_requests', '4000', 1),
    ('infra.alpaca.nightly_deadline_minutes', '60', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, 1, config_value, 'migration_508',
       'todo 521 T4 reopen: full-universe nightly in one run'
  FROM config_state
 WHERE config_key IN ('infra.alpaca.nightly_max_requests', 'infra.alpaca.nightly_deadline_minutes')
   AND NOT EXISTS (SELECT 1 FROM config_history h
                   WHERE h.config_key = config_state.config_key
                     AND h.changed_by = 'migration_508');

COMMIT;
