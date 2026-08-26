-- Migration 325: alpha.ic.broadcast_max_bars_per_day.{5m,15m,1h} APR keys
--
-- Todo 354 (temporal pseudo-replication fix, services/ic_engine.py::
-- _compute_one_symbol_broadcast_cell): a broadcast feature's value
-- (vix_z/yield_slope_z/flight_quality) is constant across every intraday bar of a
-- trading day for a given symbol. Measuring it via the ordinary per-symbol intraday
-- path treats each duplicated bar as an independent observation, inflating N by
-- ~78x at 5m, ~26x at 15m, ~6.5x at 1h. The fix collapses to one observation per
-- trading day (the first bar of each day). That alone is sufficient for every scale
-- at 5m/15m (every configured lookahead_bars there is smaller than that tf's own
-- bars-per-day), but NOT for 1h's slow/extended scales (lookahead_bars=20/60 vs.
-- ~6.5-7 bars/day) -- two day-representative observations only 1 day apart would
-- still have heavily overlapping forward-return windows for those two scales. The
-- fix derives a per-scale day_stride = max(1, ceil(lookahead_bars /
-- broadcast_max_bars_per_day[tf])) and applies it on top of the day-collapsed
-- series, exactly mirroring the existing scale_stride = max(subsample_min_stride,
-- lookahead_bars) mechanism's role, just at day granularity instead of bar
-- granularity.
--
-- [conventional]: seeded from the standard NYSE 6.5-hour (390-minute) cash session
-- divided by each tf's bar duration (390/5=78, 390/15=26, 390/60=6.5 rounded up to
-- 7 so the guard is never tighter than the true max). Cross-checked against 2 years
-- of real SPY feature_vectors data before seeding, not assumed from the convention
-- alone: max observed bars/trading-day over 654 trading days (2024-01-01 onward)
-- was 5m=78, 15m=26, 1h=7 -- an exact match. 1d is deliberately omitted: one 1d bar
-- already equals one trading day, there is no duplication for this fix to correct.
-- Not an ML learning target -- this is a derived calendar fact, not a tunable
-- statistical parameter; widen only if a future universe expansion adds an
-- exchange with a materially different session length than NYSE's.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES
(
    'alpha.ic.broadcast_max_bars_per_day.5m',
    'int',
    '78',
    1, 200,
    '[conventional] Max observed 5m bars per NYSE trading day (390-minute cash '
    'session / 5), used by _compute_one_symbol_broadcast_cell (todo 354) to derive '
    'the per-scale day_stride so a day-decimated broadcast-feature observation''s '
    'forward-return window cannot overlap a later kept observation''s window for '
    'a scale whose lookahead spans more than one trading day. Cross-checked '
    'against 2 years of real SPY feature_vectors data (exact match). Not an ML '
    'learning target.'
),
(
    'alpha.ic.broadcast_max_bars_per_day.15m',
    'int',
    '26',
    1, 100,
    '[conventional] Max observed 15m bars per NYSE trading day (390/15). See '
    '.5m sibling key''s description for full rationale -- same mechanism, same '
    'provenance, cross-checked against real SPY data (exact match). Not an ML '
    'learning target.'
),
(
    'alpha.ic.broadcast_max_bars_per_day.1h',
    'int',
    '7',
    1, 30,
    '[conventional] Max observed 1h bars per NYSE trading day (390/60=6.5, rounded '
    'up to 7 so the day_stride guard is never tighter than the true observed max). '
    'See .5m sibling key''s description for full rationale -- this is the tf where '
    'the guard actually changes behavior (slow/extended scales'' lookahead_bars '
    'exceed bars-per-day). Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.ic.broadcast_max_bars_per_day.5m', '78', 1),
    ('alpha.ic.broadcast_max_bars_per_day.15m', '26', 1),
    ('alpha.ic.broadcast_max_bars_per_day.1h', '7', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.ic.broadcast_max_bars_per_day.5m', 1, '78', 'migration_325',
     'Initial value: NYSE 6.5hr session / 5min bars, cross-checked against real SPY data. Todo 354.'),
    (NOW(), 'alpha.ic.broadcast_max_bars_per_day.15m', 1, '26', 'migration_325',
     'Initial value: NYSE 6.5hr session / 15min bars, cross-checked against real SPY data. Todo 354.'),
    (NOW(), 'alpha.ic.broadcast_max_bars_per_day.1h', 1, '7', 'migration_325',
     'Initial value: NYSE 6.5hr session / 60min bars rounded up, cross-checked against real SPY data. Todo 354.')
ON CONFLICT DO NOTHING;

COMMIT;
