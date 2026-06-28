# Metadata Governance Registry System

**Status**: Partially built — four registries live, one designed, one future
**Created**: 2026-06-28
**Type**: Architecture pattern + gap analysis

---

## Renaissance Framing

Renaissance Technologies runs every model variant, signal idea, and methodology through a formal research pipeline. Nothing lives in a notebook nobody reads. Nothing disappears into a deleted branch. Every hypothesis either earns its way to live through accumulated statistical proof or gets formally retired with the evidence attached.

This is not bureaucracy — it is how you avoid re-discovering dead ends. When someone asks ten years from now "why don't we use diagonal covariance HMM?" the answer should be in the database: `demotion triggered 2026-09-14, held-out LL = -847.3 vs full covariance -821.1, n = 1200 bars`. Not in a Slack thread. Not in someone's memory. In a queryable row with the evidence that ruled it out.

The registries in this system are that pipeline. APR formalizes numeric parameters. Feature Registry formalizes predictive features. Shadow Registry formalizes trading components. Concept Registry formalizes research hypotheses across every other domain. Every governed concept moves through the same lifecycle - `candidate → active → shadow_only → deprecated` - driven by statistical gates that cannot be argued with.

The `enabled` flag is the A/B comparison primitive. Two HMM variants running simultaneously in shadow, both scoring every evaluation cycle. Whichever clears the held-out log-likelihood gate promotes. The loser gets `deprecated` with its evidence permanently attached. This is how you run rigorous model selection without ad-hoc notebooks and gut feel.

---

## The Pattern

APR solved a class of problem: things that need to be governed, discovered, and audited at runtime without code changes. The same pattern recurs across the system for different semantic domains. Every instance shares the same structural DNA:

- A **registry table** with a controlled set of entries and rich metadata
- A **transition/history log** — immutable audit trail of state changes
- A **service layer** that loads at daemon startup with a divergence check (mismatch = hard crash)
- **Statistical or rule-based gates** that drive lifecycle transitions
- **Dashboard/SQL discoverability** — any consumer can enumerate members without importing Python

The question is not "should we build registries?" — we already have four. The question is "which domains still need one, and what type?"

---

## Registry Taxonomy

Three types, distinguished by what drives state changes:

### Type 1 — Parameter Registries (value-mutable)
Entries have tunable values. ML can update them at runtime. Gate is validation range, not evidence threshold.
- **APR** (`config_state` + `config_history`) — 348 numeric/behavioral params across 13 namespaces

### Type 2 — Lifecycle Registries (evidence-gated promotion/demotion)
Entries move through states (`candidate → active → shadow_only/deprecated`) based on accumulated statistical evidence. Gate is an IC or return metric threshold.
- **Feature Registry** (`feature_registry` + `feature_transition_log`) — 61 features, IC Sharpe gated, parent-cascade trigger
- **Shadow Registry** (`shadow_registry` + `shadow_transition_log`) — 36 components (i7_plugins, swarm_agents), EV[R] bootstrap CI gated

### Type 3 — Vocabulary Registries (static taxonomy)
Entries are codes/labels with metadata. No lifecycle states. Value is discoverability — dashboard filters, SQL group membership, startup divergence checks against Python enums.
- **Tag Vocabulary** (`tag_vocabulary` + `instrument_tags` + `instrument_annotations`) — 6 categories, 301 human-assigned instrument tags
- **Controlled Vocabulary** (designed, not built) — domain enums: `signal_outcome`, `entry_type`, `signal_status`, `market_regime`, timeframe labels, HMM regime labels

---

## What Exists

| Registry | Type | Tables | Entries | Gate |
|---|---|---|---|---|
| APR | Parameter | `config_state`, `config_history`, `config_schema` | 348 keys | Validation range |
| Feature Registry | Lifecycle | `feature_registry`, `feature_transition_log` | 61 features | IC Sharpe + FDR | migrate to concept_registry at build time |
| Shadow Registry | Lifecycle | `shadow_registry`, `shadow_transition_log` | 36 components | EV[R] bootstrap CI |
| Tag Vocabulary | Vocabulary | `tag_vocabulary`, `instrument_tags`, `instrument_annotations` | 301 tags | Human curation |

---

## What's Missing

### Controlled Vocabulary (Type 3) — next to build

Full design at `docs/plans/2026-06-18-controlled-vocabulary-system.md`. Three tables:

```
controlled_vocabulary      — one row per valid code per namespace
vocabulary_group           — named groupings within a namespace
vocabulary_group_member    — many-to-many membership
```

`VocabularyService` follows `FeatureRegistryService` exactly: load at startup, startup divergence check against Python enums (hard crash on mismatch), cached reads at runtime.

