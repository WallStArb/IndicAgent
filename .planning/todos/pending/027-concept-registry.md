---
created: 2026-06-28
priority: low
phase_target: Phase C+ (v3.0, after alpha_events pipeline stabilizes)
tags: [architecture, registry, governance, research, alpha, hmm, ensemble]
---

# Concept Registry — Generalized Lifecycle Governance for Research Concepts

## What

Build a four-table generalized lifecycle registry for all evidence-gated concept domains that are not features. Formalizes the research pipeline: every hypothesis enters as `candidate`, runs in shadow, earns promotion through statistical gates or gets formally retired with evidence attached.

Full design: `docs/ideas/metadata-governance-registries.md` — Generalized Concept Registry section.

## Tables

```
concept_registry        — identity + status + lineage (parent_concept_id) + redundancy_group
concept_gate            — per-concept promotion/demotion parameters + OOS eval method + regime_scope
concept_eval_state      — latest evaluation snapshot (working memory, overwritten each cycle)
concept_transition_log  — immutable audit trail with trigger_reason distinguishing decay vs perf vs redundancy
```

Key design decisions beyond the basic four-table split:

- `gate_eval_method` is required — in-sample IC never valid; must be `oos_holdout`, `walk_forward`, or `bootstrap_ci`
- `min_promotion_consecutive` — N consecutive evals above threshold before promotion fires (default 3)
- `regime_scope` — gate can be regime-conditional; an edge that only works in trending regime is still a real edge
- `baseline_metric` + `decay_ratio` in eval_state — decay demotion fires when current/baseline drops below `decay_floor`
- `parent_concept_id` — lineage tree; iterations of a concept reference their parent
- `redundancy_group` — concepts in the same group compete; only one holds `active` at a time
- `ConceptRegistryService` lazy-loads candidates; active/shadow_only load eagerly at startup

## Domains (seed at build time)

| Domain | Gate metric | What it governs |
|---|---|---|
| `alpha_pattern` | IC Sharpe | Alpha signal ideas competing for ensemble inclusion |
| `hmm_variant` | Held-out log-likelihood | HMM architecture variants (covariance structure, obs vector, K) |
| `ic_method` | Walk-forward stability | IC calculation variants (Spearman vs rank-IC vs HAC-adjusted) |
| `ensemble_strategy` | Realized Sharpe | Ensemble weighting strategies |
| `regime_model` | Cross-validated accuracy | Regime classification model variants |
| `feature_interaction` | IC Sharpe + FDR | Interaction feature candidates before FeatureVector promotion |

## Why

Without this, model variants live in ad-hoc notebooks, failed experiments disappear into deleted branches, and the same dead ends get rediscovered. The transition log is the research ledger: a `deprecated` row with `ic_sharpe = 0.11, n = 1200` tells future research what was tried and ruled out — permanently, queryable from SQL.

The `enabled` flag makes parallel A/B comparison first-class: two `hmm_variant` rows both `enabled = true` in shadow, scored every eval cycle, promote on evidence.

## Replaces Feature Registry

`feature_registry` migrates into concept_registry as `domain = 'feature'` at build time. It is not architecturally distinct — its domain-specific logic (dataclass alignment gate, parent-cascade) moves to ConceptRegistryService for the `feature` domain. Its metadata columns (`formula_short`, `normalization`, `linear_ready`, etc.) move to `metadata JSONB` — ic_engine and ensemble_trainer load everything at startup into Python anyway, so there are no actual SQL consumers of those columns. `FeatureRegistryService` is replaced by `ConceptRegistryService` loading `domain = 'feature'`.

## Dependency

Defer until `alpha_events` pipeline is stable and the first domain (`alpha_pattern`) has concrete concepts ready to govern. The four-table schema is designed; implementation starts when there is a consumer.
