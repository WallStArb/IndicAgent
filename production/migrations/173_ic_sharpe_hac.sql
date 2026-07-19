-- Migration 173: HAC-corrected IC Sharpe + bootstrap key cleanup.
--
-- 1. feature_ic_scores.ic_sharpe_hac (double precision NULL)
--    Newey-West Bartlett-kernel HAC-corrected IC Sharpe, stored alongside the
--    naive ic_sharpe. Adjusts for autocorrelation in rolling-window IC values:
--      ic_sharpe_hac = mean(IC_windows) / (std(IC_windows) * sqrt(inflation))
--      inflation = 1 + 2 * sum_{k=1}^{K} (1 - k/(K+1)) * rho_k(IC)
--    where K = alpha.ic.hac_max_lag and rho_k is the k-th autocorrelation of the
--    IC series across windows. Regime-persistent features (high IC autocorrelation)
--    will have ic_sharpe_hac < ic_sharpe. The naive Sharpe is retained for continuity.
--    NULL for rows written before this migration (pre-Phase-141 rows).
--
-- 2. alpha.ic.hac_max_lag (int, default 3)
--    Bartlett-kernel max lag K for Newey-West HAC IC Sharpe correction.
--    K=0 degenerates to naive Sharpe (no autocorrelation adjustment).
--    K=3 is a standard choice for the IC series at 30-100 rolling windows;
--    revise upward if IC series autocorrelation extends beyond lag 3.
--
-- 3. Deprecate bootstrap APR keys (now unused after Fisher z replacement).
--    Keys remain in config_state for historical continuity but are soft-deleted
--    from config_schema by marking them with a [deprecated] prefix so the UI
--    surfaces them as unused. Code no longer reads these keys (ic_engine.py
--    replaced circular block bootstrap with Fisher z-transform in migration 176 era).

BEGIN;

-- 1. HAC Sharpe column
ALTER TABLE feature_ic_scores
    ADD COLUMN IF NOT EXISTS ic_sharpe_hac double precision;

COMMENT ON COLUMN feature_ic_scores.ic_sharpe_hac IS
    'Newey-West Bartlett-kernel HAC-corrected IC Sharpe. Adjusts for autocorrelation '
    'in rolling-window IC series. ic_sharpe_hac <= ic_sharpe when IC is positively '
    'autocorrelated (regime-persistent features). NULL for pre-Phase-141 rows.';

-- 2. HAC max lag APR key
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ic.hac_max_lag',
    'int',
    '3',
    0, 20,
    '[initial_estimate] Bartlett-kernel max lag K for Newey-West HAC correction of the rolling-window IC Sharpe. '
    'K=0 disables HAC correction (ic_sharpe_hac == ic_sharpe). K=3 is standard for a 30-100 window IC series. '
    'Increase if IC autocorrelation at lag 3+ is material. Not an ML learning target -- methodological parameter. '
    'Inflates Sharpe denominator by sqrt(1 + 2*sum_k w_k*rho_k) where w_k = Bartlett weight.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.hac_max_lag', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

-- 3. Mark bootstrap APR keys as deprecated (code no longer reads them)
UPDATE config_schema
SET description = '[deprecated] ' || description
WHERE config_key IN (
    'alpha.ic.bootstrap_seed',
    'alpha.ic.bootstrap_resamples',
    'alpha.ic.bootstrap_block_size.5m',
    'alpha.ic.bootstrap_block_size.15m',
    'alpha.ic.bootstrap_block_size.1h',
    'alpha.ic.bootstrap_block_size.1d'
)
AND description NOT LIKE '[deprecated]%';

COMMIT;
