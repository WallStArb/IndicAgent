# Unified Concept Registry (UCR)

**Canonical name:** Unified Concept Registry (UCR)
**Informal aliases:** "Concept Registry," "the concept tables" (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current for architecture/mechanics — MVP live since 2026-07-13 (`ensemble_strategy` domain). The `feature` domain migration (Phase 170) is **COMPLETE** (2026-08-10, migration 311): `feature_registry`/`feature_transition_log` were DROPped and `FeatureRegistryService` deleted — `concept_registry` is the sole feature-lifecycle system, no parallel table remains. Both domains live: `concept_registry` holds 300 `feature`-domain rows (298 `FeatureVector` fields + 2 orphan tombstones from migration 284) and 5 `ensemble_strategy` rows, verified 2026-08-15 — re-verify row counts before citing them further out, this count moves as new features are added (most recently todo 320, migration 316).
**Phase introduced:** 160 (MVP, four tables), extended Phase 170 (feature-domain schema gaps: `concept_parent`, cascade trigger, cycle guard, control/group columns, shadow-recovery counters)
**Last Updated:** 2026-08-15

---

## What It Is

The **Unified Concept Registry (UCR)** is the system-wide home for evidence-gated lifecycle governance of research artifacts — features, ensemble weighting strategies, and (eventually) other recipe-shaped candidates like HMM variants or confluence patterns. It answers a different question than APR or ITR: not "what value should this parameter hold" or "what is this instrument," but **"does this recipe deserve to keep running, based on what it has actually proven."**

UCR governs **recipes, not their outputs.** A feature definition is governed here; a bar's computed feature value in `feature_vectors` is a fact table, untouched by this system. An `ensemble_strategy` concept is governed here; the ensemble weights it produces live in `ensemble_weights`, a separate fact table. This separation is load-bearing — conflating "is this recipe valid" with "what did this recipe compute" is exactly the confusion this registry exists to prevent.

Every concept moves through the same four-state lifecycle, proven or disproven by a deterministic evaluation engine that no proposer — human or AI — can short-circuit:

```
candidate → shadow_only → active → deprecated
```

### Relationship to APR, ITR, CVR

Fourth sibling under [Concept Governance Registries](../research/concept-governance-registries.md), governing yet another kind of knowledge:

- **APR** — tunable *numbers*.
- **ITR** — falsifiable *classification claims* about instruments.
- **CVR** — fixed *symbolic definitions*.
- **UCR** — evidence-gated *lifecycle status* of research artifacts (does this recipe still earn its place).

UCR is the only one of the four with a governance-vs-knowledge split baked into its own schema: `concept_registry`/`concept_gate`/`concept_transition_log` prove things (**the gate proves**); `concept_annotation` explains them (**the annotation explains**). This split is enforced structurally, not by convention — see Invariant 1 below.

---

## Infrastructure

Five tables (MVP + Phase 170 additions), two DB-level triggers, one service (`ConceptRegistryService`) with two call surfaces (async and sync). No dashboard; `scripts/ops/alpha/ops_concept_registry_override.py` is the operator CLI.
<!-- src: production/migrations/225_concept_registry_mvp.sql, 283_concept_registry_feature_domain_schema.sql, 284_concept_registry_feature_domain_seed.sql -->

### Table Schemas

**`concept_registry`** — identity and current status. Changes almost never outside a lifecycle transition.

| Column | Type | Description |
|--------|------|--------------|
| `concept_id` | UUID PRIMARY KEY | |
| `domain` | TEXT NOT NULL, CHECK | `'feature'` or `'ensemble_strategy'` today — see Domains below |
| `name` | TEXT NOT NULL | Unique within `(domain, name)` |
| `description` | TEXT NOT NULL | |
| `status` | TEXT NOT NULL DEFAULT `'candidate'`, CHECK | `candidate` / `shadow_only` / `active` / `deprecated` |
| `enabled` | BOOLEAN NOT NULL DEFAULT false | Maintained as `(status = 'active')` by the sync CAS transition path |
| `parent_concept_id` | UUID, self-FK | Single-parent lineage (legacy shape; `ensemble_strategy` may still use it) |
| `redundancy_group` | TEXT | Displacement disabled for `ensemble_strategy` — competing strategies are the normal state, resolved per-stratum |
| `is_control` / `control_expectation` | BOOLEAN / TEXT, CHECK | Control-canary marking (ported from `feature_registry`, Phase 170 L-10); `control_expectation ∈ {negative_control, positive_control}` |
| `group_name` | TEXT (unconstrained) | Peer-group label, read by real `WHERE` filters in `ops_ic_shrinkage.py`/`ops_ensemble_ablation.py`/`ops_broadcast_feature_audit.py` — not decorative |
| `metadata` | JSONB | Domain-specific fields (e.g. `feature` domain's `tier`) |
| `added_phase`, `sensitivity` | TEXT | |
| `created_at` | TIMESTAMPTZ | |

**`concept_parent`** — multi-parent lineage join table (Phase 170, L-8), superseding `feature_registry.parent_features`' unenforced `TEXT[]`.

| Column | Type | Description |
|--------|------|--------------|
| `child_concept_id`, `parent_concept_id` | UUID, FK both sides | PK `(child, parent)`; CHECK rejects self-edges |
| `created_at` | TIMESTAMPTZ | |

No ordinality column — no live consumer depends on parent order. A `BEFORE INSERT OR UPDATE` trigger (`fn_concept_parent_cycle_guard`) rejects any edge that would create a cycle, required because the cascade-deprecation trigger below recurses across this same table. **Known concurrency limit:** the cycle check reads only committed edges — two concurrent transactions each inserting one leg of a two-edge cycle can both pass. Not closed, because `concept_parent`'s only writer today is a single-transaction migration seed; any future runtime writer must take an advisory lock first (documented in the trigger's own comment).

**`concept_gate`** — per-concept promotion/demotion gate, with the eval-state cache folded in (MVP simplification vs. the ten-table reference architecture).

| Column | Type | Description |
|--------|------|--------------|
| `concept_id` | UUID PRIMARY KEY, FK | |
| `gate_metric_name`, `gate_eval_method` | TEXT, CHECK | `gate_eval_method ∈ {oos_holdout, walk_forward, bootstrap_ci}` |
| `min_gate_metric`, `min_gate_n`, `min_promotion_consecutive`, `min_new_observations` | numeric | `NULL` inherits the per-domain APR default (`alpha.concept_registry.<domain>_*`) |
| `demotion_threshold`, `decay_floor`, `regime_scope` | numeric/TEXT | |
| `fdr_required`, `fdr_alpha` | BOOLEAN, numeric | **Advisory only** — `ConceptRegistryService` reads `fdr_required` to fail-closed-gate promotions (see Invariants), but BH-FDR correction itself is computed entirely upstream by the caller (`ops_ensemble_weight_compare.py`), never inside this service |
| `last_eval_metric`, `last_eval_n`, `last_eval_at`, `last_eval_corpus_build_ref` | | Folded eval-state cache |
| `baseline_metric` | numeric | The **mean** of `promotion_eval_metrics` at promotion time — never the final (selection-inflated) value (winner's-curse guard) |
| `promotion_consecutive`, `promotion_eval_metrics` | INT, numeric[] | Running win streak and its per-round metrics |
| `consecutive_shadow_passes`, `observations_since_demotion` | INT, BIGINT | Phase 170 L-5 recovery counters, ported from `feature_registry` — gate `shadow_only → active` re-promotion after a decay |

**`concept_transition_log`** — immutable append-only audit trail, TimescaleDB hypertable on `triggered_at` (3-month chunks).

| Column | Type | Description |
|--------|------|--------------|
| `id`, `triggered_at` | BIGSERIAL, TIMESTAMPTZ | Composite PK `(id, triggered_at)` — hypertable partition column must be in the PK |
| `concept_id`, `domain`, `name` | | |
| `from_status`, `to_status` | TEXT NOT NULL | |
| `trigger_reason` | TEXT NOT NULL, CHECK | `promotion` / `demotion_performance` / `demotion_decay` / `demotion_redundancy` / `operator_override` / `parent_cascade` / `candidate_timeout` / `implementation_change` / `genesis_seed` |
| `corpus_build_ref` | TEXT | The CorpusManifest identity the deciding evaluation read from — Invariant 2's re-evaluation guard compares against this |
| `gate_metric`, `gate_n`, `ci_lower`, `decay_ratio`, `regime_scope`, `notes` | | |

**`concept_annotation`** — the knowledge layer. Never read by any gate decision; never required for a promotion.

| Column | Type | Description |
|--------|------|--------------|
| `annotation_id` | UUID PRIMARY KEY | |
| `concept_id` | UUID NOT NULL, FK | |
| `annotation_type` | TEXT, CHECK | `thesis` / `assumption` / `failure_mode` / `observation` / `open_question` / `implementation` / `reference` |
| `content` | TEXT NOT NULL | |
| `source` | TEXT, CHECK | `human` / `ai` / `empirical` |
| `confidence` | FLOAT `[0,1]` | |
| `valid_from`, `valid_to` | TIMESTAMPTZ | |

**Deliberately NOT built** (reference-architecture-only, per the design doc's own "do not build the ten-table version" ruling): `concept_gate_template`, `concept_gate_stack`, `concept_eval_run`, `concept_eval_state` (folded into `concept_gate`), `concept_dependency`, `concept_regime_ic`, `concept_correlation`. All nine invariants below apply to the five-table live shape without needing any of these.

### Cascade-deprecation trigger

`fn_cascade_concept_parent_deprecation()` (`AFTER UPDATE OF status`) — when a concept transitions to `deprecated`, every child in `concept_parent` cascades to `deprecated` too, recursively (safe only because the cycle guard above guarantees an acyclic graph). Two bugs from the `feature_registry` original this generalizes were fixed, not carried forward: the audit-log `INSERT` now runs **before** the cascading `UPDATE` (logging after would find every child already deprecated and silently select zero rows), and `from_status` is read as the child's **real** current status, never hardcoded to `'active'`.

---

## The Nine Invariants

These are the stable mechanics — the part of this design meant to survive unchanged regardless of which domain or how many rows are in play. Full reasoning: `docs/research/concept-unified-registry.md` §"Promotion/Demotion Design for Autonomous Self-Improvement".

1. **Proposal and decision are structurally different roles.** An agent (human or AI) may create a `candidate` row and write a `thesis` annotation. It may never write `status` directly. Only the deterministic evaluation engine — no LLM in the path — flips status. No code path both writes annotation content and flips status in the same call. **Exempt: migration-time genesis seeding.** A migration adding a new `FeatureVector` field may INSERT its corresponding `concept_registry` row with `status='active'` directly — this is schema-definition-time DDL establishing a new concept's existence, not a runtime lifecycle transition on an existing row, and isn't something the evaluation engine is meant to govern. Established, repeated practice across 5 migrations (288/289/290/291/316), all four pre-316 sourcing `status` from `feature_registry.status` (itself hardcoded `'active'` at INSERT before migration 311 dropped that table).
2. **Re-evaluation consumes new evidence, never re-rolls the same dice.** A concept may not be re-evaluated until `≥ min_new_observations` new independent observations have accrued since its last evaluation. Corpus-advance alone (a new `corpus_build_ref`) is necessary but insufficient — this project's corpus rebuilds run on mostly-overlapping windows.
3. **Proposal volume has a budget.** `alpha.concept_registry.max_ai_candidates_per_period` caps new AI-sourced `candidate` rows per domain per period, enforced at the service layer.
4. **The proposer's own track record is tracked for free.** `concept_annotation.source` (human/ai/empirical) on every thesis lets a hit-rate query answer "is this proposer's idea generation any good" with no new table.
5. **Demotion is engine-only, same as promotion, opposite direction.** No override path through the proposer. `decay_ratio` (measured against the winner's-curse-guarded `baseline_metric`) is domain-agnostic infrastructure, not a domain of its own.
6. **`shadow_only` is mandatory between `candidate` and `active`** for proposer-driven or backtested-only domains — non-negotiable for AI-sourced concepts. **Two documented exceptions exist today**, each required to justify why its gate already substitutes for live observation:
   - `domain='feature'` — hand-engineered, not proposer-driven; the walk-forward IC gate's OOS folds already serve the equivalent evidentiary function.
   - `domain='ensemble_strategy'` — human-authored E1-E4 candidates; the OOS A/B judged by `EnsembleICEngine` (non-overlapping-CI win rule, `walk_forward_stable` veto, BH-FDR across strata) substitutes. This is why `ensemble_strategy` promotes `candidate → active` directly.
7. **Initial promotion requires an effective-N minimum observation floor, regardless of significance.** A concept clearing `p < 0.05` on 50 bars is a fluke, not proof. The floor is stated against *effective* N (independent observations), never raw overlapping bars — the same independence discipline the IC engine already applies elsewhere in this codebase.
8. **Evidence is bound to the implementation version that produced it.** If the underlying computation silently changes after promotion, accumulated evidence no longer describes what's running. A version change resets promotion evidence and re-enters evaluation (`trigger_reason='implementation_change'`).
9. **Status transitions are compare-and-swap, in one transaction.** `UPDATE concept_registry SET status = :to WHERE concept_id = :id AND status = :from` — zero rows matched aborts the whole transaction, including the transition-log insert. Prevents two racing evaluators from logging a transition whose `from_status` never actually matched.

---

## `ConceptRegistryService` — two call surfaces

`src/intelligence/concept_registry_service.py`. Stateless on the async side; the sync side keeps an in-memory per-domain cache (`load_sync`) because its caller has no running event loop.

### Async path — `record_comparison_outcome()`

The **sole** status-flipping code path for `domain='ensemble_strategy'` (Invariant 1's deterministic engine, concretely). Called by `scripts/ops/alpha/ops_ensemble_weight_compare.py` after its own BH-FDR-corrected win decision. Runs read-decide-write inside one transaction with `FOR UPDATE` held throughout, so a concurrent evaluator for the same concept blocks rather than racing. Possible outcomes: `promote` (CAS `candidate→active`), `record_win`/`record_win_not_promotable`/`record_loss` (eval-cache bookkeeping only), or one of several `blocked_*`/`noop_*` results that write nothing — including `blocked_fdr_unverified`, which fails closed whenever `concept_gate.fdr_required=true` and the caller cannot prove FDR correction actually ran this round.

### Sync path — `record_transition_sync()` / `advance_shadow_counters_sync()` / `is_promotion_eligible()`

Used by `ic_engine.py` and `ensemble_trainer.py`, both psycopg-based with no running event loop. `record_transition_sync` is the CAS-guarded general transition writer (any domain, any `trigger_reason`) — refuses automated callers targeting `deprecated` (operator-only), validates `trigger_reason` against the CHECK vocabulary in Python before hitting Postgres, and resets the shadow-recovery counters whenever a transition lands on `shadow_only` (without this, a concept that previously earned recovery would re-promote off a single passing run instead of re-earning the full evidence bar). `advance_shadow_counters_sync` is the only other counter-mutation path — increments/resets `consecutive_shadow_passes` and accumulates `observations_since_demotion` after each corpus run. `is_promotion_eligible` is a pure evidence-only predicate (no calendar/date input) over those two counters.

---

## Domains

| Domain | Status | Gate metric | Min observation floor |
|--------|--------|--------------|------------------------|
| `ensemble_strategy` | **Live** — MVP seeded 2026-07-13, 5 concepts | Ensemble IC (`ic_ci_lower`, walk-forward stable) | 1,000 bars (per-TF fold) |
| `feature` | **Live** — Phase 170 migration complete 2026-08-10 (migration 311), 300 rows as of 2026-08-15 | IC Sharpe + FDR, walk-forward | 20,000 bars |
| `feature_interaction`, `hmm_variant`, `ic_method`, `regime_model`, `confluence` | Anticipated, not in the `domain` CHECK yet | — | — |
| `alpha_pattern` | **Retired**, not anticipated | — | Its scope was fully absorbed by `feature_interaction` (dense deterministic transforms), `confluence` (sparse conditional predictors), and `feature`-grain retrieval columns — nothing left for it to govern |

A domain is added to the live `domain` CHECK only once it has real candidates — never pre-seeded "reserved, pending definition." Full per-domain gate design and vetting reasoning (why `ic_method` currently has no governable scope, `regime_model`'s open row-grain question, `confluence`'s six-gate stack): `docs/research/concept-unified-registry.md` §Domains, §Domain Vetting.

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|-----------------|-----|
| A recipe's computed output (a bar's feature value, an ensemble's emitted weights) | The domain's own fact table (`feature_vectors`, `ensemble_weights`) | UCR governs the recipe, not its results |
| Tunable numeric values, including UCR's own gate defaults | APR (`config_state`, `alpha.concept_registry.*`) | UCR consumes APR, doesn't duplicate it |
| Falsifiable instrument classification | ITR | Different subject entirely — instruments, not research artifacts |
| Fixed symbolic code definitions | CVR | Different epistemic kind of row (definitional vs. evidence-gated) |
| Measured tag assignments (ITR's `instrument_tags`) | Explicitly **not** a UCR domain | A tag assignment is a fact about an instrument, not a recipe with a lifecycle — the two systems' invariants don't transfer |

---

## Migration History

The `feature` domain migrated from the pre-existing, separate `feature_registry`/`feature_transition_log` sibling system under **ROADMAP Phase 170**, complete 2026-08-10 (migration 311): both predecessor tables were DROPped (no rename-and-archive — an explicit 2026-08-04 user override of this project's usual retirement default, since `feature_registry` is governance/bookkeeping metadata, not something gating live capital) and `FeatureRegistryService` deleted as dead code. `concept_registry` has been the sole feature-lifecycle system, with no parallel table, since that date. Full migration record: `.planning/todos/completed/118-migrate-feature-domain-into-concept-registry.md`, `production/migrations/283/284/310/311_*.sql`.

---

## Related Docs

- `docs/foundation/adaptive-parameter-registry.md`, `instrument-tag-registry.md`, `controlled-vocabulary-registry.md` — sibling registries this doc's structure mirrors.
- `docs/research/concept-unified-registry.md` — full design doc: complete Domains/Domain-Vetting sections, the ten-table reference architecture (not built), revision history, "What Jim Simons Would Demand" safeguards.
- `docs/research/concept-governance-registries.md` — Type 1/2/3 umbrella index across all four registries.
- `.planning/todos/completed/118-migrate-feature-domain-into-concept-registry.md` — Phase 170's full scope, now closed.
