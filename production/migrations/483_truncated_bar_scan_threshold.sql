-- Migration 483: threshold of the truncated-bar scan (phase 191, third review of plan 07, low item)
--
-- An IBKR request that ended inside a 5m bar stored a truncated bar (TMUS 19:05, BLK and XTL
-- 2026-10-09 14:10: volume a fraction of the other vendor's). A reselect promotes such a bar
-- wherever raw holds it. scripts/ops/bars/ops_truncated_bar_scan.py reports every vendor bar
-- whose volume ratio to the other vendor's bar at the same slot, divided by the session's median
-- ratio, falls below this share. Read-only report; never changes data.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.bar_integrity.truncated_bar_volume_ratio',
    'float', '0.2', 0, 1,
    '[rca_analysis] A vendor bar is a truncated-bar candidate when its volume ratio to the other '
    'vendor''s bar at the same slot, over the session''s median ratio, is below this share '
    '(2026-10-09 14:10 truncated IBKR bars were under a fifth of Alpaca''s volume). Read-only '
    'scan (ops_truncated_bar_scan.py). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.bar_integrity.truncated_bar_volume_ratio', '0.2', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:483',
       'seed (phase 191, third review of plan 07: truncated-bar scan)'
  FROM config_state s
 WHERE s.config_key = 'threshold.bar_integrity.truncated_bar_volume_ratio'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
          AND h.changed_by = 'migration:483'
   );

COMMIT;
