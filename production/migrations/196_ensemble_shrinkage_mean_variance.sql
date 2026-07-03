-- Migration 196: E1 shrinkage + E2 mean-variance APR contract (Phase 142B.1, Wave 0)
--
-- Ships the schema/APR interface every downstream E1 (shrinkage) and E2 (mean-variance
-- combination) wave reads/writes. Three additive changes, all strictly non-breaking:
--
-- 1. feature_ic_scores gains ic_shrunk + shrinkage_weight (double precision, nullable).
--    E1 writes these via a bulk UPDATE post-processing step (services/_batch_utils.py's
--    bulk_update_by_key); no existing column, index, or row is touched.
-- 2. Four new alpha.* APR keys, seeded with NON-BREAKING defaults so this migration can
--    land before E1/E2 code exists without changing any current runtime behavior:
--      - alpha.ic.shrinkage_k            (E1 shrinkage calibration constant)
--      - alpha.ensemble.mv_condition_max (E2 np.linalg.cond gate for Sigma^-1 . IC solve)
--      - alpha.ensemble.weight_method    (default 'ic_proportional' == existing v1 behavior)
--      - alpha.ensemble.ic_input         (default 'ic_sharpe_hac' == existing v1 behavior)
-- 3. alpha_ensemble_ic gains weight_version (text, NOT NULL, backfilled 'v1'). Without
--    this, the A/B judge (Plan 05's ops_ensemble_weight_compare.py) has no column to
--    GROUP BY / filter on to keep two weight variants' measurements separate -- the
--    entire point of this phase (comparing v1 vs an E1/E2 challenger) is unbuildable
--    without it. Mirrors alpha_events.weight_version (migration 168), which is already
--    NOT NULL there.
--
-- See .planning/phases/142B.1-ensemble-weighting-methodology-replace-ensemble-trainer-py-s/
-- 142B.1-CONTEXT.md D-04 through D-08 for the full decision trail.
--
-- All statements idempotent: ADD COLUMN IF NOT EXISTS, idempotent DO-block for the CHECK
-- constraint (mirrors migration 150's pg_constraint existence-guard pattern), ON CONFLICT
-- DO NOTHING per key insert, backfill UPDATE is a no-op once applied. Safe to re-run.

BEGIN;

-- -------------------------------------------------------------------------
-- Section 1: feature_ic_scores.ic_shrunk + shrinkage_weight (E1 schema footprint)
-- -------------------------------------------------------------------------

ALTER TABLE feature_ic_scores
    ADD COLUMN IF NOT EXISTS ic_shrunk double precision,
    ADD COLUMN IF NOT EXISTS shrinkage_weight double precision;

-- shrinkage_weight is w = n_eff/(n_eff+k) -- always in [0, 1] by construction. NULL is
-- allowed (E1 has not yet computed this cell). Idempotent guard mirrors migration 150's
-- pg_constraint existence-check pattern.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'feature_ic_scores'::regclass
          AND conname = 'chk_fis_shrinkage_weight_unit_interval'
    ) THEN
        ALTER TABLE feature_ic_scores
            ADD CONSTRAINT chk_fis_shrinkage_weight_unit_interval
            CHECK (shrinkage_weight IS NULL OR (shrinkage_weight BETWEEN 0 AND 1));
    END IF;
END $$;

-- -------------------------------------------------------------------------
-- Section 2: alpha.ic.shrinkage_k / alpha.ensemble.* APR seeds (4 keys)
-- Each key: config_schema INSERT, config_state INSERT, config_history INSERT --
-- config_schema/config_state each idempotent via their own ON CONFLICT (config_key)
-- DO NOTHING (migration 195's three-table triad pattern, one INSERT per key).
-- -------------------------------------------------------------------------

-- Key 1: alpha.ic.shrinkage_k

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ic.shrinkage_k',
    'float',
    '100',
    '[initial_estimate, ML learning target] E1 shrinkage effective-sample-size '
    'calibration constant: w = n_eff/(n_eff+k), the weight placed on a cell''s own raw '
    'ic_sharpe_hac vs. its leave-one-out peer-group prior. Seeded so a cell at exactly '
    'min_reliable_n=100 gets ~50% shrinkage toward its peer-group prior (n_eff=k -> '
    'w=0.5). Validated and recalibrated by the D-05 out-of-fold acceptance test. '
    'See todo 029 for the shrinkage design.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.shrinkage_k', '100', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.shrinkage_k', 1, '100', 'migration_196',
    'Initial estimate: E1 shrinkage k, see todo 029 [initial_estimate, ML learning target]'
);

-- Key 2: alpha.ensemble.mv_condition_max

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ensemble.mv_condition_max',
    'float',
    '1000',
    '[initial_estimate] E2 gate: maximum allowed np.linalg.cond(cov_matrix) (2-norm '
    'condition number) before the Sigma^-1 . IC mean-variance solve is considered '
    'ill-conditioned and E2 falls back to the existing cluster_deflate_weights path '
    '(RESEARCH.md Assumption A3, Pitfall 3). Slated for recalibration once real '
    'condition-number distributions are observed from the first mean_variance run. '
    'NOT an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.mv_condition_max', '1000', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.mv_condition_max', 1, '1000', 'migration_196',
    'Initial estimate: E2 condition-number gate, recalibrate after first mean_variance '
    'run [initial_estimate]'
);

