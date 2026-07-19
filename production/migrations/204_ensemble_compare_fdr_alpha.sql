-- Migration 204: APR key for ops_ensemble_weight_compare.py's BH-FDR multiplicity
-- correction across (tf, regime) strata (todo 069 / measurement-ic-engine.md OQ7 --
-- the ensemble-grain winner's-curse decision)
--
-- ops_ensemble_weight_compare.py's D-10 win rule (challenger.ic_ci_lower >
-- champion.ic_ci_upper AND challenger.walk_forward_stable) is applied independently
-- across every (tf, regime) stratum present for both weight_versions being compared --
-- roughly 4 tfs x 9 cross-sectional regime labels = ~36 strata per comparison round.
-- Per docs/research/fable-2026-07-09-ensemble-winners-curse-peer-group.md: under a
-- global null, expected false WINs across that family are ~36 x 0.006 = 0.2, so the
-- chance of at least one fluke WIN somewhere in the family is ~20% -- real multiplicity
-- that BH-FDR already controls at feature grain (alpha.ic.fdr_alpha, migration 161) and
-- now needs to control at ensemble-variant-comparison grain too.
--
-- A WIN now requires D-10 AND BH-adjusted p < this alpha; a stratum that passes D-10
-- but fails BH-FDR reports as WIN-FDR-VETO, a distinct verdict from LOSS (see
-- ops_ensemble_weight_compare.py's _final_verdict()).
--
-- Seeded to the same value as alpha.ic.fdr_alpha (migration 161) -- same conventional
-- 5% choice -- but kept as a DEDICATED key because the strata family compared here
-- (ensemble weight_version A/B judgment rounds) is a different test family than the
-- feature-corpus BH-FDR pass; coupling them to one shared key would coordinate two
-- independently-tunable multiplicity budgets, an APR-mandate violation in spirit.
--
-- [conventional] Not an ML learning target.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'alpha.ensemble.compare_fdr_alpha',
    'float',
    '0.05',
    0.001, 0.20,
    '[conventional] Benjamini-Hochberg FDR correction alpha for ops_ensemble_weight_compare.py''s '
    'per-stratum winner''s-curse multiplicity correction (todo 069 / measurement-ic-engine.md '
    'OQ7). Seeded to the same conventional 5% as alpha.ic.fdr_alpha (migration 161) but kept as '
    'a dedicated key since the strata family here (ensemble weight_version A/B comparison '
    'rounds) is a different test family than the feature-corpus BH-FDR pass. Not an ML '
    'learning target.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.compare_fdr_alpha', '0.05', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.compare_fdr_alpha', 1, '0.05', 'migration_213',
    'Initial seed: same conventional 5% as alpha.ic.fdr_alpha [conventional]'
);

COMMIT;
