# Concept Governance Registries

**Status:** Framework live. All four parts now have foundation-level architecture docs (APR, ITR, CVR, UCR). Concept Registry (Type 2 / UCR) is MVP-live and its stable mechanics (schema, invariants, service) are documented, but its `feature`-domain migration is actively in progress under a separate concurrent session (ROADMAP Phase 170, per `.planning/STATE.md`) as of this update — any row-count or domain-completeness claim about `feature` is a known-stale snapshot; do not treat it as current until Phase 170 closes.
**Type:** Umbrella index — links to canonical docs for each registry type
**Last Updated:** 2026-08-08 (Type 3 entries corrected — both 3a Instrument Tag Vocabulary and 3b Controlled Vocabulary had drifted badly: this index still called them "draft design"/"build unscheduled" months after Phase 146 and Phase 161 shipped them live, complete with running services. Promoted both to `docs/foundation/` — see `instrument-tag-registry.md` and `controlled-vocabulary-registry.md`. Type 2 (Concept Registry) also promoted to `docs/foundation/unified-concept-registry.md` — its stable architecture (schema, 9 invariants, service mechanics) doesn't change with Phase 170's progress even though `feature`-domain completeness numbers do; the new doc carries that caveat inline.)

---

## What This Is

Concept Governance Registries is the overarching framework that unifies all runtime-governed system knowledge into three complementary types. Rather than scattered one-off tables and hardcoded constants, every tunable value, every research artifact, and every domain vocabulary lives in a structured registry with a clear lifecycle and audit trail.

**Three complementary types:**

| Type | What it governs | Canonical doc | Status |
|------|-----------------|--------------|--------|
| **Type 1 — Parameter** | Tunable numeric values (thresholds, weights, periods, preferences) | [APR](../foundation/adaptive-parameter-registry.md) | ✅ Live (425 params, 13 namespaces) |
| **Type 2 — Lifecycle** | Evidence-gated research artifacts (features, ensemble strategies, HMM variants, alpha patterns) | [Unified Concept Registry (UCR)](../foundation/unified-concept-registry.md) | ✅ Architecture live (5 tables + `ConceptRegistryService`), `ensemble_strategy` domain fully live. ⏳ `feature` domain migration in progress (Phase 170) — `feature_registry` (separate sibling system) still exists and is still authoritative; do not cite row counts for either until Phase 170 closes |
| **Type 3 — Vocabulary** | Static taxonomies (tags, domain enums, controlled vocabularies) | See below | ✅ Live — both 3a and 3b shipped |

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

## Type 2 — Lifecycle Registries (Unified Concept Registry, UCR)

**Purpose:** Evidence-gated promotion/demotion of research artifacts.