-- Key 3: alpha.ensemble.weight_method (non-breaking default -- existing v1 behavior)

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ensemble.weight_method',
    'str',
    'ic_proportional',
    '[conventional] Selects the ensemble weight-derivation branch in ensemble_trainer.py: '
    '''ic_proportional'' (existing v1 behavior -- derive_weights -> cluster_deflate_weights, '
    'purely additive IC-Sharpe weighting) or ''mean_variance'' (E2 -- Sigma^-1 . IC '
    'combination via mean_variance_weights, gated by alpha.ensemble.mv_condition_max). '
    'Default preserves current v1 behavior exactly -- this migration changes no runtime '
    'output until E2 code reads this key and an operator explicitly sets it to '
    '''mean_variance''.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.weight_method', 'ic_proportional', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.weight_method', 1, 'ic_proportional', 'migration_196',
    'Conventional: non-breaking default preserves existing v1 weight derivation '
    '[conventional]'
);

-- Key 4: alpha.ensemble.ic_input (non-breaking default -- existing v1 behavior)

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ensemble.ic_input',
    'str',
    'ic_sharpe_hac',
    '[conventional] Selects which feature_ic_scores column ensemble_trainer.py reads as '
    'the per-feature IC input: ''ic_sharpe_hac'' (existing v1 column, pre-shrinkage) or '
    '''ic_shrunk'' (E1''s shrinkage-adjusted column, migration 196 Section 1). Default '
    'keeps ensemble_trainer.py reading ic_sharpe_hac until E1''s hard out-of-fold gate '
    '(D-05) passes -- this migration changes no runtime output on its own.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.ic_input', 'ic_sharpe_hac', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.ic_input', 1, 'ic_sharpe_hac', 'migration_196',
    'Conventional: non-breaking default preserves existing v1 IC column [conventional]'
);

-- -------------------------------------------------------------------------
-- Section 3: alpha_ensemble_ic.weight_version (D-01 fix -- A/B comparison keying)
-- -------------------------------------------------------------------------
-- Backfill first (existing rows, including the D-02 v1 baseline, predate weight
-- variants and are all 'v1'), then enforce NOT NULL -- standard add-then-tighten
-- sequence for a column going onto a table with existing rows.

ALTER TABLE alpha_ensemble_ic
    ADD COLUMN IF NOT EXISTS weight_version text;

UPDATE alpha_ensemble_ic SET weight_version = 'v1' WHERE weight_version IS NULL;

ALTER TABLE alpha_ensemble_ic
    ALTER COLUMN weight_version SET NOT NULL;

COMMIT;
