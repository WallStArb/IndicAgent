-- 382: survivorship bound APR seeds (phase 185 plan 08, D-04, unified design
-- 12.2). Six alpha.survivorship.* keys consumed by
-- src/intelligence/bars/labels.py via SurvivorshipRule.from_apr (caller
-- loads the keys; the pure module never reads the config service).
--
-- Delisting returns and hazards are the Shumway-style literature numbers
-- behind the D0 survivorship bound reported beside every attempt's statistic
-- (never a gate, D-04). The two [ASSUMED] values are disclosed in their
-- descriptions (T-185-08-01) and every future change lands in config_history;
-- min/max bounds refuse out-of-range tampering (T-185-08-02).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'alpha.survivorship.delisting_return.nasdaq',
        'float',
        '-0.55',
        '-1', '0',
        '[conventional] Performance-delisting return for Nasdaq names, Shumway and Warther 1999 (The delisting bias in CRSP''s Nasdaq data and its implications for the size effect). Enters labels.py delisting_sensitivity and the D0 survivorship bound reported beside the statistic (D-04). Not an ML learning target.'
    ),
    (
        'alpha.survivorship.delisting_return.nyse_amex',
        'float',
        '-0.30',
        '-1', '0',
        '[ASSUMED] Performance-delisting return for NYSE/AMEX names, Shumway 1997 (The delisting bias in CRSP data); [ASSUMED] number not confirmed against the paper. Enters labels.py delisting_sensitivity and the D0 survivorship bound (D-04). Not an ML learning target.'
    ),
    (
        'alpha.survivorship.hazard.nasdaq_annual',
        'float',
        '0.056',
        '0', '1',
        '[conventional] Annual probability a Nasdaq name delists for performance reasons, from the Shumway survivorship literature. Divided by trading_days_per_year for the per-session hazard in labels.py delisting_sensitivity. Not an ML learning target.'
    ),
    (
        'alpha.survivorship.hazard.nyse_amex_annual',
        'float',
        '0.012',
        '0', '1',
        '[conventional] Annual probability a NYSE/AMEX name delists for performance reasons, from the Shumway survivorship literature. Divided by trading_days_per_year for the per-session hazard in labels.py delisting_sensitivity. Not an ML learning target.'
    ),
    (
        'alpha.survivorship.haircut.small_cap_annual',
        'float',
        '0.015',
        '0', '1',
        '[ASSUMED] Annual survivorship haircut for small-cap names, spec range 1-2 percent a year; [ASSUMED] midpoint, not a measured value. Scaled by the attempt''s small-cap share into the D0 survivorship bound (labels.py survivorship_bound, D-04). Not an ML learning target.'
    ),
    (
        'alpha.survivorship.trading_days_per_year',
        'int',
        '252',
        '200', '260',
        '[conventional] Trading sessions per year; converts the annual delisting hazards to per-session and annualizes the D0 survivorship bound (labels.py SurvivorshipRule). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('alpha.survivorship.delisting_return.nasdaq', '-0.55', 1),
    ('alpha.survivorship.delisting_return.nyse_amex', '-0.30', 1),
    ('alpha.survivorship.hazard.nasdaq_annual', '0.056', 1),
    ('alpha.survivorship.hazard.nyse_amex_annual', '0.012', 1),
    ('alpha.survivorship.haircut.small_cap_annual', '0.015', 1),
    ('alpha.survivorship.trading_days_per_year', '252', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES
    (NOW(), 'alpha.survivorship.delisting_return.nasdaq', 1, '-0.55', 'migration_382', 'Initial value [conventional] Shumway and Warther 1999'),
    (NOW(), 'alpha.survivorship.delisting_return.nyse_amex', 1, '-0.30', 'migration_382', 'Initial value [ASSUMED] Shumway 1997, number not confirmed'),
    (NOW(), 'alpha.survivorship.hazard.nasdaq_annual', 1, '0.056', 'migration_382', 'Initial value [conventional]'),
    (NOW(), 'alpha.survivorship.hazard.nyse_amex_annual', 1, '0.012', 'migration_382', 'Initial value [conventional]'),
    (NOW(), 'alpha.survivorship.haircut.small_cap_annual', 1, '0.015', 'migration_382', 'Initial value [ASSUMED] spec 1-2 percent midpoint'),
    (NOW(), 'alpha.survivorship.trading_days_per_year', 1, '252', 'migration_382', 'Initial value [conventional]')
ON CONFLICT DO NOTHING;

COMMIT;
