# Metadata Governance Registry System

**Status**: Partially built — four registries live, one designed, one to build
**Created**: 2026-06-28
**Type**: Architecture pattern + design

---

## Renaissance Framing

Renaissance Technologies runs every model variant, signal idea, and methodology through a formal research pipeline. Nothing lives in a notebook nobody reads. Nothing disappears into a deleted branch. Every hypothesis either earns its way to live through accumulated statistical proof or gets formally retired with the evidence attached.

This is not bureaucracy — it is how you avoid re-discovering dead ends. When someone asks ten years from now "why don't we use diagonal covariance HMM?" the answer should be in the database: `demotion triggered 2026-09-14, held-out LL = -847.3 vs full covariance -821.1, n = 1200 bars`. Not in a Slack thread. Not in someone's memory. Queryable. Permanent.

The registries in this system are that pipeline. Every governed concept moves through the same lifecycle — `candidate → shadow_only → active → deprecated` — driven by statistical gates that cannot be argued with. Promotion requires sustained out-of-sample evidence. Demotion fires automatically when an edge decays below threshold for consecutive evaluation periods. The transition log is the institutional memory.

---

## Registry Taxonomy

Three types, distinguished by what drives state changes:

**Type 1 — Parameter** (value-mutable): entries have tunable values ML can update at runtime. Gate is a validation range.
- **APR** — 348 numeric/behavioral params across 13 namespaces

**Type 2 — Lifecycle** (evidence-gated): entries move through `candidate → shadow_only → active → deprecated` based on statistical evidence.
- **Feature Registry** — 61 features, IC Sharpe + FDR gated _(migrates to Concept Registry at build time)_
- **Shadow Registry** — 36 components, EV[R] bootstrap CI gated
- **Concept Registry** — generalized lifecycle governance for all new research domains _(to build)_

**Type 3 — Vocabulary** (static taxonomy): codes/labels with metadata, no lifecycle states. Value is discoverability.
- **Tag Vocabulary** — 6 categories, 301 instrument tags
- **Controlled Vocabulary** — domain enums (to build, design at `docs/plans/2026-06-18-controlled-vocabulary-system.md`)

---

## What Exists

| Registry | Tables | Entries | Gate | Gap |
|---|---|---|---|---|
| APR | `config_state`, `config_history`, `config_schema` | 348 keys | Validation range | — |
| Feature Registry | `feature_registry`, `feature_transition_log` | 61 features | IC Sharpe + FDR | Gate params + eval state conflated in registry row; migrates to Concept Registry |
| Shadow Registry | `shadow_registry`, `shadow_transition_log` | 36 components | EV[R] bootstrap CI | Same conflation; no OOS enforcement, no decay tracking |
| Tag Vocabulary | `tag_vocabulary`, `instrument_tags`, `instrument_annotations` | 301 tags | Human curation | — |

---

## Controlled Vocabulary (Type 3)

Full design at `docs/plans/2026-06-18-controlled-vocabulary-system.md`. Three tables:

```
controlled_vocabulary      — one row per valid code per namespace
vocabulary_group           — named groupings within a namespace
vocabulary_group_member    — many-to-many membership
```

`VocabularyService`: load at startup, hard crash on Python enum divergence, cached reads.

Namespaces to seed at build time: `signal_outcome` (groups: wins/losses/timeouts), `entry_type`, `signal_status`, `hmm_regime` (5 labels by emission mean), `market_regime_cross_sectional` (9 labels), `timeframe`.

Phase 134 blocker satisfied. Ready to build.

---

## Concept Registry (Type 2) — to build

### Purpose

Every new research domain that needs evidence-gated lifecycle governance goes here. Alpha patterns, HMM architecture variants, IC methods, ensemble strategies, regime models. One set of tables governs all of them. No bespoke tables per domain.

Feature Registry migrates into this at build time as `domain = 'feature'`. It is not architecturally distinct — its separation is historical, not structural. See migration note below.

