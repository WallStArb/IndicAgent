# Concept Governance Registries

**Status:** Framework live — components at various stages of completion
**Type:** Umbrella index — links to canonical docs for each registry type
**Last Updated:** 2026-07-06

---

## What This Is

Concept Governance Registries is the overarching framework that unifies all runtime-governed system knowledge into three complementary types. Rather than scattered one-off tables and hardcoded constants, every tunable value, every research artifact, and every domain vocabulary lives in a structured registry with a clear lifecycle and audit trail.

**Three complementary types:**

| Type | What it governs | Canonical doc | Status |
|------|-----------------|--------------|--------|
| **Type 1 — Parameter** | Tunable numeric values (thresholds, weights, periods, preferences) | [APR](../foundation/adaptive-parameter-registry.md) | ✅ Live (348 params, 13 namespaces) |
| **Type 2 — Lifecycle** | Evidence-gated research artifacts (features, ensemble strategies, HMM variants, alpha patterns) | [Concept Registry](platform-unified-concept-registry.md) | ✅ Design complete (Feature Registry live with 61 rows) |
| **Type 3 — Vocabulary** | Static taxonomies (tags, domain enums, controlled vocabularies) | See below | ⏳ Design complete, build pending |

---

## Type 1 — Adaptive Parameter Registry (APR)

**Purpose:** Runtime-tunable numeric values without code deployment.

- **Canonical doc:** `docs/foundation/adaptive-parameter-registry.md`
- **Status:** Live in production
- **Coverage:** 348 parameters across 13 namespaces (`threshold.*`, `weights.*`, `feature.*`, `regime.*`, `alpha.*`, `shadow.*`, `swarm.*`, `roll.*`, `ui.*`, `infra.*`, `signal.*`, `ml.*`, `ensemble.*`)
- **Infrastructure:** Four tables (`config_schema`, `config_state`, `config_history`, `config_outbox`) + `ConfigService`
- **Lifecycle:** `seed → user/operator → ml_learned → user_override → ml_learned_again`

**What lives here:** Detection thresholds, indicator periods, confidence weights, governance gates, dashboard preferences. Any value a human or ML might want to change at runtime.

**What does NOT live here:** DAG topology, table schemas, mathematical constants, numbers that define statistical concepts (e.g., the "5" in `momentum_z_5`).

---

## Type 2 — Lifecycle Registries (Concept Registry)

**Purpose:** Evidence-gated promotion/demotion of research artifacts.

- **Canonical doc:** `docs/ideas/platform-unified-concept-registry.md`
- **Status:** Feature Registry live (61 features); Concept Registry design complete; unified build pending
- **Domains:** `feature`, `ensemble_strategy`, `hmm_variant`, `ic_method`, `regime_model`, `alpha_pattern`, `confluence`
- **Infrastructure:** Four-table MVP (`concept_registry`, `concept_domains`, `concept_transition_log`, `concept_annotation`) + `ConceptRegistryService`
- **Lifecycle:** `candidate → shadow_only → active → deprecated` with statistical gates (p < 0.05, minimum observation floors)

**What lives here:** Recipes, not their outputs. A feature definition is governed; a bar's feature value in `feature_vectors` is a fact table. An alpha_pattern strategy is governed; the emitted `alpha_events` are a fact table.

**Legacy — Shadow Registry (v2.x):** 36 I1-I7 plugins/swarm agents, archived, not migrating to v3.0.

---

## Type 3 — Vocabulary Registries

**Purpose:** Static taxonomies and controlled vocabularies.

Two related systems:

### 3a — Instrument Tag Vocabulary

**Purpose:** Empirically-derived instrument tags (risk_on, rate_sensitive, defensive, etc.)

- **Canonical doc:** `docs/ideas/data-instrument-tag-calibrator.md`
- **Status:** Draft design
- **Coverage:** 71 tags / 410 instrument assignments
- **Primitives:** 8 measurable betas (equity, rate, gold, credit, dollar, vol, oil, china) + information-theoretic measures (lead_lag, regime_mi, asymmetric betas, hurst, autocorrelation, vol_of_vol, skewness, beta_stability)

### 3b — Controlled Vocabulary

**Purpose:** Domain enums and code vocabularies (signal_outcome, entry_type, regime labels, timeframes, etc.)

- **Canonical doc:** `docs/ideas/platform-controlled-vocabulary.md`
- **Status:** Design complete, build unscheduled
- **Coverage:** 10+ namespaces across signal_outcome, entry_type, regime_hmm, regime_cross_sectional, tier, timeframe, asset_class, session_type
- **Infrastructure:** Three tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`) + `VocabularyService`

---

## How the Three Types Relate

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Concept Governance Registries                        │
│                        (this umbrella doc)                             │
└─────────────────────────────────────────────────────────────────────────┘
         │                              │                           │
         ▼                              ▼                           ▼
    Type 1                        Type 2                     Type 3
   (APR)                        (Lifecycle)               (Vocabulary)
 ─────────────────────────────────────────────────────────────────────────
 Values you tune             Recipes you prove           Codes you query
 threshold.*                 feature, ensemble*          signal_outcome
 weights.*                   hmm_variant                 entry_type
 feature.*                   regime_model                regime_hmm
 alpha.*                     alpha_pattern              timeframe
```

**Independence:** The three types are independently valuable. APR can exist without Concept Registry. Tag Vocabulary can exist without Concept Registry. They are siblings, not dependencies.

**Unification benefit:** When all three are live, the system has a single, queryable source of truth for:
- What parameters are active and why (APR + `config_history`)
- Which research artifacts earned promotion and with what evidence (Concept Registry + `concept_transition_log`)
- What instrument tags apply and how they were calibrated (Tag Vocabulary + factor primitives)
- What domain codes are valid and what they mean (Controlled Vocabulary)

---

## Implementation Status

| Component | Tables | Service | Status |
|-----------|--------|---------|--------|
| APR | 4 live | `ConfigService` | ✅ Shipped |
| Feature Registry (Type 2 subset) | 1 live | Integrated in `ensemble_trainer.py` | ✅ Shipped (61 rows) |
| Concept Registry (full Type 2) | 4 designed | `ConceptRegistryService` (designed) | ⏳ Build pending |
| Tag Vocabulary | 3 designed | `TagCalibratorService` (designed) | ⏳ Build pending |
| Controlled Vocabulary | 3 designed | `VocabularyService` (designed) | ⏳ Build pending |

---

## Related Docs

- **Renaissance framing:** `docs/foundation/principles.md` — institutional-grade research discipline
- **APR detail:** `docs/foundation/adaptive-parameter-registry.md` — full spec, namespace convention, access patterns
- **Concept Registry detail:** `docs/ideas/platform-unified-concept-registry.md` — Renaissance safeguards, Domains table, invariants
- **Tag Vocabulary detail:** `docs/ideas/data-instrument-tag-calibrator.md` — factor primitives, derivability, Simons critique
- **Controlled Vocabulary detail:** `docs/ideas/platform-controlled-vocabulary.md` — namespace list, groupings, enum enforcement
- **Roadmap context:** `docs/ideas/roadmap-scope-map.md` §2 (Governance / Concept Lifecycle)
