-- Migration 276: infra.ibkr.rate_limit_max_requests / rate_limit_window_sec APR keys
-- (todo 050, remaining scope)
--
-- Migrates the last unmigrated hardcoded numeric constants in src/providers/ibkr.py:
-- _IBKR_HIST_RATE_LIMIT / _IBKR_HIST_WINDOW_S, which back the module-level
-- _SlidingWindowRateLimiter singleton (_hist_rate_limiter). Unlike the constants
-- covered by migrations 197/199/227, that singleton is constructed eagerly at
-- ibkr.py import time and reads its config only once, in __init__ -- so the usual
-- "mutate the module constant in place, read fresh at each call site" overlay
-- pattern can't reach it. _SlidingWindowRateLimiter gained a reconfigure() method
-- instead; scripts/infrastructure/backfill/infrastructure_run_historical_pipeline.py's
-- new _load_ibkr_rate_limit_config() calls it at backfill startup, same call site as
-- the existing _load_ibkr_*_config() loaders. Seeded to the exact current hardcoded
-- values -- byte-for-byte behavior preserved unless an operator explicitly changes
-- these APR values.
--
-- Real, live-trading-critical component (IBKR enforces a hard 60-req/10-min ceiling;
-- exceeding it triggers Error 162). min/max bounds below keep the seeded value inside
-- IBKR's documented hard limit and a sane window range.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'infra.ibkr.rate_limit_max_requests',
    'int',
    '55',
    1, 60,
    '[conventional] Max historical-data requests _SlidingWindowRateLimiter allows within the sliding window before pre-emptively sleeping. IBKR enforces a hard ceiling of 60 requests per 10-minute window (Error 162 "query cancelled" on breach); 55 is a conservative 5-slot buffer absorbing jitter. Not an ML learning target.'
),
(
    'infra.ibkr.rate_limit_window_sec',
    'float',
    '600.0',
    60.0, 3600.0,
    '[conventional] Sliding-window duration (seconds) _SlidingWindowRateLimiter tracks request timestamps over, matching IBKR''s documented 10-minute pacing period. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('infra.ibkr.rate_limit_max_requests', '55', 1),
    ('infra.ibkr.rate_limit_window_sec', '600.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'infra.ibkr.rate_limit_max_requests', 1, '55', 'migration_276', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]'),
    (NOW(), 'infra.ibkr.rate_limit_window_sec', 1, '600.0', 'migration_276', 'Initial value: matches pre-migration hardcoded constant exactly [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
