-- Migration 556: APR seed for the fetcher's intake-stall exit (todo 538 follow-up).
--
-- The 538 watchdog (migration 548) counts forward motion, and a failed item or a stall check is
-- forward motion, so on 2026-11-02 a run whose every deep 5m request timed out (answers took
-- 11-35 s at 2 days and never at 30 days against a 90 s outer timeout, while the one-bar SPY 1d
-- probe answered in 0.1 s) read as alive for 3.5 hours and the timer never got a turn. The
-- invariant: a run that takes in no data ends, whatever the cause. Intake is rows a persisted
-- chunk wrote to ohlcv_raw, or an item that ended ok or no_data. After this many seconds without
-- intake while the item loop runs, the workers are cancelled, captured rows are flushed and the
-- run ends with status stalled; the timer relaunches it. Read by
-- scripts/infrastructure/backfill/ohlcv_history_fetcher.py at start. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.backfill.intake_stall_exit_s',
        'float', '1800', 900, 21600,
        '[initial_estimate] Seconds without data intake (rows written to ohlcv_raw, or an item ending ok or no_data) after which the IBKR history fetcher ends the run as stalled instead of waiting on timeouts (todo 538 follow-up). 1800 s matches infra.ibkr.stall_abort_s; the floor of 900 s keeps it above one rate-limiter window (600 s), whose pacing waits take in no data; one slow-farm run then costs 30 minutes instead of hours. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.backfill.intake_stall_exit_s', '1800', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'infra.backfill.intake_stall_exit_s', 1, '1800', 'migration_556',
       'seed: fetcher intake-stall exit (todo 538 follow-up)'
 WHERE NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = 'infra.backfill.intake_stall_exit_s' AND h.changed_by = 'migration_556'
 );

UPDATE config_schema SET min_value = 900 WHERE config_key = 'infra.backfill.intake_stall_exit_s' AND min_value <> 900;

COMMIT;
