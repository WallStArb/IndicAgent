-- Migration 375: per-timeframe IBKR historical rate limits
--
-- infra.ibkr.rate_limit_max_requests (58 per 10 minutes, migration 302) paces every historical
-- request. IBKR's documented hard pacing rules bind bars of 30 seconds or less; for bars of a
-- minute or more the hard limit was lifted and only a soft, load-balancing slowdown applies (TWS
-- API "Historical Data Limitations", checked 2026-09-26). The 2026-09-26 1d backfill of 546 names
-- ran at about 2.5 names a minute, paced by that shared limit.
--
-- This key maps a timeframe to its own limit and sliding window (src/providers/ibkr.py
-- _IBKR_HIST_RATE_LIMIT_BY_TF, overlaid by the backfill's _load_ibkr_rate_limit_config). It is
-- seeded empty, which keeps every timeframe on the shared limit: a value is set only from a
-- measurement (scripts/infrastructure/backfill/infrastructure_ibkr_chunk_and_rate_limit_probe.py
-- --rate-ceilings), recorded in config_history like any operator change.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'infra.ibkr.rate_limit_max_requests_by_tf',
    'json',
    '{}',
    NULL, NULL,
    '[rca_analysis] Per-timeframe historical-request limits per infra.ibkr.rate_limit_window_sec, each with its own window, e.g. {"1d": 150}. Unlisted timeframes use infra.ibkr.rate_limit_max_requests. Set only from the rate-limit probe (--rate-ceilings), with a margin below the highest clean ceiling. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('infra.ibkr.rate_limit_max_requests_by_tf', '{}', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (NOW(), 'infra.ibkr.rate_limit_max_requests_by_tf', 1, '{}', 'migration_375', 'Initial value: empty, every timeframe on the shared limit until measured [rca_analysis]')
ON CONFLICT DO NOTHING;

COMMIT;
