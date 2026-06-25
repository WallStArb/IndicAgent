-- Migration 171: IC engine correctness — Phase 140.
--
-- Three changes:
--
-- 1. feature_ic_scores.cluster_id (SMALLINT NULL)
--    Correlation-cluster ID assigned by ic_engine during BH-FDR correction.
--    The cluster representative (highest |ic_value|) is the only feature that
--    receives a multiple-testing correction slot; non-representatives are marked
--    passes_fdr=false. NULL for rows written before Phase 140.
--
-- 2. alpha.ensemble.meta_fdr_min_fraction
--    Gate added in ensemble_trainer.py (Phase 140 P3): a feature must pass
--    BH-FDR in at least this fraction of (symbol, tf) cells to be eligible for
--    ensemble weight. Prevents features that are strong in one niche from riding
--    the ensemble purely on that niche.
--
-- 3. alpha.ic.cluster_max_corr
--    Correlation threshold used by ic_engine.py (Phase 140 P2) to build a
--    distance-threshold dendrogram cluster of features before BH-FDR. Converted
--    internally to a correlation-distance cutoff for scipy fcluster().
--
-- 4. alpha.ic.sharpe_min_windows: 10 → 30
--    Phase 140 Issue 5: at stride=5 bars the minimum 10-window requirement only
--    demands 50 bars of rolling IC history. Standard error at N=10 is ~0.32
--    (1/sqrt(10)); raising to 30 cuts SE to ~0.18 (1/sqrt(30)) and makes the
--    Sharpe gate a meaningful reliability filter without discarding symbols.

BEGIN;

-- 1. Cluster ID column on feature_ic_scores
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS cluster_id SMALLINT NULL;
COMMENT ON COLUMN feature_ic_scores.cluster_id IS
    'Correlation cluster ID for this (symbol, tf, regime, training_window_end) run. '
    'Cluster representative has the highest |ic_value| within cluster. '
    'Non-representatives have passes_fdr=false. NULL for pre-Phase-140 rows.';

-- 2. New APR keys: meta_fdr_min_fraction and cluster_max_corr
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description) VALUES
(
    'alpha.ensemble.meta_fdr_min_fraction',
    'float',
    '0.50',
    0.0, 1.0,
    '[initial_estimate] Minimum fraction of (symbol, tf) cells in which a feature must pass BH-FDR before it is eligible for ensemble weight. Guards meta-level false discovery across the 232-cell universe. Conservative starting value; revisit after the first clean corpus run — 0.50 may suppress niche alpha that is genuinely strong in a subset of symbols/TFs if set too high. Candidate ML learning target.'
),
(
    'alpha.ic.cluster_max_corr',
    'float',
    '0.70',
    0.0, 1.0,
    '[initial_estimate] Correlation threshold driving distance-threshold dendrogram clustering of features before BH-FDR. It is converted to a correlation-distance cutoff for scipy fcluster(criterion=distance); this is a dendrogram distance cutoff, NOT a guarantee that every pair within a cluster exceeds this correlation. Only the cluster representative receives multiple-testing correction. Candidate ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version) VALUES
('alpha.ensemble.meta_fdr_min_fraction', '0.50', 1),
('alpha.ic.cluster_max_corr',            '0.70', 1)
ON CONFLICT (config_key) DO NOTHING;

-- 3. Raise alpha.ic.sharpe_min_windows: 10 → 30
UPDATE config_state
SET config_value = '30', updated_at = NOW(), version = version + 1
WHERE config_key = 'alpha.ic.sharpe_min_windows';

-- No trigger on config_state; write history row manually.
INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
SELECT
    NOW(),
    'alpha.ic.sharpe_min_windows',
    version,
    '30',
    'migration_171',
    'Raise IC Sharpe reliability floor: SE 0.32->0.18 (Phase 140 Issue 5)'
FROM config_state
WHERE config_key = 'alpha.ic.sharpe_min_windows';

COMMIT;
