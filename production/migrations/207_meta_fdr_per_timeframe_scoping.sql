-- Migration 207: meta-FDR eligibility gate — per-timeframe scoping + min-cells floor
--
-- ensemble_trainer.py's meta-FDR replication test previously pooled BH-FDR pass/fail
-- outcomes across ALL 4 timeframes into one fraction per feature (GROUP BY feature_name
-- only), then required >=meta_fdr_min_fraction to admit the feature into ANY stratum's
-- ensemble weighting. Timeframes are not exchangeable draws of the same experiment --
-- different bars/day, different noise floor, different economically-meaningful horizon
-- -- so pooling across that axis conflated cross-timeframe statistical-power differences
-- with feature quality. Empirically confirmed against the live 2026-07-08 corpus: 18
-- feature x timeframe combinations flip from ineligible to eligible under per-timeframe
-- scoping, in an economically coherent direction (e.g. vix_z passes 75%/100% of its
-- 1d/1h cells but was globally vetoed by weaker 5m showings). Root cause of 1d/1h having
-- zero/near-zero ensemble_weights strata after the 2026-07-08 corpus rebuild.
--
-- Code fix (services/ensemble_trainer.py, this same session): GROUP BY feature_name, tf
-- instead of GROUP BY feature_name; _meta_eligible() now returns dict[tf, set[feature]].
--
-- This migration seeds the one new APR key the fix reads: alpha.ensemble.meta_fdr_min_cells
-- -- a minimum-evidence floor so a single-cell "100% pass rate" (a tautology, not
-- replication) cannot trivially clear the per-tf fraction test. Seeded at 3, matching the
-- existing minimum-replication convention already used by EIC-03's 3-fold walk-forward
-- stability gate -- not an arbitrary pick.
--
-- Non-breaking on its own: this migration only inserts the new key. The behavior change
-- ships in the same commit as the code (migrate-as-you-go), but the key's existence alone
-- does nothing until ensemble_trainer.py reads it.

BEGIN;

INSERT INTO config_schema (config_key, value_type, default_value, description)
VALUES (
    'alpha.ensemble.meta_fdr_min_cells',
    'int',
    '3',
    '[initial_estimate] Minimum number of (regime) cells a (feature, tf) pair must appear '
    'in before its per-timeframe BH-FDR pass-rate is trusted by the meta-FDR eligibility '
    'gate. Below this floor, a fraction like 1/1=100% is a tautology, not replication '
    'evidence. Seeded at 3 to match the existing minimum-replication convention already '
    'used by EIC-03''s 3-fold walk-forward stability gate. Paired with '
    'alpha.ensemble.meta_fdr_min_fraction, which is now scoped per-timeframe rather than '
    'pooled across all 4 timeframes (migration 207 fix) -- see services/ensemble_trainer.py '
    '_meta_eligible() docstring for the full rationale.'
)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES ('alpha.ensemble.meta_fdr_min_cells', '3', 1)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_history (timestamp, config_key, version, config_value, changed_by, reason)
VALUES (
    NOW(), 'alpha.ensemble.meta_fdr_min_cells', 1, '3', 'migration_207',
    'Initial estimate: minimum-cells floor for per-timeframe meta-FDR eligibility, '
    'matches EIC-03''s 3-fold walk-forward convention [initial_estimate]'
);

COMMIT;