- **Canonical doc:** `docs/foundation/unified-concept-registry.md` (full design reference, domain vetting, reference architecture: `docs/research/concept-unified-registry.md` — still live/active, not design history, since Phase 170 builds against it)
- **Status:** MVP live 2026-07-13 (todo 058, migrations 231/232), `ensemble_strategy` domain fully live (5 concepts). `feature`-domain migration actively in progress under Phase 170 (todo 118) — `feature_registry` (separate sibling system) still exists and is still authoritative; check `.planning/STATE.md` before citing either system's row counts
- **Domains seeded at build time (only domains with real candidates as of 2026-07-06):** `feature`, `ensemble_strategy`. The rest (`hmm_variant`, `ic_method`, `regime_model`, `alpha_pattern`, `confluence`) are anticipated shapes, added by migration only once each has real candidates; see the canonical doc's Domains table for per-domain status
- **Infrastructure:** Four-table MVP (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`) + `ConceptRegistryService`
- **Lifecycle:** `candidate → shadow_only → active → deprecated` with statistical gates (p < 0.05, minimum observation floors stated against effective N, not raw bar count)

**What lives here:** Recipes, not their outputs. A feature definition is governed; a bar's feature value in `feature_vectors` is a fact table. An alpha_pattern strategy is governed; the emitted `alpha_events` are a fact table.

**Legacy — Shadow Registry (v2.x):** 36 I1-I7 plugins/swarm agents, archived, not migrating to v3.0.

---

## Type 3 — Vocabulary Registries

**Purpose:** Static taxonomies and controlled vocabularies.

Two related systems:

### 3a — Instrument Tag Registry (ITR)

**Purpose:** Empirically-derived, falsifiable instrument tags (risk_on, rate_sensitive, defensive, etc.)

- **Canonical doc:** `docs/foundation/instrument-tag-registry.md` (Phase 146 design history: `docs/research/stratification-instrument-tag-calibrator.md`)
- **Status:** ✅ Live — Phase 146 shipped complete 2026-07-17, `TagCalibrator` running
- **Coverage:** 74 tags / ~1,235 instrument assignments (724 human, 511 empirical), verified live 2026-08-08
- **Measurement:** OLS beta regression vs. `factor_series` proxy, HAC p-value, run-level BH-FDR, hysteresis-gated expiry — see canonical doc for the 3-pass engine

### 3b — Controlled Vocabulary Registry (CVR)

**Purpose:** Domain enums and code vocabularies (regime labels, timeframes, asset classes, etc.)

- **Canonical doc:** `docs/foundation/controlled-vocabulary-registry.md` (Phase 161 design history: `docs/research/concept-controlled-vocabulary.md`)
- **Status:** ✅ Live — Phase 161 shipped complete 2026-07-18
- **Coverage:** 6 live namespaces (`regime_hmm`, `regime_cross_sectional_equity`, `regime_cross_sectional_rates`, `timeframe`, `asset_class`, `tier`) — archived-SLA namespaces (`signal_outcome`, `entry_type`, `signal_status`, `session_type`) deliberately not seeded, no live consumer
- **Infrastructure:** Three tables (`controlled_vocabulary`, `vocabulary_group`, `vocabulary_group_member`) + `VocabularyService` (cached read projection) + `VocabularyDriftAuditor` (chained into `ops_corpus_pipeline_run.sh`, flags live columns emitting unregistered codes)

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

**Independence:** The three types are independently valuable. APR can exist without Concept Registry. ITR and CVR can each exist without Concept Registry. They are siblings, not dependencies.

**Unification benefit:** When all three are live, the system has a single, queryable source of truth for:
- What parameters are active and why (APR + `config_history`)
- Which research artifacts earned promotion and with what evidence (Concept Registry + `concept_transition_log`)
- What instrument tags apply and how they were calibrated (ITR + factor primitives)
- What domain codes are valid and what they mean (CVR)

---

## Implementation Status

| Component | Tables | Service | Status |
|-----------|--------|---------|--------|
| APR | 4 live | `ConfigService` | ✅ Shipped |
| Feature Registry (separate sibling system, not part of Concept Registry) | 1 live | Integrated in `ensemble_trainer.py` | ⚠️ Live but on a confirmed retirement path — being migrated into Concept Registry's `feature` domain under Phase 170 (concurrent, in progress as of 2026-08-08). Do not cite a row count here; it's moving. |
| Unified Concept Registry (full Type 2, UCR) | 5 live (`concept_registry`, `concept_gate`, `concept_transition_log`, `concept_annotation`, `concept_parent`) | `ConceptRegistryService` (live, `src/intelligence/concept_registry_service.py`) | ✅ MVP shipped 2026-07-13 (todo 058, migrations 231/232); `ensemble_strategy` seeded. Architecture documented: `docs/foundation/unified-concept-registry.md`. `feature`-domain migration actively in progress under Phase 170 (concurrent session) — do not cite specific numbers here until it closes; check `.planning/STATE.md` for current status. |
| Instrument Tag Registry (ITR) | 3 live | `TagCalibrator` (`services/tag_calibrator.py`) | ✅ Shipped (Phase 146, 2026-07-17) — see `docs/foundation/instrument-tag-registry.md` |
| Controlled Vocabulary Registry (CVR) | 3 live | `VocabularyService` + `VocabularyDriftAuditor` | ✅ Shipped (Phase 161, 2026-07-18) — see `docs/foundation/controlled-vocabulary-registry.md` |

---

## Related Docs

- **Sibling umbrella (stratification/classification cluster):** `docs/research/stratification-governance-registries.md` — StratificationDimension, Security Classification Hierarchy, Instrument Tag Calibrator. Different question (what state/kind an instrument or market is in, vs. what values are tuned or what artifacts earned promotion), one real seam via Concept Registry's `regime_model`/`hmm_variant` domains.
- **Renaissance framing:** `docs/foundation/principles.md` — institutional-grade research discipline
- **APR detail:** `docs/foundation/adaptive-parameter-registry.md` — full spec, namespace convention, access patterns
- **UCR detail:** `docs/foundation/unified-concept-registry.md` — schema, 9 invariants, service mechanics (full design reference/domain vetting: `docs/research/concept-unified-registry.md`)
- **ITR detail:** `docs/foundation/instrument-tag-registry.md` — schema, TagCalibrator's 3-pass engine, consumers, known gaps (design history: `docs/research/stratification-instrument-tag-calibrator.md`)
- **CVR detail:** `docs/foundation/controlled-vocabulary-registry.md` — schema, VocabularyService, drift auditor (design history: `docs/research/concept-controlled-vocabulary.md`)
- **Roadmap context:** `docs/research/roadmap-scope-map.md` §2 (Governance / Concept Lifecycle)
