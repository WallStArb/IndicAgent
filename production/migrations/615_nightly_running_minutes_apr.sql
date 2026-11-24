-- Migration 615: threshold.bar_reconciliation.nightly_running_minutes (todo 513).
-- D7's nightly_skipped now reads the newest Alpaca nightly run from its ohlcv_request rows instead
-- of the deleted IBKR fetcher's status file. A run whose last answer is younger than this is
-- treated as still running and left unjudged, not a finding.
--
-- Rerun semantics: ON CONFLICT DO NOTHING. No table is rewritten, so no VACUUM clause is owed.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.bar_reconciliation.nightly_running_minutes', 'int', '30', 1, 720,
    '[initial_estimate] Minutes since the last answer of the Alpaca nightly run under which D7 treats '
    'the run as still answering and leaves nightly_skipped unjudged. The nightly ends about 35 '
    'minutes after it starts and D7 runs about an hour after that. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.bar_reconciliation.nightly_running_minutes', '30', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), 'threshold.bar_reconciliation.nightly_running_minutes', 1, '30', 'migration', 'todo 513'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history
    WHERE config_key = 'threshold.bar_reconciliation.nightly_running_minutes' AND version = 1
);

COMMIT;
