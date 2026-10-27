-- Migration 523: the instrument passport's cache TTL (dashboard v3.5 slice 3,
-- docs/plans/2026-10-26-dashboard-v35-cockpit-design.md).
--
-- Reader: src/api/routes/universe.py. The passport reads a name's whole bar history from the
-- tradeable view (about 2 s for a 26-year name) and that history changes about once a day, so it
-- is cached longer than the summary pages' ui.dashboard.refresh_seconds. Not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'ui.dashboard.passport_refresh_seconds',
        'int',
        '900',
        5, NULL,
        '[initial_estimate] Seconds an instrument passport (full bar history per timeframe and vendor) is cached by the API. History changes about once a day and each read scans every bar of the name, so a quarter hour keeps an open page from rescanning every poll. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('ui.dashboard.passport_refresh_seconds', '900', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (now(), 'ui.dashboard.passport_refresh_seconds', 1, '900', 'migration_523',
     'seed: instrument passport cache TTL (dashboard v3.5 slice 3)');

COMMIT;
