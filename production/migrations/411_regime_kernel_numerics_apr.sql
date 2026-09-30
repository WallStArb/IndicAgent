-- Migration 411: label-affecting HMM numerics to APR (phase 186 plan 186-13 review, D3)
--
-- Two constants carried verbatim from the pre-186 regime writer decide regime labels and lived
-- as literals in kernels/_hmm.py:
--   alpha.hmm.covariance_ridge    1e-6  added to every full-covariance matrix (times I) before
--                                       the Cholesky factorization in the log-emission
--   alpha.hmm.momentum_vol_floor  1e-8  floor on realized_vol in the trend momentum column
--                                       (sum of log returns / max(realized_vol, floor))
-- The seeds equal the literals, so stored labels and the regime golden do not change. The
-- kernels read them through HmmConfig (kernels/_hmm.py), the one declaration of the HMM keys.
-- 1e-300 (log and variance floors) stays a constant: a mathematical guard, not a tunable.
--
-- Guarded: the migration refuses (raises, nothing changes) if either key already exists with a
-- different default or value, rather than overwriting it.

BEGIN;

DO $$
DECLARE
    bad text;
BEGIN
    SELECT string_agg(config_key, ', ') INTO bad
    FROM config_schema
    WHERE (config_key = 'alpha.hmm.covariance_ridge' AND default_value IS DISTINCT FROM '0.000001')
       OR (config_key = 'alpha.hmm.momentum_vol_floor' AND default_value IS DISTINCT FROM '0.00000001');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'migration 411 refused: config_schema already holds a different default for %', bad;
    END IF;

    SELECT string_agg(config_key, ', ') INTO bad
    FROM config_state
    WHERE (config_key = 'alpha.hmm.covariance_ridge' AND config_value IS DISTINCT FROM '0.000001')
       OR (config_key = 'alpha.hmm.momentum_vol_floor' AND config_value IS DISTINCT FROM '0.00000001');
    IF bad IS NOT NULL THEN
        RAISE EXCEPTION 'migration 411 refused: config_state already holds a different value for %', bad;
    END IF;
END
$$;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.hmm.covariance_ridge',
    'float',
    '0.000001',
    0, 0.01,
    '[conventional] ridge added (times the identity) to each full-covariance matrix before the '
    'Cholesky factorization in the HMM log-emission; guards near-singular covariances on flat '
    'timeframes. Carried over from the pre-186 regime writer. Not an ML learning target. '
    'CHANGING THIS INVALIDATES every stored regime label (full re-run of regime_writer and the '
    'rebuild).'
),
(
    'alpha.hmm.momentum_vol_floor',
    'float',
    '0.00000001',
    0.000000000001, 0.01,
    '[conventional] floor on realized volatility in the trend HMM momentum observation '
    '(sum of log returns / max(realized_vol, floor)); avoids division by zero on flat series. '
    'Carried over from the pre-186 regime writer. Not an ML learning target. CHANGING THIS '
    'INVALIDATES every stored trend regime label (full re-run of regime_writer and the rebuild).'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.hmm.covariance_ridge', '0.000001', 1),
('alpha.hmm.momentum_vol_floor', '0.00000001', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT NOW(), v.config_key, 1, v.config_value, 'migration_411', v.reason
FROM (VALUES
    ('alpha.hmm.covariance_ridge', '0.000001',
     'Initial value: the literal 1e-6 the kernels carried since the pre-186 writer [conventional]'),
    ('alpha.hmm.momentum_vol_floor', '0.00000001',
     'Initial value: the literal 1e-8 the kernels carried since the pre-186 writer [conventional]')
) AS v(config_key, config_value, reason)
WHERE NOT EXISTS (
    SELECT 1 FROM config_history h
    WHERE h.config_key = v.config_key AND h.changed_by = 'migration_411'
);

COMMIT;
