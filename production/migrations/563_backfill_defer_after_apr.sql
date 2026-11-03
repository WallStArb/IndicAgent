-- Migration 563: APR infra.backfill.defer_after, the pre-2016-first order for IBKR 5m (todo 534).
--
-- IBKR answers 5m at a fixed ~13.5 ms per bar (measured 2026-11-03 over five days, flat across
-- window sizes and eras), so the history server's bar throughput is the scarce budget. On
-- 2026-11-03, 1,208 of 1,457 IBKR 5m requests asked 2016-2026, which Alpaca SIP already holds:
-- 336 series whose IBKR 5m ends 2015-12-31 sit in the queue's SLA band and fetch forward ahead of
-- the 990 series with no IBKR 5m at all, and a never-fetched series walks newest first.
--
-- With this key ohlcv_history_fetcher ends each (vendor, timeframe) plan at the horizon instead
-- of now, the update lane's overlap re-ask included; an escalation (a correction, not backfill)
-- still re-asks its whole window. A series with nothing to ask before the horizon ends the item
-- 'deferred': not asked, not written to ohlcv_coverage, not counted as intake or in a lane,
-- counted as n_deferred in the run summary. Horizons apply to the record-planner timeframes
-- (5m/15m/1h, end-exclusive) of registry vendors; anything else fails the run at start. Pausing
-- IBKR 5m freshness after 2016 is accepted while it is set (Alpaca SIP is the 5m primary there).
-- Order only: capture per source still holds. Drop the ibkr 5m entry ('{}') once pre-2016 depth
-- is complete; series that end at 2015-12-31 then plan forward in the update lane, sparser ones
-- on their weekly gap-fill session. [user_preference] lead ruling 2026-11-03 (indicagent-16).
-- Not an ML learning target. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.backfill.defer_after',
        'json', '{}', NULL, NULL,
        '[user_preference] {vendor: {timeframe: ISO instant}}. ohlcv_history_fetcher ends that series'' fetch plan at the instant instead of now (gaps and the update-lane overlap alike; an escalation re-asks its whole window), so the vendor budget goes first to history no other vendor holds; a series with nothing to ask before it is deferred (not asked, not recorded, n_deferred in the run summary). ''{}'' defers nothing; an unknown vendor, a timeframe outside 5m/15m/1h or a malformed instant fails the run. Seeded {"ibkr": {"5m": "2016-01-01T00:00:00+00:00"}} for the todo 534 pre-2016 IBKR 5m backfill; set ''{}'' when pre-2016 depth is complete. Parsed once per run by scripts/infrastructure/backfill/_history_fetch_item.parse_defer_after. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.backfill.defer_after', '{"ibkr": {"5m": "2016-01-01T00:00:00+00:00"}}', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_563',
       'seed: pre-2016-first order for the IBKR 5m backfill (todo 534, lead ruling 2026-11-03)'
  FROM config_state s
 WHERE s.config_key = 'infra.backfill.defer_after'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_563'
 );

COMMIT;
