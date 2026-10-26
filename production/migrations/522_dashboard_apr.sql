-- Migration 522: seed the dashboard's read-route bounds (dashboard v3.5 slice 1,
-- docs/plans/2026-10-26-dashboard-v35-cockpit-design.md decisions 3 and 5).
--
-- Readers: src/api/routes/pipeline.py (stale_hours: a stage whose newest row is older than
-- this shows stale; ingest_failing_fraction: the share of coverage rows with fetch failures above
-- which ingest shows failing; refresh_seconds, served to the dashboard by /api/pipeline/config so
-- the poll interval is set here, not in the browser) and src/api/routes/system.py
-- (dlq_window_days: how far back the DLQ panel counts). 36 hours: data arrives by nightly batch,
-- so one missed night shows stale before a second one does. Not ML learning targets.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'ui.dashboard.refresh_seconds',
        'int',
        '60',
        5, NULL,
        '[initial_estimate] Seconds between dashboard polls of the read routes. Data arrives by nightly batch, so a minute is ample. Not an ML learning target.'
    ),
    (
        'ui.dashboard.stale_hours',
        'int',
        '36',
        1, NULL,
        '[initial_estimate] A pipeline stage whose newest row is older than this many hours shows stale on the dashboard: one missed nightly batch plus slack. Not an ML learning target.'
    ),
    (
        'ui.dashboard.ingest_failing_fraction',
        'float',
        '0.1',
        0, 1,
        '[initial_estimate] The ingest stage shows failing when more than this fraction of ohlcv_coverage rows report consecutive fetch failures; below it the failing count still shows beside the chip. A known backlog of a few hundred names (2026-10-26: 249 of 5,532) must not turn the home page permanently red. Not an ML learning target.'
    ),
    (
        'ui.dashboard.dlq_window_days',
        'int',
        '7',
        1, NULL,
        '[initial_estimate] Days of dlq_events the System page counts by topic and error type. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('ui.dashboard.refresh_seconds', '60', 1),
    ('ui.dashboard.stale_hours', '36', 1),
    ('ui.dashboard.ingest_failing_fraction', '0.1', 1),
    ('ui.dashboard.dlq_window_days', '7', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason) VALUES
    (now(), 'ui.dashboard.refresh_seconds', 1, '60', 'migration_522',
     'seed: dashboard poll interval (dashboard v3.5 slice 1)'),
    (now(), 'ui.dashboard.stale_hours', 1, '36', 'migration_522',
     'seed: dashboard stage staleness bound (dashboard v3.5 slice 1)'),
    (now(), 'ui.dashboard.ingest_failing_fraction', 1, '0.1', 'migration_522',
     'seed: ingest failing threshold (dashboard v3.5 slice 1)'),
    (now(), 'ui.dashboard.dlq_window_days', 1, '7', 'migration_522',
     'seed: dashboard DLQ window (dashboard v3.5 slice 1)');

-- The pipeline summary reads max(ts) from market_regimes every poll; ts is the third column of
-- the primary key, so without its own index that is a 5.4M-row index scan (1.8 s, measured
-- 2026-10-26).
CREATE INDEX IF NOT EXISTS market_regimes_ts_idx ON market_regimes (ts DESC);

COMMIT;
