# Unified Concept Registry (UCR)

**Canonical name:** Unified Concept Registry (UCR)
**Status:** template — pattern only, all examples are illustrative placeholders
**Source:** genericized from IndicAgent `docs/foundation/unified-concept-registry.md`

---

## What It Is

The **Unified Concept Registry (UCR)** is the system-wide home for evidence-gated lifecycle governance of research artifacts — features, strategies, weighting schemes, and any other recipe-shaped candidate your system produces. It answers a different question than APR or a classification registry: not "what value should this parameter hold" or "what is this entity," but **"does this recipe deserve to keep running, based on what it has actually proven."**

UCR governs **recipes, not their outputs.** A feature definition is governed here; a computed feature value in a fact table is untouched by this system. A strategy concept is governed here; the weights it produces live in a separate fact table. This separation is load-bearing — conflating "is this recipe valid" with "what did this recipe compute" is exactly the confusion this registry exists to prevent.

Every concept moves through the same four-state lifecycle, proven or disproven by a deterministic evaluation engine that no proposer — human or AI — can short-circuit:

```
candidate → shadow_only → active → deprecated
```

### Relationship to APR and CVR

If your project also has an [APR](adaptive-parameter-registry.md) and a [CVR](controlled-vocabulary-registry.md), the three are siblings, each governing a different kind of knowledge:

- **APR** — tunable *numbers*.
- **CVR** — fixed *symbolic definitions*.
- **UCR** — evidence-gated *lifecycle status* of research artifacts (does this recipe still earn its place).

UCR is typically the only one of the three with a governance-vs-knowledge split baked into its own schema: `concept_registry`/`concept_gate`/`concept_transition_log` prove things (**the gate proves**); `concept_annotation` explains them (**the annotation explains**). Enforce this split structurally, not by convention — see Invariant 1 below.

---

## Infrastructure

Five tables, one or two DB-level triggers, one service with two call surfaces if you need both an async event-driven path and a sync batch-job path.

### Table Schemas

**`concept_registry`** — identity and current status. Changes almost never outside a lifecycle transition.

| Column | Type | Description |
|--------|------|--------------|
| `concept_id` | UUID PRIMARY KEY | |
| `domain` | TEXT NOT NULL, CHECK | Your domain enum, e.g. `'feature'` or `'strategy'` — see Domains below |
| `name` | TEXT NOT NULL | Unique within `(domain, name)` |
| `description` | TEXT NOT NULL | |
| `status` | TEXT NOT NULL DEFAULT `'candidate'`, CHECK | `candidate` / `shadow_only` / `active` / `deprecated` |
| `enabled` | BOOLEAN NOT NULL DEFAULT false | Maintained as `(status = 'active')` by the transition path |
| `parent_concept_id` | UUID, self-FK | Single-parent lineage (legacy shape; some domains may still use it) |
| `redundancy_group` | TEXT | If competing candidates are the normal state, resolve per-group instead of forcing displacement |
| `is_control` / `control_expectation` | BOOLEAN / TEXT, CHECK | Control-canary marking; `control_expectation ∈ {negative_control, positive_control}` |
| `group_name` | TEXT (unconstrained) | Peer-group label, read by real filters wherever grouped analysis happens — not decorative |
| `metadata` | JSONB | Domain-specific fields |
| `added_phase`, `sensitivity` | TEXT | |
| `created_at` | TIMESTAMPTZ | |

**`concept_parent`** — multi-parent lineage join table, for domains where a single `parent_concept_id` FK isn't expressive enough.

| Column | Type | Description |
|--------|------|--------------|
| `child_concept_id`, `parent_concept_id` | UUID, FK both sides | PK `(child, parent)`; CHECK rejects self-edges |
| `created_at` | TIMESTAMPTZ | |

No ordinality column unless a consumer depends on parent order. A `BEFORE INSERT OR UPDATE` trigger should reject any edge that would create a cycle — required if a cascade-deprecation trigger recurses across this table. **Concurrency note:** a cycle check that reads only committed edges leaves a window where two concurrent transactions can each insert one leg of a two-edge cycle. If this table has more than a single-transaction migration-seed writer, take an advisory lock before inserting.

**`concept_gate`** — per-concept promotion/demotion gate, with the eval-state cache folded in (a deliberate simplification vs. a larger reference architecture with separate eval-run tables).

