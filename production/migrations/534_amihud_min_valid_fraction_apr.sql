-- Migration 534: APR seed for the amihud_illiq_z minimum valid fraction (todo 555,
-- src/intelligence/features/kernels/volume.py).
--
-- feature.amihud.min_valid_fraction: the share of the z-score window (feature.amihud.zscore_window,
-- 252 bars) that must hold a valid ln(illiq) observation before the z-score is emitted; below
-- it the row is NaN. An observation is missing for a NULL-volume bar (the tradeable view NULLs
-- volume for the ibkr venue and fallback kinds), a zero return, or a non-positive close.
-- 0.8 = [conventional] a standard completeness bar for a rolling statistic: at 252 bars it
-- tolerates 50 missing bars (about ten weeks of sessions) and still estimates the window mean and
-- std from at least 202 observations (standard error about 7% and 5%), so one missing session
-- does not blank a year of rows while a window that is mostly empty still does. The window also restarts
-- at a volume-basis change, so the count is per basis segment.
-- Changing the value changes stored amihud_illiq_z and illiquidity_momentum_product (a rebuild
-- of those columns). Idempotent.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'feature.amihud.min_valid_fraction',
        'float',
        '0.8',
        0.1, 1.0,
        '[conventional] amihud_illiq_z: minimum share of the zscore_window that must hold a valid ln(illiq) observation (a NULL-volume bar, a zero return or a non-positive close is missing); below it the row is NaN. 0.8 tolerates 50 missing bars of 252 and leaves at least 202 observations for the window moments. The window restarts at a volume-basis change. A rebuild of amihud_illiq_z and illiquidity_momentum_product follows a change. Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.amihud.min_valid_fraction', '0.8', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), 'feature.amihud.min_valid_fraction', 1, '0.8', 'migration_534',
       'seed: amihud_illiq_z minimum valid fraction (todo 555)'
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = 'feature.amihud.min_valid_fraction'
);

COMMIT;