### Four-table design

The existing Feature Registry and Shadow Registry conflate identity, gate parameters, and evaluation state in a single row. These change on different cadences and have different owners. The correct design separates them:

```
concept_registry       — what a concept IS (identity, status, lineage)
concept_gate           — what it needs to PROVE (promotion/demotion parameters)
concept_eval_state     — what was last OBSERVED (evaluation engine working memory)
concept_transition_log — what HAPPENED (immutable audit trail)
```

---

### concept_registry

Identity and current state. Changes almost never. Owned by operator/migration.

```sql
CREATE TABLE concept_registry (
    concept_id        UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT    NOT NULL,
        -- 'feature', 'alpha_pattern', 'hmm_variant', 'ic_method',
        -- 'ensemble_strategy', 'regime_model', 'feature_interaction'
    name              TEXT    NOT NULL,
    description       TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'candidate'
        CHECK (status IN ('candidate', 'shadow_only', 'active', 'deprecated')),
    enabled           BOOLEAN NOT NULL DEFAULT false,
    parent_concept_id UUID    REFERENCES concept_registry(concept_id),
    redundancy_group  TEXT,
    metadata          JSONB,
    added_phase       TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (domain, name)
);
```

**`enabled`** is independent of `status`. An `active` concept can be disabled without demotion — it stays proven, just not running. A `candidate` can be enabled to run in shadow before earning formal promotion. The evaluation engine skips `enabled = false` concepts entirely.

**`parent_concept_id`** creates a lineage tree. When an HMM variant is iterated (different obs vector, different K), the new row references the parent. Research history is navigable: what was tried before this, why was this a revision?

**`redundancy_group`** prevents silent over-fitting. Concepts in the same group compete — only one can hold `active` status. When a new concept in the group earns promotion, it displaces the incumbent (incumbent moves to `shadow_only`) unless the evaluation engine determines they are sufficiently decorrelated (IC correlation below threshold). Two alpha patterns capturing the same momentum exhaustion signal from different angles should not both be live.

---

### concept_gate

What a concept needs to prove. Tunable per-concept. Changes when an operator adjusts the bar.

