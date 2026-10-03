-- 437: venue fallback stays 1d-only (phase 185 plan 20 measurement, supersedes 405's timeframes).
--
-- Migration 405 added 5m to infra.ibkr.venue_fallback.timeframes. Measured 2026-10-03 against IBKR
-- (client 49): a verify-only 5m walk retrieves and discards the venue's whole pre-move 5m history,
-- about 46 s per 150-day chunk (TMUS at NYSE 2012: 11,664 bars in 52 s; XEL at ARCA 2016: 11,550
-- bars in 46 s), and the first live re-ask's TMUS@NYSE request timed out on all retries. A name
-- that moved in 2013 costs on the order of ten minutes per venue for data nothing reads before
-- phase 186's rebuild completes (D-19), and a resumed 5m lane would pay it for every late name.
-- The timeframe list stays an APR switch: flipping it back to include 5m restores verify-only
-- recording, and ops_intraday_venue_recovery.py still gates any storing. The recovery locks seeded
-- by 405 stay. Idempotent.

BEGIN;

UPDATE config_state
   SET config_value = '["1d"]', version = version + 1, updated_at = NOW()
 WHERE config_key = 'infra.ibkr.venue_fallback.timeframes'
   AND config_value = '["1d", "5m"]';

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'infra.ibkr.venue_fallback.timeframes', version, config_value, 'migration_437',
       'Back to 1d only: verify-only 5m walks fetch and discard years of venue bars (plan 185-20 measurement)'
  FROM config_state
 WHERE config_key = 'infra.ibkr.venue_fallback.timeframes'
   AND config_value = '["1d"]'
   AND NOT EXISTS (
       SELECT 1 FROM config_history
        WHERE config_key = 'infra.ibkr.venue_fallback.timeframes' AND changed_by = 'migration_437'
   );

COMMIT;