| Column | Type | Description |
|--------|------|--------------|
| `concept_id` | UUID PRIMARY KEY, FK | |
| `gate_metric_name`, `gate_eval_method` | TEXT, CHECK | `gate_eval_method ∈ {oos_holdout, walk_forward, bootstrap_ci}` |
| `min_gate_metric`, `min_gate_n`, `min_promotion_consecutive`, `min_new_observations` | numeric | `NULL` inherits a per-domain APR default |
| `demotion_threshold`, `decay_floor`, `regime_scope` | numeric/TEXT | |
| `fdr_required`, `fdr_alpha` | BOOLEAN, numeric | **Advisory only** — the service reads `fdr_required` to fail-closed-gate promotions, but multiple-comparison correction itself should be computed entirely upstream by the caller, never inside this service |
| `last_eval_metric`, `last_eval_n`, `last_eval_at`, `last_eval_corpus_build_ref` | | Folded eval-state cache |
| `baseline_metric` | numeric | The **mean** of promotion-round metrics at promotion time — never the final (selection-inflated) value (winner's-curse guard) |
| `promotion_consecutive`, `promotion_eval_metrics` | INT, numeric[] | Running win streak and its per-round metrics |
| `consecutive_shadow_passes`, `observations_since_demotion` | INT, BIGINT | Recovery counters — gate `shadow_only → active` re-promotion after a decay |

**`concept_transition_log`** — immutable append-only audit trail, time-partitioned on `triggered_at`.

| Column | Type | Description |
|--------|------|--------------|
| `id`, `triggered_at` | BIGSERIAL, TIMESTAMPTZ | Composite PK `(id, triggered_at)` if using a hypertable — the partition column must be in the PK |
| `concept_id`, `domain`, `name` | | |
| `from_status`, `to_status` | TEXT NOT NULL | |
| `trigger_reason` | TEXT NOT NULL, CHECK | `promotion` / `demotion_performance` / `demotion_decay` / `demotion_redundancy` / `operator_override` / `parent_cascade` / `candidate_timeout` / `implementation_change` / `genesis_seed` |
| `corpus_build_ref` | TEXT | The dataset/build identity the deciding evaluation read from — needed so a re-evaluation guard can compare against it |
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

**Don't over-build the schema up front.** A larger reference architecture might add `concept_gate_template`, `concept_gate_stack`, `concept_eval_run`, `concept_eval_state`, `concept_dependency`, `concept_regime_ic`, `concept_correlation` — start with the five tables above and only add more once a real domain's requirements demand it. All nine invariants below apply to the five-table shape without needing any of these.

### Cascade-deprecation trigger

If you implement cascading deprecation: an `AFTER UPDATE OF status` trigger that, when a concept transitions to `deprecated`, cascades every child in `concept_parent` to `deprecated` too, recursively (safe only if the cycle guard above guarantees an acyclic graph). Two easy bugs to avoid: the audit-log `INSERT` must run **before** the cascading `UPDATE` (logging after would find every child already deprecated and silently select zero rows), and `from_status` must be read as the child's **real** current status, never hardcoded to `'active'`.

---

## The Nine Invariants

These are the stable mechanics — the part of this design meant to survive unchanged regardless of which domain or how many rows are in play.

1. **Proposal and decision are structurally different roles.** An agent (human or AI) may create a `candidate` row and write a `thesis` annotation. It may never write `status` directly. Only the deterministic evaluation engine — no LLM in the path — flips status. No code path both writes annotation content and flips status in the same call.
2. **Re-evaluation consumes new evidence, never re-rolls the same dice.** A concept may not be re-evaluated until `≥ min_new_observations` new independent observations have accrued since its last evaluation. A new dataset/corpus build alone is necessary but insufficient if your rebuilds run on mostly-overlapping windows.
3. **Proposal volume has a budget.** A cap on new AI-sourced `candidate` rows per domain per period, enforced at the service layer.
4. **The proposer's own track record is tracked for free.** `concept_annotation.source` (human/ai/empirical) on every thesis lets a hit-rate query answer "is this proposer's idea generation any good" with no new table.
5. **Demotion is engine-only, same as promotion, opposite direction.** No override path through the proposer. A decay ratio (measured against the winner's-curse-guarded `baseline_metric`) is domain-agnostic infrastructure, not a domain of its own.
6. **`shadow_only` is mandatory between `candidate` and `active`** for proposer-driven or backtested-only domains — non-negotiable for AI-sourced concepts. Document any exception explicitly, and require it to justify why its gate already substitutes for live observation (e.g. a walk-forward OOS gate that already serves the equivalent evidentiary function, or a human-authored candidate set judged by an A/B rule with its own multiple-comparison correction).
7. **Initial promotion requires an effective-N minimum observation floor, regardless of significance.** A concept clearing `p < 0.05` on a handful of observations is a fluke, not proof. The floor should be stated against *effective* N (independent observations), never raw overlapping rows.
8. **Evidence is bound to the implementation version that produced it.** If the underlying computation silently changes after promotion, accumulated evidence no longer describes what's running. A version change resets promotion evidence and re-enters evaluation (`trigger_reason='implementation_change'`).
9. **Status transitions are compare-and-swap, in one transaction.** `UPDATE concept_registry SET status = :to WHERE concept_id = :id AND status = :from` — zero rows matched aborts the whole transaction, including the transition-log insert. Prevents two racing evaluators from logging a transition whose `from_status` never actually matched.

---

## `ConceptRegistryService` — call surfaces

Stateless on the async side if you have one; a sync side may keep an in-memory per-domain cache if its caller has no running event loop (e.g. called from a psycopg-based batch job).

### Async path — e.g. `record_comparison_outcome()`

The **sole** status-flipping code path for domains whose promotion decision comes from an event-driven comparison job (Invariant 1's deterministic engine, concretely). Run read-decide-write inside one transaction with `FOR UPDATE` held throughout, so a concurrent evaluator for the same concept blocks rather than racing. Typical outcomes: `promote` (CAS `candidate→active`), `record_win`/`record_win_not_promotable`/`record_loss` (eval-cache bookkeeping only), or one of several `blocked_*`/`noop_*` results that write nothing — including a `blocked_fdr_unverified`-style result that fails closed whenever the gate's multiple-comparison-correction flag is required and the caller cannot prove that correction actually ran this round.

### Sync path — e.g. `record_transition_sync()` / `advance_shadow_counters_sync()` / `is_promotion_eligible()`

Used by batch jobs with no running event loop. `record_transition_sync` is the CAS-guarded general transition writer (any domain, any `trigger_reason`) — should refuse automated callers targeting `deprecated` (operator-only), validate `trigger_reason` against the CHECK vocabulary before hitting the database, and reset the shadow-recovery counters whenever a transition lands on `shadow_only` (without this, a concept that previously earned recovery would re-promote off a single passing run instead of re-earning the full evidence bar). `advance_shadow_counters_sync` is the only other counter-mutation path — increments/resets `consecutive_shadow_passes` and accumulates `observations_since_demotion` after each run. `is_promotion_eligible` is a pure evidence-only predicate (no calendar/date input) over those two counters.

---

## Domains

| Domain | Status | Gate metric | Min observation floor |
|--------|--------|--------------|------------------------|
| `<your_domain_1>` | — | — | — |
| `<your_domain_2>` | — | — | — |

A domain is added to the live `domain` CHECK only once it has real candidates — never pre-seeded "reserved, pending definition." Fill this table in as your domains go live; don't leave placeholder rows once you have real ones.

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|-----------------|-----|
| A recipe's computed output | The domain's own fact table | UCR governs the recipe, not its results |
| Tunable numeric values, including UCR's own gate defaults | APR | UCR consumes APR, doesn't duplicate it |
| Falsifiable entity classification | A dedicated classification registry, if one exists | Different subject entirely — entities, not research artifacts |
| Fixed symbolic code definitions | CVR | Different epistemic kind of row (definitional vs. evidence-gated) |
| Measured classification assignments | Explicitly **not** a UCR domain | A classification is a fact about an entity, not a recipe with a lifecycle — the two systems' invariants don't transfer |

---

## Related Docs

- [Adaptive Parameter Registry](adaptive-parameter-registry.md), [Controlled Vocabulary Registry](controlled-vocabulary-registry.md) — sibling registries this doc's structure mirrors.

---

## Adopting This in a New Project

1. Copy the five table schemas and the nine invariants verbatim — they're the load-bearing part and are fully domain-agnostic.
2. Fill in the Domains table only once you have a real domain live; don't invent placeholder domains.
3. If your project only ever needs one domain, it's fine to skip the `domain` CHECK enum entirely and hardcode a single value — don't build multi-domain flexibility before you have a second domain that needs it (Musk Step 1/2: don't add it "just in case").
4. Decide up front whether you need both an async and a sync call surface, or just one — most single-service projects only need one.