Namespaces to seed on build:
- `signal_outcome` — with groups `wins`, `losses`, `timeouts` (replaces Python frozensets invisible to SQL)
- `entry_type` — `at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`
- `signal_status` — `pending`, `active`, `regime_suppressed`, `expired`
- `hmm_regime` — 5 labels sorted by emission mean log_return
- `market_regime_cross_sectional` — 9 labels (`{low/mid/high}_{bull/neutral/bear}`)
- `timeframe` — display labels, bar seconds, parent TF for HTF resolution

Phase 134 blocker (PG ENUM types) is satisfied. Ready to build.

### Generalized Concept Registry (Type 2) — v3.0, design needed

As the system grows, new concept domains will need the same lifecycle pattern: alpha patterns, HMM variants, IC methods, ensemble strategies, regime models. Building a bespoke table per domain is wrong — the machinery is identical.

The right design is **four tables** with clean separation of concerns. The existing `feature_registry` and `shadow_registry` conflate three distinct concerns in one row — identity, gate parameters, and evaluation state — which change on completely different cadences and have different owners. The generalized design separates them:

```
concept_registry        — identity + current status + enabled flag
concept_gate            — promotion/demotion parameters per concept
concept_eval_state      — latest evaluation snapshot (mutable, overwritten each cycle)
concept_transition_log  — immutable append-only audit trail
```

#### concept_registry
What a concept IS. Changes almost never. Owned by operator/migration.

```sql
CREATE TABLE concept_registry (
    concept_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain       TEXT NOT NULL,   -- 'alpha_pattern', 'hmm_method', 'ic_method', 'regime_model'
    name         TEXT NOT NULL,
    description  TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'active', 'shadow_only', 'deprecated')),
    enabled      BOOLEAN NOT NULL DEFAULT false,
    metadata     JSONB,           -- domain-specific fields (formula, params, etc.)
    added_phase  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);
```

`enabled` is independent of `status`. An `active` concept can be disabled by an operator without demotion — it stays proven, just not running. A `candidate` can be `enabled = true` to run in shadow before it earns promotion.

#### concept_gate
How a concept earns promotion or triggers demotion. Tunable per-concept by the operator. Changes when the operator adjusts the bar for a specific concept.

