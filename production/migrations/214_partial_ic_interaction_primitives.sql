-- Migration 214: partial-IC columns on feature_ic_scores + APR keys for todo 037
-- (Interaction Primitives pilot).
--
-- Adds nullable partial_ic/partial_ic_p_value/partial_ic_n/passes_partial_fdr columns,
-- populated only for tier='1_interaction' features (feature_registry) by
-- scripts/ops/alpha/ops_interaction_primitives_pilot.py. NULL for every tier='0_atomic'
-- row -- naive IC there is the only meaningful measurement, there is no "parent" to
-- control for.
--
-- Two dedicated APR keys, each a distinct test/tuning family from every existing key
-- (same reasoning as migration 213's alpha.ensemble.compare_fdr_alpha: coupling
-- unrelated multiplicity budgets or numerical-stability caps to an existing key would
-- be an APR-mandate violation in spirit, not just letter):
--   alpha.ic.partial_fdr_alpha              -- BH-FDR alpha for the small
--                                               partial-IC family (~8 features x a
--                                               handful of tf/lookahead cells each),
--                                               separate from alpha.ic.fdr_alpha's
--                                               516K-hypothesis corpus-wide family.
--   alpha.ic.partial_control_condition_max  -- design-matrix condition-number ceiling
--                                               for partial_spearman_ic's ill-
--                                               conditioning guard. Seeded to 1000.0,
--                                               matching the E2 mean-variance path's
--                                               mv_condition_max precedent
--                                               (services/ensemble_ic_engine.py).
--
-- [initial_estimate] Not an ML learning target.

BEGIN;

ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic double precision;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic_p_value double precision;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS partial_ic_n integer;
ALTER TABLE feature_ic_scores ADD COLUMN IF NOT EXISTS passes_partial_fdr boolean;

COMMENT ON COLUMN feature_ic_scores.partial_ic IS
    'Partial Spearman IC controlling for the feature''s parent atomics (feature_registry.parent_features). NULL for tier=0_atomic features. Populated by ops_interaction_primitives_pilot.py (todo 037).';
COMMENT ON COLUMN feature_ic_scores.partial_ic_p_value IS
    'p-value for partial_ic, t-approximation with df = n - k - 2 (k = number of parent controls).';
COMMENT ON COLUMN feature_ic_scores.partial_ic_n IS
    'Observation count used for partial_ic (post-subsampling, post-embargo).';
COMMENT ON COLUMN feature_ic_scores.passes_partial_fdr IS
    'BH-FDR pass/fail for partial_ic_p_value within the interaction-primitive family (alpha.ic.partial_fdr_alpha), corrected separately from the corpus-wide atomic-feature FDR family.';

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ic.partial_fdr_alpha',
    'float',
    '0.05',
    0.001, 0.20,
    '[initial_estimate] Benjamini-Hochberg FDR correction alpha for the interaction-'
    'primitive partial-IC family (todo 037). Same conventional 5% as alpha.ic.fdr_alpha '
    '(migration 161) but a dedicated key: this family is ~8 features x a handful of '
    '(tf, lookahead) cells, a different multiplicity budget than the 516K-hypothesis '
    'corpus-wide atomic-feature FDR pass. Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.partial_fdr_alpha', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.partial_fdr_alpha', 1, '0.05', 'migration_214',
    'Initial seed: same conventional 5% as alpha.ic.fdr_alpha [initial_estimate]'
);

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ic.partial_control_condition_max',
    'float',
    '1000.0',
    10.0, 100000.0,
    '[initial_estimate] Condition-number ceiling for partial_spearman_ic''s control-'
    'design-matrix ill-conditioning guard (todo 037). Above this, the control set is '
    'too collinear for a numerically stable partial correlation and partial_ic is '
    'returned as NULL rather than a garbage number. Seeded to match the E2 mean-'
    'variance path''s mv_condition_max precedent (services/ensemble_ic_engine.py). '
    'Not an ML learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ic.partial_control_condition_max', '1000.0', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ic.partial_control_condition_max', 1, '1000.0', 'migration_214',
    'Initial seed: matches ensemble_ic_engine.py mv_condition_max precedent [initial_estimate]'
);

COMMIT;
