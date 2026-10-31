-- Migration 548: the fetcher stall watchdog bounds (todo 538)
--
-- The 2026-10-31 wedge family: the fetcher's event loop stays alive (the systemd watchdog
-- pings continue, so WatchdogSec never fires) while the awaited future never resolves and no
-- item completes. The fix is an in-process progress watchdog (services run: the fetcher's
-- post-acquire watchdog) whose bounds are APR-seeded here. stall_abort_s cannot legally trip
-- on pacing: the rate limiter's window is 600s, so healthy fetching completes an item far
-- sooner, and stage subprocesses suspend the countdown. teardown_timeout_s bounds the
-- leaf-disconnect sequence, where the 2026-10-17 teardown hangs parked forever. The per
-- request timeout already exists (the ibkr provider plan's request_timeout_s and the 90s
-- outer wrapper in src/providers/ibkr.py) and is deliberately not duplicated. Read by
-- scripts/infrastructure/backfill/ohlcv_history_fetcher.py (_read_stall_bounds, whose code
-- defaults are these seeds). Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.ibkr.stall_tick_s',
        'int', '60', 1, 600,
        '[initial_estimate] Seconds between the fetcher stall watchdog''s progress checks (todo 538). Each tick compares the run''s forward-motion counter (phase completions and fetched items) against the last tick; stage subprocesses suspend the countdown. Not an ML learning target.'
    ),
    (
        'infra.ibkr.stall_abort_s',
        'int', '1800', 60, 7200,
        '[initial_estimate] Zero-progress seconds after which the fetcher dumps every pending task at error level and exits 1 (todo 538). 1800 s cannot trip on legal pacing (the rate limiter window is 600 s), and one wedged run costs at most 30 minutes instead of hours. Not an ML learning target.'
    ),
    (
        'infra.ibkr.teardown_timeout_s',
        'int', '30', 5, 300,
        '[initial_estimate] Budget for the fetcher''s whole leaf-disconnect sequence (todo 538); a teardown that exceeds it logs, fails the run loudly and lets the timer restart the lane, where the 2026-10-17 hangs parked forever. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.stall_tick_s', '60', 1),
    ('infra.ibkr.stall_abort_s', '1800', 1),
    ('infra.ibkr.teardown_timeout_s', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), s.config_key, s.version, s.config_value, 'migration:548',
       'seed (todo 538 stall watchdog and teardown bounds)'
  FROM config_state s
 WHERE s.config_key IN ('infra.ibkr.stall_tick_s', 'infra.ibkr.stall_abort_s',
                        'infra.ibkr.teardown_timeout_s')
   AND s.version = 1
   -- attribute only a row this migration actually seeded: if ANY history row already exists
   -- for this key and version, the seed must not claim that value as its own.
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.version = s.version
   );

COMMIT;