```sql
CREATE TABLE concept_gate (
    concept_id              UUID PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name        TEXT NOT NULL,  -- 'ic_sharpe', 'log_likelihood', 'ev_r'
    min_gate_metric         FLOAT NOT NULL,
    min_gate_n              INTEGER NOT NULL DEFAULT 100,
    demotion_threshold      FLOAT,          -- NULL = no auto-demotion
    demotion_lookback_days  INTEGER,
    demotion_consecutive    INTEGER,        -- consecutive periods below threshold before demoting
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

#### concept_eval_state
What the evaluation engine last observed. Overwritten each evaluation cycle — not audit data.

```sql
CREATE TABLE concept_eval_state (
    concept_id              UUID PRIMARY KEY REFERENCES concept_registry(concept_id),
    last_eval_metric        FLOAT,
    last_eval_n             INTEGER,
    last_eval_ci_lower      FLOAT,
    demotion_consecutive    INTEGER NOT NULL DEFAULT 0,
    last_eval_at            TIMESTAMPTZ
);
```

The transition log captures the evidence permanently when a state change fires. This table is just the engine's working memory between cycles.

#### concept_transition_log
What happened, immutable, append-only.

```sql
CREATE TABLE concept_transition_log (
    id             BIGSERIAL PRIMARY KEY,
    concept_id     UUID NOT NULL REFERENCES concept_registry(concept_id),
    domain         TEXT NOT NULL,
    name           TEXT NOT NULL,
    from_status    TEXT NOT NULL,
    to_status      TEXT NOT NULL,
    trigger_reason TEXT NOT NULL,  -- 'metric_promotion', 'metric_demotion', 'operator_override', 'cascade'
    gate_metric    FLOAT,
    gate_n         INTEGER,
    ci_lower       FLOAT,
    triggered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes          TEXT
);
```

#### Separation of concerns

| Table | Owner | Changes when | Query to answer |
|---|---|---|---|
| `concept_registry` | Operator / migration | Concept added, renamed, or deprecated | What concepts exist and what is their current state? |
| `concept_gate` | Operator | Promotion bar is adjusted for a specific concept | What does this concept need to prove? |
| `concept_eval_state` | Evaluation engine | Every IC run or shadow eval cycle | What did we observe last time? |
| `concept_transition_log` | Evaluation engine | Every state change | What happened historically and why? |

#### ConceptRegistryService

Follows `FeatureRegistryService` exactly: load at startup per domain, JOIN all four tables into memory, cache reads, async transition logging. Hard crash if a concept in the DB has no gate row (schema integrity check).

#### Domains

| Domain | Gate metric | What it governs |
|---|---|---|
| `alpha_pattern` | IC Sharpe | Alpha signal ideas competing for ensemble inclusion |
| `hmm_variant` | Held-out log-likelihood | HMM architecture variants (covariance structure, obs vector, K) |
| `ic_method` | Walk-forward stability | IC calculation variants (Spearman vs rank-IC vs HAC-adjusted) |
| `ensemble_strategy` | Realized Sharpe | Ensemble weighting strategies |
| `regime_model` | Cross-validated accuracy | Regime classification model variants |
| `feature_interaction` | IC Sharpe + FDR | Interaction feature candidates before FeatureVector promotion |

**Why this is a research pipeline, not a TODO list**

Every hypothesis enters as `candidate`, runs in shadow with `enabled = true`, and either earns promotion or gets formally retired. Nothing disappears into a deleted branch. A `deprecated` row with `ic_sharpe = 0.11, n = 1200` in the transition log tells future research exactly what was tried and refuted - preventing re-discovery of dead ends years later.

The `enabled` flag makes parallel A/B comparison first-class: two `hmm_variant` rows both `enabled = true` in shadow, scored every eval cycle. Whichever clears the log-likelihood gate promotes. The loser gets `deprecated` with its evidence attached. This is how Renaissance governs model variants without ad-hoc notebooks.

#### Feature Registry migration

Feature Registry (`feature_registry`) should be migrated into concept_registry when this is built, as `domain = 'feature'`. It is not architecturally distinct — the reasons to keep it separate are historical, not structural:

- **Dataclass alignment gate** — ConceptRegistryService implements this per domain. Not a reason for a separate table.
- **Parent-cascade DB trigger** — moves to application-layer logic in ConceptRegistryService for the `feature` domain, or a domain-filtered trigger. Not fundamental.
- **SQL columns vs JSONB** — `formula_short`, `normalization`, `linear_ready`, `source_dims`, `requires_htf`, `window_apr_keys`, `parent_features`, `tier`, `group_name` have no actual SQL consumers. ic_engine and ensemble_trainer load everything at startup via `FeatureRegistryService` into Python dicts and work in-memory. JSONB is fine. The only columns that need to be top-level are `status` and `enabled`, which concept_registry already has.

Feature Registry exists as a separate table because it predates concept_registry. Migrating it at build time proves out the design with a live domain from day one and eliminates a bespoke table. `FeatureRegistryService` becomes `ConceptRegistryService` loading `domain = 'feature'`.

Intelligence vector feature ideas and interaction candidates (`feature_interaction`) follow the same path — `candidate` in concept_registry, IC-gated promotion, and if they earn a FeatureVector column they graduate to `domain = 'feature'` status `active`.

Deferred until `alpha_events` pipeline is stable and the first concept domain needs governance.

---

## When to Add a New Registry

A registry earns its cost when all three are true:

1. **Mutable membership** — the set can grow, shrink, or have members change state over time
2. **External consumers need enumeration** — dashboard, SQL queries, or ML pipelines discover members without importing Python
3. **Metadata enrichment has actual consumers** — labels, descriptions, groupings, lifecycle gates are read by something concrete

Not worth it for: mathematical constants, schema identifiers, purely internal codes no consumer enumerates, things with a fixed membership that never changes.

---

## APR Analogy Table

| | APR | Feature Registry | Shadow Registry | Controlled Vocabulary | Concept Registry |
|---|---|---|---|---|---|
| Identity table | `config_state` | `feature_registry` | `shadow_registry` | `controlled_vocabulary` | `concept_registry` |
| Gate params | `config_schema` | in registry row | in registry row | — | `concept_gate` |
| Eval state | — | in registry row | in registry row | — | `concept_eval_state` |
| Audit log | `config_history` | `feature_transition_log` | `shadow_transition_log` | — | `concept_transition_log` |
| Namespace/domain | key prefix | `group_name` + `tier` | `component_type` | `namespace` | `domain` |
| Gate metric | Validation range | IC Sharpe + FDR | EV[R] bootstrap CI | Enum divergence | Per-domain (configurable) |
| Enable/disable | (key deletion) | `status` only | `is_shadow` bool | — | `enabled` flag (independent) |
| Runtime writer | ML discovery | ensemble_trainer | Shadow auditor | Migration only | Evaluation engine |
| Service | `ConfigService` | `FeatureRegistryService` | Shadow auditor | `VocabularyService` | `ConceptRegistryService` |
| Startup check | Schema count | Dataclass field parity | — | Python enum parity | Gate row completeness |
| Dashboard | `/config/parameters` | — | — | `/api/vocabulary/{ns}` | `/api/concepts/{domain}` |

The concept registry is the most fully separated design — the only one that isolates gate parameters and evaluation state from identity into their own tables. Feature Registry and Shadow Registry can be refactored toward this pattern as they mature, but there is no pressing reason to migrate them.
