-- Migration 565: APR seed for the IBKR session liveness probe timeout (todo 585).
--
-- IBKRProvider.session_alive (reqCurrentTime, todo 577) decides whether a failed qualify is a
-- dead session (the run ends gateway_lost) or the name's own failure. Its 10 s timeout was a
-- literal in src/providers/ibkr.py; todo 585 suspects it of reading a busy live session as lost
-- (five runs ended at LXP on 2026-11-03). Migrated as found, so an operator can widen it without
-- a code change. [initial_estimate] the prior literal, unchanged. Not an ML learning target.
-- Loaded through HIST_RATE_LIMIT_KEYS / apply_hist_rate_limit_config. Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
    (
        'infra.ibkr.session_probe_timeout_s',
        'float', '10.0', 1.0, 120.0,
        '[initial_estimate] Seconds IBKRProvider.session_alive waits for reqCurrentTime before calling the IBKR session dead (todo 577 qualify-on-dead-socket probe; todo 585). Too short reads a busy live session as lost and ends the fetcher run gateway_lost; too long delays the fast fail on a real loss. Loaded by apply_hist_rate_limit_config (HIST_RATE_LIMIT_KEYS). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ibkr.session_probe_timeout_s', '10.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), s.config_key, 1, s.config_value, 'migration_565',
       'seed: session liveness probe timeout, the prior 10 s literal (todo 585)'
  FROM config_state s
 WHERE s.config_key = 'infra.ibkr.session_probe_timeout_s'
   AND NOT EXISTS (
       SELECT 1 FROM config_history h
        WHERE h.config_key = s.config_key AND h.changed_by = 'migration_565'
 );

COMMIT;
