-- Migration 153: APR keys for Phase 137 session/cache constants
-- Migrates hardcoded session boundaries, cache warmup, cross-asset RV window,
-- and backfill coverage gate from src/ constants to config_state.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description) VALUES
    ('feature.cache.min_bars_warmup',              'int',   '16',    'Minimum bars required before any regime computation in FeatureCache. [initial_estimate]'),
    ('feature.cross_asset.rv_window',              'int',   '20',    'Realized vol window for SPY cross-asset z-score in FeatureCache. [initial_estimate]'),
    ('feature.session.ny_start_utc_hour',          'int',   '13',    'NY RTH open hour in UTC (09:30 ET = 13:30 UTC winter). [conventional]'),
    ('feature.session.ny_start_utc_minute',        'int',   '30',    'NY RTH open minute in UTC. [conventional]'),
    ('feature.session.ny_end_utc_hour',            'int',   '20',    'NY RTH close hour in UTC (16:00 ET = 20:00 UTC winter). [conventional]'),
    ('feature.session.overlap_start_utc_hour',     'int',   '12',    'London-NY overlap start UTC hour. [conventional]'),
    ('feature.session.overlap_end_utc_hour',       'int',   '15',    'London-NY overlap end UTC hour. [conventional]'),
    ('feature.session.london_kz_start_utc_hour',   'int',   '7',     'London killzone start UTC hour; covers summer offset (07:00 UTC). [conventional]'),
    ('feature.session.london_kz_end_utc_hour',     'int',   '10',    'London killzone end UTC hour. [conventional]'),
    ('feature.session.power_hour_start_utc_hour',  'int',   '19',    'Power hour start UTC hour (15:00 ET = 19:00 UTC winter). [conventional]'),
    ('feature.session.power_hour_end_utc_hour',    'int',   '21',    'Power hour end UTC hour (16:00 ET = 21:00 UTC winter). [conventional]'),
    ('feature.session.opening_range_start_minute', 'int',   '810',   'Opening range start as minutes-since-midnight UTC (13:30 = 810). [conventional]'),
    ('feature.session.opening_range_end_minute',   'int',   '900',   'Opening range end as minutes-since-midnight UTC (15:00 = 900). [conventional]'),
    ('threshold.backfill.coverage_gate',           'float', '0.80',  'Min fraction of theoretical_max rows before backfill pair is flagged below gate. [initial_estimate]')
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.cache.min_bars_warmup',              '16',    1),
    ('feature.cross_asset.rv_window',              '20',    1),
    ('feature.session.ny_start_utc_hour',          '13',    1),
    ('feature.session.ny_start_utc_minute',        '30',    1),
    ('feature.session.ny_end_utc_hour',            '20',    1),
    ('feature.session.overlap_start_utc_hour',     '12',    1),
    ('feature.session.overlap_end_utc_hour',       '15',    1),
    ('feature.session.london_kz_start_utc_hour',   '7',     1),
    ('feature.session.london_kz_end_utc_hour',     '10',    1),
    ('feature.session.power_hour_start_utc_hour',  '19',    1),
    ('feature.session.power_hour_end_utc_hour',    '21',    1),
    ('feature.session.opening_range_start_minute', '810',   1),
    ('feature.session.opening_range_end_minute',   '900',   1),
    ('threshold.backfill.coverage_gate',           '0.80',  1)
ON CONFLICT (config_key) DO UPDATE SET
    config_value = EXCLUDED.config_value,
    version      = EXCLUDED.version,
    updated_at   = now();

COMMIT;
