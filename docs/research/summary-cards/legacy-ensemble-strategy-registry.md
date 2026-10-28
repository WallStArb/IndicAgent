---
card_id: legacy-ensemble-strategy-registry
kind: legacy_verdict
title: Ensemble strategy registry rows (ic_proportional, E1 to E4)
idea: Five weighting strategies for the old IC-weighted ensemble, registered as concept_registry rows of domain ensemble_strategy with theses, implementations and gate rows, never promoted through a formal A/B.
verdict: NO_CONCLUSION
verdict_date: 2026-07-14
recipe:
  spec: null
  script: services/ensemble_trainer.py
  recipe_commit: ca4fd80e3a1087c9fbbac48f7057e31d123ced30
results:
  - name: ensemble_strategy_concepts
    value: 5
    source: db:concept_registry
  - name: concept_annotations
    value: 12
    source: db:concept_annotation
  - name: concept_gate_rows
    value: 5
    source: db:concept_gate
  - name: concept_transition_log_rows
    value: 1
    source: db:concept_transition_log
known_defects:
  - "E2's only A/B (2026-07-09, against E1, 20/20 strata LOSS) was invalidated because both sides were all-long before todo 094 (sign-symmetric eligibility); the re-run was never done."
  - "E1 was deployed as the operational default through an APR flip without ever clearing a formal A/B win; the registry gate was never earned."
  - "E3 and E4 are theses only; no code existed for either."
spans_looked_at: []
forward_span_looks: 0
tables: [concept_annotation, concept_gate, concept_transition_log]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - db:concept_registry
  - db:concept_annotation
  - db:concept_gate
  - db:concept_transition_log
related_cards: [legacy-ensemble-champion, legacy-phase142a-ensemble-ic]
---

# Ensemble strategy registry rows (ic_proportional, E1 to E4)

## What was tried

Phase 142B registered five weighting strategies for the old ensemble as `concept_registry` rows
of domain `ensemble_strategy`: the incumbent `ic_proportional` (weights proportional to raw HAC
IC Sharpe) and four challengers, E1 `e1_shrunk_ic` (empirical-Bayes shrunk IC inputs), E2
`e2_mean_variance` (inverse Ledoit-Wolf covariance times shrunk IC), E3
`e3_hierarchical_pooling` and E4 `e4_decay_half_life` (both thesis only). Each carried a
thesis, an implementation pointer and one `concept_gate` row for the metric
`ensemble_ic_ci_lower` on the `oos_holdout` scope.

## What was found

Nothing was promoted. `ic_proportional` was seeded active as the incumbent by construction
(one `concept_transition_log` row, a genesis seed, no promotion event); the four challengers
stayed candidates. The annotations below are copied verbatim from the 12 `concept_annotation`
rows (all source `human`, written 2026-07-14).

### ic_proportional

- thesis (annotation of 2026-07-14): Weighting each eligible feature proportionally to its measured IC strength is the simplest defensible aggregation: it preserves sign, requires no covariance estimate, and degrades gracefully when per-feature IC estimates are noisy.
- implementation (annotation of 2026-07-14): services/ensemble_trainer.py compute path with alpha.ensemble.ic_input=ic_sharpe_hac and alpha.ensemble.weight_method=ic_proportional; weights derived via derive_weights() in src/intelligence/ensemble/ with the max_feature_weight cap.
- observation (annotation of 2026-07-14): 2026-07-13: superseded as the deployed default by e1_shrunk_ic via the alpha.ensemble.ic_input APR flip to ic_shrunk. Remains active in the registry: recipe validity was never evidence-revoked; deployment is a fact recorded in APR and ensemble_weights, not in status (F2 resolution).

### e1_shrunk_ic

