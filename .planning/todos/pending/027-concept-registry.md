---
created: 2026-06-28
priority: low
phase_target: Phase C+ (v3.0, after alpha_events pipeline stabilizes)
tags: [architecture, registry, governance, knowledge, research, alpha, hmm, ensemble]
---

# Concept Registry — Governance + Knowledge System for Research Concepts

## What

Build a seven-table system across two layers that governs every evidence-gated research domain and preserves the institutional knowledge behind each concept. Absorbs Feature Registry at build time.

Full design: `docs/ideas/metadata-governance-registries.md`

## Two layers, seven tables

```
GOVERNANCE LAYER
  concept_registry       — identity, status, lineage (parent_concept_id), redundancy_group
  concept_gate           — what it needs to prove: OOS eval method, regime scope,
                           sustained promotion threshold, decay floor
  concept_eval_state     — evaluation engine working memory (overwritten each cycle)
  concept_transition_log — immutable state-change audit trail with trigger_reason

KNOWLEDGE LAYER
  concept_annotation     — versioned knowledge: thesis, assumptions, failure modes,
                           observations, open questions, implementation notes, references
  concept_dependency     — directed graph: uses_feature, extends, competes_with, requires_method
  concept_regime_ic      — full regime-stratified IC matrix (evaluation engine writes every cycle)
```

## Key design decisions

**Governance:**
- `gate_eval_method` required on every gate — `oos_holdout`, `walk_forward`, `bootstrap_ci`; in-sample never valid
- `min_promotion_consecutive` — N consecutive evals above threshold before promotion fires (default 3)
- `regime_scope` — gate can be conditional on a specific regime label; regime-conditional edges are real edges
- `baseline_metric` + `decay_ratio` + `decay_floor` — decay demotion fires immediately when current/baseline drops below floor, without waiting for consecutive periods
- `parent_concept_id` — lineage tree; concept iterations reference their predecessor
- `redundancy_group` — concepts in same group compete; only one holds `active` at a time

**Knowledge:**
- `concept_annotation` is append-only and typed: `thesis` (why it works), `assumption` (what must hold), `failure_mode` (when it breaks), `observation` (post-deployment learning), `open_question` (unresolved), `implementation` (code path), `reference` (papers/docs)
- `source` on each annotation: `human`, `ai`, or `empirical` (evaluation engine auto-generates empirical annotations — e.g. IC correlation findings)
- `concept_dependency` enables impact analysis: "what breaks if feature X is deprecated?" and blocks promotion of a concept whose `uses_feature` dependency is still `candidate`
- `concept_regime_ic` is richer than `regime_scope`: a concept with unconditional gate still has a regime profile the ensemble uses for weighting (regime-conditional weighting and regime-conditional governance are separate concerns)

## Domains

| Domain | Gate metric | Eval method |
|---|---|---|
| `feature` | IC Sharpe + FDR | Walk-forward |
| `feature_interaction` | IC Sharpe + FDR | Walk-forward |
| `alpha_pattern` | IC Sharpe | OOS holdout |
| `hmm_variant` | Held-out log-likelihood | OOS holdout |
| `ic_method` | Walk-forward IC stability | Walk-forward |
| `ensemble_strategy` | Realized Sharpe | OOS holdout |
| `regime_model` | Cross-validated accuracy | Walk-forward |

## Replaces Feature Registry

`feature_registry` migrates into `domain = 'feature'` at build time. `FeatureRegistryService` becomes `ConceptRegistryService`. Domain-specific logic (dataclass alignment gate, parent-cascade) moves to the service layer. Metadata columns move to `metadata JSONB`.

## Build sequence

1. Governance layer + feature_registry migration
2. Seed `thesis` and `failure_mode` annotations for all 61 migrated features
3. `concept_regime_ic` — evaluation engine writes from day one
4. `concept_annotation` full human/AI/empirical flow
5. `concept_dependency` with gate-time dependency checks
6. Dashboard: single concept view — governance status, annotation timeline, regime IC heatmap, dependency graph

## Dependency

Defer until `alpha_events` pipeline is stable and the first new domain (`alpha_pattern`) has concepts ready to govern. The design is complete.
