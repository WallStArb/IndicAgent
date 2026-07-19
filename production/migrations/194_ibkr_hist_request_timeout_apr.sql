-- Migration 194: IBKR historical-data request outer timeout -> infra.ibkr.historical_request_timeout_sec
-- and contract-qualification outer timeout -> infra.ibkr.contract_details_timeout_sec
--
-- Adds explicit, APR-governed outer timeouts around reqHistoricalDataAsync AND
-- reqContractDetailsAsync calls in src/providers/ibkr.py. Root-caused 2026-07-05: a live
-- backfill run hung for 25+ minutes with near-zero CPU and no
-- "reqHistoricalData: Timeout for..." warning ever logged. py-spy + strace confirmed the
-- main thread was genuinely idle in epoll_wait, not blocked on a synchronous call --
-- meaning ib_insync's own internal asyncio.wait_for(future, timeout=60) on
-- reqHistoricalDataAsync never fired despite far exceeding 60s elapsed. This module
-- already documents Python 3.14 asyncio.timeout()/wait_for reliability risk (see the
-- nest_asyncio comment at the top of ibkr.py); these timeouts are defense-in-depth, not a
-- guaranteed fix for that underlying runtime issue -- the actual safety net against an
-- indefinite hang is the external bar-count watchdog added to backfill_retry_loop.sh,
-- which force-kills the process based on observed DB progress, independent of
-- in-process timers.
--
-- A follow-up Fable review (same day) found reqContractDetailsAsync (qualify_instrument,
-- resolve_instrument) has NO timeout at all in ib_insync -- not even reqHistoricalDataAsync's
-- internal default=60 -- so it was fully unbounded, same failure class, only caught by the
-- (much slower, much less specific) external watchdog. Added the same outer-timeout
-- treatment there.
--
-- All statements idempotent: ON CONFLICT DO NOTHING per key insert. Safe to re-run.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES
  ('infra.ibkr.historical_request_timeout_sec', 'float', '90',
   '[rca_analysis] Outer asyncio.wait_for() timeout wrapping each reqHistoricalDataAsync '
   'call, on top of ib_insync''s own internal timeout=60 default. Added after a live '
   '2026-07-05 backfill hang where the internal timeout never fired despite 25+ minutes '
   'elapsed (confirmed via py-spy/strace: process was idle, not blocked). Not a '
   'guaranteed fix for Python 3.14 asyncio timer reliability -- see backfill_retry_loop.sh '
   'bar-count watchdog for the real safety net. Not an ML target.'),
  ('infra.ibkr.contract_details_timeout_sec', 'float', '30',
   '[rca_analysis] Outer asyncio.wait_for() timeout wrapping each reqContractDetailsAsync '
   'call (qualify_instrument, resolve_instrument). Unlike reqHistoricalDataAsync, this '
   'ib_insync call has NO internal timeout of its own -- fully unbounded without this '
   'wrapper, same failure class as the 2026-07-05 backfill hang. Not an ML target.')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
  ('infra.ibkr.historical_request_timeout_sec', '90', 1),
  ('infra.ibkr.contract_details_timeout_sec', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
  (NOW(), 'infra.ibkr.historical_request_timeout_sec', 1, '90', 'migration_199',
   'Migrate-as-you-go: new outer-timeout constant added APR-backed from day one, per '
   '2026-07-05 backfill hang root cause [rca_analysis]'),
  (NOW(), 'infra.ibkr.contract_details_timeout_sec', 1, '30', 'migration_199',
   'Migrate-as-you-go: new outer-timeout constant added APR-backed from day one, per '
   '2026-07-05 Fable review finding F4 [rca_analysis]');

COMMIT;