- thesis (annotation of 2026-07-14): Per-feature IC estimates are noisy at stratum grain; empirical-Bayes shrinkage toward the peer mean (weighted by effective N) reduces estimation variance in the weight vector, so weights track persistent skill rather than single-window luck.
- implementation (annotation of 2026-07-14): src/intelligence/ensemble/shrinkage.py::shrink_ic feeding the ic_proportional path in services/ensemble_trainer.py; selected by alpha.ensemble.ic_input=ic_shrunk. The shrunk-IC column in feature_ic_scores is written solely by the gate script.
- observation (annotation of 2026-07-14): 2026-07-13: deployed operational champion-by-default (live APR: ic_input=ic_shrunk, weight_method=ic_proportional; live rows weight_version=run_2025122405150000, 193 rows, computed 2026-07-10). Has NEVER cleared a formal A/B win against ic_proportional; status stays candidate until the registry gate is earned (the deployed-vs-proven distinction is exactly what this registry exists to keep honest).

### e2_mean_variance

- thesis (annotation of 2026-07-14): IC-proportional weighting ignores feature covariance and so over-allocates to correlated clusters. Mean-variance combination (inverse shrunk covariance times the shrunk IC vector) is the portfolio-theoretic optimum under Gaussian assumptions, with a condition-number cap (alpha.ensemble.mv_condition_max) guarding ill-conditioned covariance inversions.
- implementation (annotation of 2026-07-14): src/intelligence/ensemble/weights.py::mean_variance_weights over src/intelligence/ensemble/covariance.py::compute_shrinkage_covariance (Ledoit-Wolf); selected by alpha.ensemble.weight_method=mean_variance; falls back to ic_proportional when the condition number exceeds alpha.ensemble.mv_condition_max (method_used=mean_variance_fallback).
- observation (annotation of 2026-07-14): 2026-07-13: the 2026-07-09 A/B vs e1_shrunk_ic (challenger rows weight_version=run_2025122405150000_mv, 251 rows) returned 20/20 strata LOSS, but that result is INVALIDATED - both sides were all-long pre-todo-094 (sign-symmetric eligibility), so the comparison does not carry forward. Re-run sequenced in Phase 143.1 after components 094/097. No transition was or will be logged from the invalidated round.

### e3_hierarchical_pooling

- thesis (annotation of 2026-07-14): Per-stratum IC estimates share structure across tf and regime; hierarchical partial pooling (stratum estimates shrunk toward tf-level and global hyperpriors in proportion to within-stratum precision) should outperform flat shrinkage when strata are thin. No code exists; deferred at 142B.1 decision level.

### e4_decay_half_life

- thesis (annotation of 2026-07-14): Features decay at different rates; a per-feature IC decay half-life (estimated from each feature's own IC time series) should replace any single global staleness half-life when weighting historical evidence. No code exists; deferred at 142B.1 decision level.
- observation (annotation of 2026-07-14): 2026-07-13 conflation guard: the live alpha.ensemble.weight_half_life_days=30 key is a single GLOBAL staleness decay applied in services/ensemble_trainer.py - it is not E4 and its existence does not make E4 partially shipped.

## Known defects

E2's only A/B was invalidated (both sides all-long before todo 094); E1 became the deployed
default through an APR flip without a formal win; E3 and E4 were never built. The gate rows
never recorded a result.

## Why closed

The old ensemble chain (`ensemble_trainer`, `ensemble_weights`, `alpha_publisher`) was deleted
in phase 186 and the unified design (E18) replaces the weighting question with the combiner
battery and StepM selection, so these registry rows have no consumer. They are retired by plan
187-11, which retypes the construction domain and drops the `ensemble_strategy` domain after
this card (design 10.2.3). Verdict: no conclusion; no strategy earned or lost a formal
comparison.

## Where the numbers came from

Counts and annotation text read 2026-10-28 (read-only):

```sql
SELECT count(*) FROM concept_registry WHERE domain = 'ensemble_strategy';  -- 5
SELECT count(*) FROM concept_annotation a JOIN concept_registry c USING (concept_id)
  WHERE c.domain = 'ensemble_strategy';  -- 12
SELECT count(*) FROM concept_gate g JOIN concept_registry c USING (concept_id)
  WHERE c.domain = 'ensemble_strategy';  -- 5
SELECT count(*) FROM concept_transition_log t JOIN concept_registry c USING (concept_id)
  WHERE c.domain = 'ensemble_strategy';  -- 1
```

The full rows are also dumped to `data/backups/187-11/` before the drop.
