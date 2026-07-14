-- Migration 234: seed domain='ensemble_strategy' into the Concept Registry MVP (todo 058)
--
-- Seed data re-derived against live DB 2026-07-13 - the todo's 2026-07-04 snapshot
-- ("only weight_version='v1', 103 rows") is stale. Live state: ensemble_weights holds
-- run_2025122405150000 (193 rows, E1: APR ic_input='ic_shrunk' + weight_method=
-- 'ic_proportional' at run time) and run_2025122405150000_mv (251 rows, E2 mean-variance
-- challenger from the 2026-07-09 A/B). weight_version is a data-scoping epoch tag only
-- (migration 224); no ensemble_weights column identifies the E-variant, so concept identity
-- lives HERE, in metadata->'recipe' (the definitional ic_input/weight_method combination,
-- which is recipe identity like the 5 in momentum_z_5, not a tunable value copy).
--
-- Status semantics (F2 resolution, recorded in concept_registry's table comment):
-- status = recipe validity; per-stratum champions stay facts in ensemble_weights;
-- redundancy_group displacement is disabled for this domain (redundancy_group left NULL).
-- No E-variant has ever cleared a formal A/B win (E2's 2026-07-09 20/20-LOSS result was
-- invalidated as all-long-vs-all-long pre-todo-094; re-run sequenced in Phase 143.1), so
-- ic_proportional seeds active (genesis incumbent) and e1_shrunk_ic seeds candidate even
-- though it is the deployed champion-by-default - deployment is an observation annotation,
-- not a status.
--
-- Invariant-6 exception (todo 058 item 6): E1-E4 are human-authored, so the mandatory
-- shadow_only stage between candidate and active does not bind for this domain the way it
-- would for an AI-sourced concept. The OOS A/B judged by EnsembleICEngine on live corpus
-- runs (per-stratum, non-overlapping-CI win rule, walk-forward-stable veto, BH-FDR
-- corrected, via ops_ensemble_weight_compare.py) is this domain's evidentiary substitute
-- for a live shadow period. Documented in docs/research/concept-unified-registry.md
-- Invariant 6, same pattern as the domain='feature' exception.
--
-- gate rows: gate_eval_method='oos_holdout' (the Domains table's "OOS, via EnsembleICEngine");
-- gate_metric_name='ensemble_ic_ci_lower' (D-15 citation rule: ic_ci_lower, never ic_value);
-- min_gate_metric NULL because the win rule is relative CI ordering vs the champion, not an
-- absolute scalar threshold; min_promotion_consecutive / min_new_observations NULL = inherit
-- the APR defaults seeded by migration 233; fdr_required=true with fdr_alpha NULL = inherit
-- alpha.ensemble.compare_fdr_alpha (the compare script's existing BH-FDR key).
--
-- M-4 CORRECTION (phase 160 cross-AI review): min_gate_n seeds NULL on all 5 rows, not 1000.
-- A non-NULL per-concept min_gate_n overrides the APR default, which would make
-- alpha.concept_registry.ensemble_strategy_min_observations dead-on-arrival: the key would
-- exist and appear on the /config/parameters dashboard, but tuning it would silently do
-- nothing for every seeded concept. Seeding it NULL makes all three floors (min_gate_n,
-- min_promotion_consecutive, min_new_observations) inherit the migration-233 APR defaults
-- uniformly, which is what the APR philosophy this migration set cites requires.
--
-- Idempotent: every INSERT is ON CONFLICT DO NOTHING or guarded by WHERE NOT EXISTS.
-- Safe to re-run.

BEGIN;

INSERT INTO concept_registry (domain, name, description, status, enabled, metadata, added_phase)
VALUES
(
    'ensemble_strategy', 'ic_proportional',
    'v1 incumbent: per-stratum weights proportional to raw HAC IC Sharpe '
    '(alpha.ensemble.ic_input=ic_sharpe_hac, alpha.ensemble.weight_method=ic_proportional).',
    'active', true,
    '{"recipe": {"ic_input": "ic_sharpe_hac", "weight_method": "ic_proportional"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e1_shrunk_ic',
    'E1: empirical-Bayes shrunk IC inputs (shrink_ic) feeding ic_proportional weighting '
    '(alpha.ensemble.ic_input=ic_shrunk, alpha.ensemble.weight_method=ic_proportional).',
    'candidate', true,
    '{"recipe": {"ic_input": "ic_shrunk", "weight_method": "ic_proportional"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e2_mean_variance',
    'E2: mean-variance weighting (inverse Ledoit-Wolf covariance times shrunk IC vector, '
    'alpha.ensemble.weight_method=mean_variance, condition-number capped).',
    'candidate', true,
    '{"recipe": {"ic_input": "ic_shrunk", "weight_method": "mean_variance"}}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e3_hierarchical_pooling',
    'E3: hierarchical partial pooling of per-stratum IC estimates toward tf/regime-level '
    'hyperpriors before weighting. Thesis only; no shipped mechanism.',
    'candidate', false,
    '{"recipe": null}'::jsonb,
    'todo-058'
),
(
    'ensemble_strategy', 'e4_decay_half_life',
    'E4: per-feature IC decay half-lives replacing the single global staleness half-life. '
    'Thesis only; no shipped mechanism.',
    'candidate', false,
    '{"recipe": null}'::jsonb,
    'todo-058'
)
ON CONFLICT (domain, name) DO NOTHING;

-- M-4: min_gate_n seeded NULL (not 1000) so all 5 rows inherit the
-- alpha.concept_registry.ensemble_strategy_min_observations APR default.
INSERT INTO concept_gate
    (concept_id, gate_metric_name, gate_eval_method, min_gate_n, fdr_required)
SELECT concept_id, 'ensemble_ic_ci_lower', 'oos_holdout', NULL, true
FROM concept_registry
WHERE domain = 'ensemble_strategy'
ON CONFLICT (concept_id) DO NOTHING;

-- Genesis transition for the incumbent only: establishes ic_proportional as active without
-- fabricating a promotion event. corpus_build_ref NULL - pre-registry incumbency is not
-- attributable to a specific corpus build.
INSERT INTO concept_transition_log
    (concept_id, domain, name, from_status, to_status, trigger_reason, notes)
SELECT concept_id, 'ensemble_strategy', 'ic_proportional', 'candidate', 'active',
       'genesis_seed',
       'Genesis seed (todo 058): incumbent by construction since Phase 139/142A, no formal '
       'promotion event exists. Recipe validity granted by incumbency; deployment has since '
       'moved to e1_shrunk_ic via the alpha.ensemble.ic_input APR flip (a deployment fact, '
       'not a registry demotion).'
FROM concept_registry
WHERE domain = 'ensemble_strategy' AND name = 'ic_proportional'
  AND NOT EXISTS (
      SELECT 1 FROM concept_transition_log t
      WHERE t.domain = 'ensemble_strategy' AND t.name = 'ic_proportional'
        AND t.trigger_reason = 'genesis_seed'
  );

-- Annotations. All source='human' (E1-E4 are human-authored; nothing here was written by
-- the evaluation engine). Idempotency guard: one row per (concept, type, first 40 chars).
INSERT INTO concept_annotation (concept_id, annotation_type, content, source)
SELECT r.concept_id, a.annotation_type, a.content, 'human'
FROM concept_registry r
JOIN (VALUES
    ('ic_proportional', 'thesis',
     'Weighting each eligible feature proportionally to its measured IC strength is the '
     'simplest defensible aggregation: it preserves sign, requires no covariance estimate, '
     'and degrades gracefully when per-feature IC estimates are noisy.'),
    ('ic_proportional', 'implementation',
     'services/ensemble_trainer.py compute path with alpha.ensemble.ic_input=ic_sharpe_hac '
     'and alpha.ensemble.weight_method=ic_proportional; weights derived via derive_weights() '
     'in src/intelligence/ensemble/ with the max_feature_weight cap.'),
    ('ic_proportional', 'observation',
     '2026-07-13: superseded as the deployed default by e1_shrunk_ic via the '
     'alpha.ensemble.ic_input APR flip to ic_shrunk. Remains active in the registry: recipe '
     'validity was never evidence-revoked; deployment is a fact recorded in APR and '
     'ensemble_weights, not in status (F2 resolution).'),
    ('e1_shrunk_ic', 'thesis',
     'Per-feature IC estimates are noisy at stratum grain; empirical-Bayes shrinkage toward '
     'the peer mean (weighted by effective N) reduces estimation variance in the weight '
     'vector, so weights track persistent skill rather than single-window luck.'),
    ('e1_shrunk_ic', 'implementation',
     'src/intelligence/ensemble/shrinkage.py::shrink_ic feeding the ic_proportional path in '
     'services/ensemble_trainer.py; selected by alpha.ensemble.ic_input=ic_shrunk. The '
     'shrunk-IC column in feature_ic_scores is written solely by the gate script.'),
    ('e1_shrunk_ic', 'observation',
     '2026-07-13: deployed operational champion-by-default (live APR: ic_input=ic_shrunk, '
     'weight_method=ic_proportional; live rows weight_version=run_2025122405150000, 193 '
     'rows, computed 2026-07-10). Has NEVER cleared a formal A/B win against '
     'ic_proportional; status stays candidate until the registry gate is earned (the '
     'deployed-vs-proven distinction is exactly what this registry exists to keep honest).'),
    ('e2_mean_variance', 'thesis',
     'IC-proportional weighting ignores feature covariance and so over-allocates to '
     'correlated clusters. Mean-variance combination (inverse shrunk covariance times the '
     'shrunk IC vector) is the portfolio-theoretic optimum under Gaussian assumptions, with '
     'a condition-number cap (alpha.ensemble.mv_condition_max) guarding ill-conditioned '
     'covariance inversions.'),
    ('e2_mean_variance', 'implementation',
     'src/intelligence/ensemble/weights.py::mean_variance_weights over '
     'src/intelligence/ensemble/covariance.py::compute_shrinkage_covariance (Ledoit-Wolf); '
     'selected by alpha.ensemble.weight_method=mean_variance; falls back to ic_proportional '
     'when the condition number exceeds alpha.ensemble.mv_condition_max '
     '(method_used=mean_variance_fallback).'),
    ('e2_mean_variance', 'observation',
     '2026-07-13: the 2026-07-09 A/B vs e1_shrunk_ic (challenger rows weight_version='
     'run_2025122405150000_mv, 251 rows) returned 20/20 strata LOSS, but that result is '
     'INVALIDATED - both sides were all-long pre-todo-094 (sign-symmetric eligibility), so '
     'the comparison does not carry forward. Re-run sequenced in Phase 143.1 after '
     'components 094/097. No transition was or will be logged from the invalidated round.'),
    ('e3_hierarchical_pooling', 'thesis',
     'Per-stratum IC estimates share structure across tf and regime; hierarchical partial '
     'pooling (stratum estimates shrunk toward tf-level and global hyperpriors in '
     'proportion to within-stratum precision) should outperform flat shrinkage when strata '
     'are thin. No code exists; deferred at 142B.1 decision level.'),
    ('e4_decay_half_life', 'thesis',
     'Features decay at different rates; a per-feature IC decay half-life (estimated from '
     'each feature''s own IC time series) should replace any single global staleness '
     'half-life when weighting historical evidence. No code exists; deferred at 142B.1 '
     'decision level.'),
    ('e4_decay_half_life', 'observation',
     '2026-07-13 conflation guard: the live alpha.ensemble.weight_half_life_days=30 key is '
     'a single GLOBAL staleness decay applied in services/ensemble_trainer.py - it is not '
     'E4 and its existence does not make E4 partially shipped.')
) AS a(name, annotation_type, content)
  ON r.domain = 'ensemble_strategy' AND r.name = a.name
WHERE NOT EXISTS (
    SELECT 1 FROM concept_annotation ca
    WHERE ca.concept_id = r.concept_id
      AND ca.annotation_type = a.annotation_type
      AND left(ca.content, 40) = left(a.content, 40)
);

COMMIT;
