# Concept Governance Registries

**Status:** Framework live — components at various stages of completion. Only APR (Type 1) and the separate sibling Feature Registry are actually built; Concept Registry (Type 2) and both Type 3 systems are design-complete but unbuilt.
**Type:** Umbrella index — links to canonical docs for each registry type
**Last Updated:** 2026-07-06 (corrected against the canonical Concept Registry doc's 2026-07-06 Fable rigor pass; this index had drifted: cited a `concept_domains` table that was never designed, was missing `concept_gate` from the real four-table MVP, carried a stale APR count, and didn't reflect Concept Registry's still-unbuilt status)

---

## What This Is

Concept Governance Registries is the overarching framework that unifies all runtime-governed system knowledge into three complementary types. Rather than scattered one-off tables and hardcoded constants, every tunable value, every research artifact, and every domain vocabulary lives in a structured registry with a clear lifecycle and audit trail.

**Three complementary types:**

| Type | What it governs | Canonical doc | Status |
|------|-----------------|--------------|--------|
| **Type 1 — Parameter** | Tunable numeric values (thresholds, weights, periods, preferences) | [APR](../foundation/adaptive-parameter-registry.md) | ✅ Live (425 params, 13 namespaces) |
| **Type 2 — Lifecycle** | Evidence-gated research artifacts (features, ensemble strategies, HMM variants, alpha patterns) | [Concept Registry](concept-unified-registry.md) | ✅ MVP live 2026-07-13 (todo 058, migrations 231/232): four tables + `ConceptRegistryService`, `ensemble_strategy` seeded (5 concepts). `feature` domain not yet migrated (todo 118). Feature Registry (a separate sibling system, not part of Concept Registry) is live with 61 rows |
| **Type 3 — Vocabulary** | Static taxonomies (tags, domain enums, controlled vocabularies) | See below | ⏳ Design complete, build pending |

---

## Type 1 — Adaptive Parameter Registry (APR)

**Purpose:** Runtime-tunable numeric values without code deployment.

- **Canonical doc:** `docs/foundation/adaptive-parameter-registry.md`
- **Status:** Live in production
- **Coverage:** 425 parameters across 13 namespaces (`threshold.*`, `weights.*`, `feature.*`, `regime.*`, `alpha.*`, `shadow.*`, `swarm.*`, `roll.*`, `ui.*`, `infra.*`, `signal.*`, `ml.*`, `ensemble.*`)
- **Infrastructure:** Four tables (`config_schema`, `config_state`, `config_history`, `config_outbox`) + `ConfigService`
- **Lifecycle:** `seed → user/operator → ml_learned → user_override → ml_learned_again`

**What lives here:** Detection thresholds, indicator periods, confidence weights, governance gates, dashboard preferences. Any value a human or ML might want to change at runtime.

**What does NOT live here:** DAG topology, table schemas, mathematical constants, numbers that define statistical concepts (e.g., the "5" in `momentum_z_5`).

---

## Type 2 — Lifecycle Registries (Concept Registry)

**Purpose:** Evidence-gated promotion/demotion of research artifacts.

- **Canonical doc:** `docs/research/concept-unified-registry.md`
- **Status:** Feature Registry (separate sibling system) live (61 features); Concept Registry MVP live 2026-07-13 (todo 058, migrations 231/232), `ensemble_strategy` seeded; `feature` migration pending (todo 118)
- **Domains seeded at build time (only domains with real candidates as of 2026-07-06):** `feature`, `ensemble_strategy`. The rest (`hmm_variant`, `ic_method`, `regime_model`, `alpha_pattern`, `confluence`) are anticipated shapes, added by migration only once each has real candidates; see the canonical doc's Domains table for per-domain status
- **Infrastructure:** Four-table MVP (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`) + `ConceptRegistryService`
- **Lifecycle:** `candidate → shadow_only → active → deprecated` with statistical gates (p < 0.05, minimum observation floors stated against effective N, not raw bar count)

**What lives here:** Recipes, not their outputs. A feature definition is governed; a bar's feature value in `feature_vectors` is a fact table. An alpha_pattern strategy is governed; the emitted `alpha_events` are a fact table.

**Legacy — Shadow Registry (v2.x):** 36 I1-I7 plugins/swarm agents, archived, not migrating to v3.0.

---

## Type 3 — Vocabulary Registries

**Purpose:** Static taxonomies and controlled vocabularies.

Two related systems:

### 3a — Instrument Tag Vocabulary

**Purpose:** Empirically-derived instrument tags (risk_on, rate_sensitive, defensive, etc.)

- **Canonical doc:** `docs/research/stratification-instrument-tag-calibrator.md`
- **Status:** Draft design
- **Coverage:** 71 tags / 410 instrument assignments
- **Primitives:** 8 measurable betas (equity, rate, gold, credit, dollar, vol, oil, china) + information-theoretic measures (lead_lag, regime_mi, asymmetric betas, hurst, autocorrelation, vol_of_vol, skewness, beta_stability)

### 3b — Controlled Vocabulary

**Purpose:** Domain enums and code vocabularies (signal_outcome, entry_type, regime labels, timeframes, etc.)

- **Canonical doc:** `docs/research/concept-controlled-vocabulary.md`
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
| Feature Registry (separate sibling system, not part of Concept Registry) | 1 live | Integrated in `ensemble_trainer.py` | ✅ Shipped (61 rows) |
| Concept Registry (full Type 2) | 4 live (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`) | `ConceptRegistryService` (live, `src/intelligence/concept_registry_service.py`) | ✅ MVP shipped 2026-07-13 (todo 058, migrations 231/232); `ensemble_strategy` seeded, `feature` migration pending (todo 118) |
| Tag Vocabulary | 3 designed | `TagCalibratorService` (designed) | ⏳ Build pending |
| Controlled Vocabulary | 3 designed | `VocabularyService` (designed) | ⏳ Build pending |

---

## Related Docs

- **Sibling umbrella (stratification/classification cluster):** `docs/research/stratification-governance-registries.md` — StratificationDimension, Security Classification Hierarchy, Instrument Tag Calibrator. Different question (what state/kind an instrument or market is in, vs. what values are tuned or what artifacts earned promotion), one real seam via Concept Registry's `regime_model`/`hmm_variant` domains.
- **Renaissance framing:** `docs/foundation/principles.md` — institutional-grade research discipline
- **APR detail:** `docs/foundation/adaptive-parameter-registry.md` — full spec, namespace convention, access patterns
- **Concept Registry detail:** `docs/research/concept-unified-registry.md` — Renaissance safeguards, Domains table, invariants
- **Tag Vocabulary detail:** `docs/research/stratification-instrument-tag-calibrator.md` — factor primitives, derivability, Simons critique
- **Controlled Vocabulary detail:** `docs/research/concept-controlled-vocabulary.md` — namespace list, groupings, enum enforcement
- **Roadmap context:** `docs/research/roadmap-scope-map.md` §2 (Governance / Concept Lifecycle)
