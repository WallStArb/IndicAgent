-- Migration 559: the item-8 add-list (todo 584 D2, 558's spec): ten feature_vectors_v2 columns and
-- the nine window seeds their kernels read.
--
-- Columns (registry outputs of kernels/residual.py, distribution.py, dividend.py; V2_ONLY_COLUMNS):
--   market_residual_return, idiosyncratic_volatility, market_residual_z, market_residual_lag1_acf,
--   residual_beta_stability (the Avellaneda-Lee 2010 ingredient set against SPY), max_daily_return,
--   max_drawdown, downside_deviation, size_proxy, dividend_yield. days_to_ex_dividend stays out:
--   dividend_events carries no declaration time, so it cannot be computed at t without reading
--   the future. Nullable real columns, a catalog change; ADD COLUMN puts them after the existing
--   columns and the rebuild writer COPYs with an explicit column list. No chunk is compressed and
--   no type changes, so no VACUUM clause is owed.
-- Window seeds: provenance and ranges in each description. Idempotent (ON CONFLICT DO NOTHING,
-- IF NOT EXISTS, guarded history insert).

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
    (
        'feature.market_residual.z_window',
        'int', '252', 2, 2000,
        '[conventional] one trading year: Trailing window, in the name''s own daily bars, of the time-series z behind market_residual_z (Avellaneda-Lee 2010 ingredient). Cross-sectional standardization never happens in storage. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.idiosyncratic_volatility.window',
        'int', '21', 2, 500,
        '[conventional] monthly, Ang et al. 2006: Sample std (unannualized) window of the market residual behind idiosyncratic_volatility. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.market_residual.lag1_acf_window',
        'int', '63', 3, 1000,
        '[initial_estimate] one quarter: Window of the lag-1 autocorrelation of the market residual behind market_residual_lag1_acf; a no-spread window is NaN. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.residual_beta_stability.window',
        'int', '60', 2, 1000,
        '[initial_estimate]: Window of the sample std of the rolling equity beta behind residual_beta_stability (the dispersion estimator pinned by the review). Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.max_daily_return.window',
        'int', '21', 2, 500,
        '[conventional] monthly, Bali et al. MAX: Window of the largest daily log return behind max_daily_return. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.max_drawdown.window',
        'int', '252', 2, 2000,
        '[conventional] one trading year: Window of the close-based maximum drawdown behind max_drawdown, stored in [0, 1]. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.downside_deviation.window',
        'int', '252', 2, 2000,
        '[conventional] one trading year: Window of the downside deviation (target 0) behind downside_deviation. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.size_proxy.window',
        'int', '63', 2, 2000,
        '[initial_estimate] one quarter: Window, in own-timeframe bars, of the mean ln(close * volume) behind size_proxy; runs per volume-basis segment. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    ),
    (
        'feature.dividend_yield.window',
        'int', '252', 2, 2000,
        '[conventional] trailing twelve months: Window of trailing dividend amounts over the close behind dividend_yield; NaN while the window holds a date outside dividend_event_coverage. Changing it changes stored feature_vectors_v2 values (a rebuild of the column). Not an ML learning target.'
    )
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
    ('feature.market_residual.z_window', '252', 1),
    ('feature.idiosyncratic_volatility.window', '21', 1),
    ('feature.market_residual.lag1_acf_window', '63', 1),
    ('feature.residual_beta_stability.window', '60', 1),
    ('feature.max_daily_return.window', '21', 1),
    ('feature.max_drawdown.window', '252', 1),
    ('feature.downside_deviation.window', '252', 1),
    ('feature.size_proxy.window', '63', 1),
    ('feature.dividend_yield.window', '252', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT now(), k, 1, v, 'migration_559', r
FROM (VALUES
    ('feature.market_residual.z_window', '252', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.idiosyncratic_volatility.window', '21', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.market_residual.lag1_acf_window', '63', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.residual_beta_stability.window', '60', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.max_daily_return.window', '21', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.max_drawdown.window', '252', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.downside_deviation.window', '252', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.size_proxy.window', '63', 'seed: item-8 add-list window (todo 584 D2)'),
    ('feature.dividend_yield.window', '252', 'seed: item-8 add-list window (todo 584 D2)')
) AS s(k, v, r)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h WHERE h.config_key = s.k AND h.changed_by = 'migration_559'
);

-- Conditional: the integration baseline replay has no feature_vectors_v2 (see migration 526).
DO $$
BEGIN
    IF to_regclass('feature_vectors_v2') IS NOT NULL THEN
        ALTER TABLE feature_vectors_v2
            ADD COLUMN IF NOT EXISTS market_residual_return real,
            ADD COLUMN IF NOT EXISTS idiosyncratic_volatility real,
            ADD COLUMN IF NOT EXISTS market_residual_z real,
            ADD COLUMN IF NOT EXISTS market_residual_lag1_acf real,
            ADD COLUMN IF NOT EXISTS residual_beta_stability real,
            ADD COLUMN IF NOT EXISTS max_daily_return real,
            ADD COLUMN IF NOT EXISTS max_drawdown real,
            ADD COLUMN IF NOT EXISTS downside_deviation real,
            ADD COLUMN IF NOT EXISTS size_proxy real,
            ADD COLUMN IF NOT EXISTS dividend_yield real;
    END IF;
END $$;

-- Registry rows: the ten columns enter concept_registry as candidates (feature domain rows are
-- seeded by migration, as in 289; scripts/research/register_idea.py takes the idea domains only).
-- Promotion happens only through ConceptRegistryService when a family prereg names the column.
INSERT INTO concept_registry (domain, name, description, status, enabled, added_phase, metadata)
SELECT 'feature', v.name, v.description, 'candidate', false, '584-item8',
       jsonb_build_object('module', v.module, 'apr_namespace', 'feature.', 'todo', '584 D2')
FROM (VALUES
    ('market_residual_return', 'r_sym - beta*r_spy; beta the trailing factor_beta.window OLS slope against SPY daily log returns', 'kernels/residual.py'),
    ('idiosyncratic_volatility', 'sample std (ddof=1) of the market residual over feature.idiosyncratic_volatility.window', 'kernels/residual.py'),
    ('market_residual_z', 'trailing time-series z of the name''s own market residual over feature.market_residual.z_window', 'kernels/residual.py'),
    ('market_residual_lag1_acf', 'lag-1 autocorrelation of the market residual over feature.market_residual.lag1_acf_window', 'kernels/residual.py'),
    ('residual_beta_stability', 'sample std (ddof=1) of the rolling equity beta over feature.residual_beta_stability.window', 'kernels/residual.py'),
    ('max_daily_return', 'largest daily log return over feature.max_daily_return.window', 'kernels/distribution.py'),
    ('max_drawdown', '1 - min(close / running max close) over feature.max_drawdown.window, in [0, 1], price-only', 'kernels/distribution.py'),
    ('downside_deviation', 'sqrt(mean(min(r, 0)^2)) over feature.downside_deviation.window', 'kernels/distribution.py'),
    ('size_proxy', 'mean ln(close * volume) over feature.size_proxy.window own-timeframe bars', 'kernels/distribution.py'),
    ('dividend_yield', 'trailing dividend amounts over feature.dividend_yield.window dates divided by close; NaN outside dividend_event_coverage', 'kernels/dividend.py')
) AS v(name, description, module)
ON CONFLICT DO NOTHING;

COMMIT;
