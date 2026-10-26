-- 513: the alpaca nightly asks SIP again, with its window end held back from now.
-- Measured live 2026-10-26 14:21Z: feed=sip with end = now answers 403 "subscription does not
-- permit querying recent SIP data"; the same request with end = now - 20 minutes answers 200
-- (SPY 5m, 73 bars to 14:00Z). The 403 is about the window end, not the data: a nightly that
-- ends its window before the recent-SIP horizon keeps the admitted sip_rth basis (521), so the
-- iex switch of migration 511 is reverted here (iex_rth stays a kind raw can carry, never
-- selected; src/intelligence/bars/selection.py).
-- Provenance [rca_analysis]; not an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
('infra.alpaca.sip_recent_lag_minutes', 'int', '20', 16, 1440,
 '[rca_analysis] Minutes the alpaca nightly holds its SIP window end back from now. Free-plan Alpaca 403s a feed=sip window ending within about 15 minutes of now (measured 2026-10-26: end=now 403, end=now-20min 200). Not an ML learning target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.alpaca.sip_recent_lag_minutes', '20', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.alpaca.sip_recent_lag_minutes', 1, '20', 'migration_513',
       'Initial value: the recent-SIP horizon measured at about 15 minutes, plus margin'
 WHERE NOT EXISTS (SELECT 1 FROM config_history
                    WHERE config_key = 'infra.alpaca.sip_recent_lag_minutes'
                      AND changed_by = 'migration_513');

UPDATE config_state SET config_value = 'sip', version = version + 1
 WHERE config_key = 'infra.alpaca.data_feed' AND config_value <> 'sip';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), config_key, version, config_value, 'migration_513',
       'Back to sip: the 403 binds the window end, not the feed; the nightly ends its window '
       'infra.alpaca.sip_recent_lag_minutes before now and keeps the admitted sip_rth basis'
  FROM config_state
 WHERE config_key = 'infra.alpaca.data_feed'
   AND NOT EXISTS (SELECT 1 FROM config_history
                    WHERE config_key = 'infra.alpaca.data_feed'
                      AND changed_by = 'migration_513');

COMMIT;
