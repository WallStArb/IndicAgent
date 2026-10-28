-- Migration 526: the two spread-estimator kernels (todo 553, src/intelligence/features/kernels/liquidity.py).
--
-- 1. APR seeds for their windows (read through FeatureFactoryConfig by
--    services/backfill_feature_factory.py and services/feature_vector_pipeline.py):
--    feature.high_low_spread.window: Corwin-Schultz (2012) two-bar spread estimates averaged over
--      this many pairs. 21 = the paper's monthly average of daily estimates. Declared memory equals it.
--    feature.roll_spread.window: Roll (1984) serial-covariance window in return pairs. 252 = one
--      trading year of daily returns, the per-year estimation period of Roll's paper; the estimator
--      is noisy and needs a long window. Declared memory is window + 1.
--    Changing either value changes stored feature_vectors_v2 values (a rebuild of those columns).
--
-- 2. Two nullable real columns on feature_vectors_v2 (registry outputs high_low_spread and
--    roll_spread). The table holds 0 rows when this is applied (the 186-26 rebuild has not
--    launched), so this is a catalog change only. ADD COLUMN puts them after migration 425's
--    columns; the rebuild writer COPYs with an explicit column list, so physical order does not
--    matter. No decompress or recompress and no VACUUM: no chunk holds data.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'feature.high_low_spread.window',
        'int',
        '21',
        1, 500,
        '[conventional] Corwin-Schultz high_low_spread: two-bar spread estimates (negatives set to 0) averaged over this many pairs; 21 = the paper''s monthly average of daily estimates. Declared memory = window. Not an ML learning target.'
    ),
    (
        'feature.roll_spread.window',
        'int',
        '252',
        2, 1000,
        '[conventional] Roll implied spread roll_spread: serial covariance of log close changes over this many return pairs; 252 = one trading year, Roll (1984) estimated per year. NaN when the covariance is >= 0. Declared memory = window + 1. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.high_low_spread.window', '21', 1),
    ('feature.roll_spread.window', '252', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), k, 1, v, 'migration_526', r
FROM (VALUES
    ('feature.high_low_spread.window', '21', 'seed: Corwin-Schultz spread window (todo 553)'),
    ('feature.roll_spread.window', '252', 'seed: Roll spread window (todo 553)')
) AS s(k, v, r)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h WHERE h.config_key = s.k AND h.changed_by = 'migration_526'
);

ALTER TABLE feature_vectors_v2
    ADD COLUMN high_low_spread real,
    ADD COLUMN roll_spread real;

COMMIT;