```sql
CREATE TABLE concept_gate (
    concept_id                UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name          TEXT  NOT NULL,
        -- 'ic_sharpe', 'log_likelihood', 'ev_r', 'walk_forward_ic', 'cross_val_accuracy'
    gate_eval_method          TEXT  NOT NULL,
        -- 'oos_holdout', 'walk_forward', 'bootstrap_ci' — in-sample never valid
    min_gate_metric           FLOAT NOT NULL,
    min_gate_n                INTEGER NOT NULL DEFAULT 100,
    min_promotion_consecutive INTEGER NOT NULL DEFAULT 3,
        -- evaluations above threshold required before promotion fires
    demotion_threshold        FLOAT,   -- NULL = no auto-demotion
    demotion_lookback_days    INTEGER,
    demotion_consecutive      INTEGER, -- consecutive periods below threshold before demotion
    decay_floor               FLOAT,   -- ratio of current/baseline below which decay demotion fires
    regime_scope              TEXT,    -- NULL = unconditional; regime label = conditional gate
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`gate_eval_method`** is non-negotiable. An IC computed in-sample is meaningless and will cause false promotions. Every gate must declare its evaluation method and the evaluation engine must enforce it. `oos_holdout`, `walk_forward`, or `bootstrap_ci` are the only valid values.

**`min_promotion_consecutive`** prevents premature promotion on a lucky evaluation. A concept must clear the gate metric on N consecutive evaluation cycles before promotion fires. Default 3 — one good evaluation proves nothing.

**`regime_scope`** enables conditional promotion. An alpha pattern with IC Sharpe 0.8 in trending and 0.1 in ranging would fail an unconditional gate at most thresholds. Setting `regime_scope = 'trending_up'` governs it as a regime-conditional edge — valid and live only when the regime engine is in that state. The IC engine already stratifies by regime; the concept gate should too.

**`decay_floor`** is the decay demotion trigger. When `current_metric / baseline_metric_at_promotion < decay_floor`, the demotion fires immediately without waiting for `demotion_consecutive` periods. Edges decay — a concept that was IC Sharpe 0.6 at promotion and is now 0.15 is a zombie. Kill it automatically.

---

### concept_eval_state

What the evaluation engine last observed. Overwritten each cycle — not audit data. The transition log captures evidence permanently at state-change time.

```sql
CREATE TABLE concept_eval_state (
    concept_id                UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    last_eval_metric          FLOAT,
    last_eval_n               INTEGER,
    last_eval_ci_lower        FLOAT,
    baseline_metric           FLOAT,   -- metric value at promotion; NULL if never promoted
    decay_ratio               FLOAT,   -- last_eval_metric / baseline_metric
    promotion_consecutive     INTEGER  NOT NULL DEFAULT 0,
    demotion_consecutive      INTEGER  NOT NULL DEFAULT 0,
    last_eval_at              TIMESTAMPTZ,
    last_eval_regime          TEXT     -- regime label if gate is regime-scoped
);
```

**`baseline_metric`** is written once at promotion and never updated. Everything after is compared against it. `decay_ratio` is derived: `last_eval_metric / baseline_metric`. When `decay_ratio < decay_floor` (from `concept_gate`), the evaluation engine fires a decay demotion without waiting for `demotion_consecutive`.

**`promotion_consecutive`** counts how many consecutive evaluations have cleared the gate. When this reaches `min_promotion_consecutive`, promotion fires.

---

### concept_transition_log

What happened. Immutable, append-only. The institutional memory.

```sql
CREATE TABLE concept_transition_log (
    id             BIGSERIAL    PRIMARY KEY,
    concept_id     UUID         NOT NULL REFERENCES concept_registry(concept_id),
    domain         TEXT         NOT NULL,
    name           TEXT         NOT NULL,
    from_status    TEXT         NOT NULL,
    to_status      TEXT         NOT NULL,
    trigger_reason TEXT         NOT NULL,
        -- 'promotion', 'demotion_performance', 'demotion_decay', 'demotion_redundancy',
        -- 'operator_override', 'parent_cascade'
    gate_metric    FLOAT,
    gate_n         INTEGER,
    ci_lower       FLOAT,
    decay_ratio    FLOAT,       -- populated on decay demotions
    regime_scope   TEXT,        -- populated if gate was regime-conditional
    triggered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notes          TEXT
);
```

`trigger_reason` distinguishes why a demotion fired — performance degradation, decay, redundancy displacement, or operator override. Each has different implications for future research. A decay demotion on a concept that was once strong signals edge erosion over time. A redundancy demotion signals a better competitor emerged. These are not the same.

---

### Separation of concerns

| Table | Owner | Changes when | Query purpose |
|---|---|---|---|
| `concept_registry` | Operator / migration | Concept added, iterated, or deprecated | What exists and what state is it in? |
| `concept_gate` | Operator | Promotion bar tuned for a concept | What does it need to prove, and how? |
| `concept_eval_state` | Evaluation engine | Every eval cycle | What did we last observe? |
| `concept_transition_log` | Evaluation engine | Every state change | What happened and why? |

---

### ConceptRegistryService

Follows `FeatureRegistryService` with one improvement: **domain-scoped lazy loading**. Active and shadow_only concepts for a domain load eagerly at daemon startup (these are in use). Candidates load lazily when the evaluation engine first requests that domain. With hundreds of alpha pattern candidates, loading all of them at startup is wasteful — only the evaluation engine needs candidates and it runs in batch.

Hard crash at startup if any active or shadow_only concept has no `concept_gate` row. Candidates without gates are valid (they haven't been formally entered into evaluation yet).

---

### Domains

| Domain | Gate metric | Eval method | What it governs |
|---|---|---|---|
| `feature` | IC Sharpe + FDR | Walk-forward | Intelligence vector features (migrated from feature_registry) |
| `feature_interaction` | IC Sharpe + FDR | Walk-forward | Interaction feature candidates before FeatureVector column |
| `alpha_pattern` | IC Sharpe | OOS holdout | Alpha signal ideas competing for ensemble inclusion |
| `hmm_variant` | Held-out log-likelihood | OOS holdout | HMM architecture variants (covariance, obs vector, K) |
| `ic_method` | Walk-forward IC stability | Walk-forward | IC calculation variants (Spearman, rank-IC, HAC methods) |
| `ensemble_strategy` | Realized Sharpe | OOS holdout | Ensemble weighting strategies |
| `regime_model` | Cross-validated accuracy | Walk-forward | Regime classification model variants |

---

### Feature Registry migration

`feature_registry` migrates into concept_registry at build time as `domain = 'feature'`. Its separation is historical, not structural:

- **Dataclass alignment gate** — implemented in ConceptRegistryService per domain. Not a table concern.
- **Parent-cascade trigger** — moves to application-layer logic for `domain = 'feature'`, or a domain-filtered DB trigger.
- **SQL columns** — `formula_short`, `normalization`, `linear_ready`, `tier`, `group_name` etc. move to `metadata JSONB`. The actual consumers (ic_engine, ensemble_trainer) load everything at startup into Python dicts — there are no SQL-level consumers of these columns.

`FeatureRegistryService` is replaced by `ConceptRegistryService` loading `domain = 'feature'`. Migration proves out the design with a live domain from day one.

Intelligence vector ideas and interaction candidates start as `domain = 'feature_interaction'` in candidate status, earn IC promotion, and if they get a FeatureVector column they move to `domain = 'feature'`.

---

## When to Add a New Registry

A registry earns its cost when all three are true:

1. **Mutable membership** — the set can grow, shrink, or change state over time
2. **External consumers need enumeration** — dashboard, SQL, or ML pipelines discover members without importing Python
3. **Metadata enrichment has actual consumers** — labels, descriptions, groupings, or gates are read by something concrete

Not worth it for: mathematical constants, schema identifiers, internal codes no consumer enumerates, fixed sets that never change.

---

## Full Comparison

| | APR | Shadow Registry | Controlled Vocabulary | Concept Registry |
|---|---|---|---|---|
| Identity table | `config_state` | `shadow_registry` | `controlled_vocabulary` | `concept_registry` |
| Gate params | `config_schema` | in registry row | — | `concept_gate` (separate) |
| Eval state | — | in registry row | — | `concept_eval_state` (separate) |
| Audit log | `config_history` | `shadow_transition_log` | — | `concept_transition_log` |
| Gate metric | Validation range | EV[R] bootstrap CI | Enum divergence | Per-domain, OOS-enforced |
| OOS enforcement | — | No | — | Yes — `gate_eval_method` required |
| Regime-conditional | — | No | — | Yes — `regime_scope` per gate |
| Sustained promotion | — | No | — | Yes — `min_promotion_consecutive` |
| Decay tracking | — | No | — | Yes — `decay_ratio` vs `baseline_metric` |
| Lineage | — | No | — | Yes — `parent_concept_id` |
| Redundancy | — | No | — | Yes — `redundancy_group` |
| Enable/disable | (key deletion) | `is_shadow` bool | — | `enabled` independent of `status` |
| Service | `ConfigService` | Shadow auditor | `VocabularyService` | `ConceptRegistryService` |
| Loading | Eager | Eager | Eager | Active/shadow eager; candidates lazy |
| Dashboard | `/config/parameters` | — | `/api/vocabulary/{ns}` | `/api/concepts/{domain}` |
