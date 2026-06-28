# Metadata Governance Registry System

**Status**: Partially built — four registries live, two to build
**Created**: 2026-06-28
**Type**: Architecture pattern + design

---

## Renaissance Framing

Renaissance Technologies runs every model variant, signal idea, and methodology through a formal research pipeline. Nothing lives in a notebook nobody reads. Nothing disappears into a deleted branch. Every hypothesis either earns its way to live through accumulated statistical proof or gets formally retired with the evidence attached.

This is not bureaucracy — it is how you avoid re-discovering dead ends. When someone asks ten years from now "why don't we use diagonal covariance HMM?" the answer should be in the database: `demotion triggered 2026-09-14, held-out LL = -847.3 vs full covariance -821.1, n = 1200 bars`. Not in a Slack thread. Not in someone's memory. Queryable. Permanent.

But evidence alone is not enough. The other half of institutional knowledge is understanding — why something works, what breaks it, what we've learned since deployment, what depends on what. A concept whose thesis lives only in someone's head evaporates when they're gone. A concept whose failure modes are undocumented gets re-discovered the hard way.

The registries in this system capture both halves. The **governance layer** answers: *Is this valid? What state is it in? What happened?* The **knowledge layer** answers: *Why does it work? What breaks it? What have we learned? What depends on it?*

---

## Registry Taxonomy

Three types, distinguished by what drives state changes:

**Type 1 — Parameter** (value-mutable): entries have tunable values ML can update at runtime. Gate is a validation range.
- **APR** — 348 numeric/behavioral params across 13 namespaces

**Type 2 — Lifecycle** (evidence-gated): entries move through `candidate → shadow_only → active → deprecated` based on statistical evidence.
- **Shadow Registry** — 36 components, EV[R] bootstrap CI gated
- **Concept Registry** — generalized lifecycle governance for all research domains _(to build; absorbs Feature Registry)_

**Type 3 — Vocabulary** (static taxonomy): codes/labels with metadata, no lifecycle states.
- **Tag Vocabulary** — 6 categories, 301 instrument tags
- **Controlled Vocabulary** — domain enums _(to build; design at `docs/plans/2026-06-18-controlled-vocabulary-system.md`)_

---

## What Exists

| Registry | Tables | Entries | Gate | Gap |
|---|---|---|---|---|
| APR | `config_state`, `config_history`, `config_schema` | 348 keys | Validation range | — |
| Feature Registry | `feature_registry`, `feature_transition_log` | 61 features | IC Sharpe + FDR | Governance only — no knowledge layer; gate params conflated in registry row; migrates to Concept Registry |
| Shadow Registry | `shadow_registry`, `shadow_transition_log` | 36 components | EV[R] bootstrap CI | Governance only — no OOS enforcement, no decay tracking, no knowledge layer |
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

Every research domain that needs evidence-gated lifecycle governance goes here. Alpha patterns, HMM architecture variants, IC methods, ensemble strategies, regime models, intelligence vector features. One system governs all of them.

Feature Registry migrates into this at build time as `domain = 'feature'`. It is not architecturally distinct — its separation is historical, not structural.

### Two layers, seven tables

```
GOVERNANCE LAYER — is this valid, what state is it in, what happened
  concept_registry       — identity, status, lineage, redundancy group
  concept_gate           — what it needs to prove (OOS method, regime scope, sustained threshold)
  concept_eval_state     — evaluation engine working memory (overwritten each cycle)
  concept_transition_log — immutable state-change audit trail

KNOWLEDGE LAYER — why it works, what breaks it, what we know, what depends on what
  concept_annotation     — versioned knowledge: thesis, assumptions, failure modes, observations
  concept_dependency     — directed dependency graph between concepts
  concept_regime_ic      — full regime-stratified IC matrix (evaluation engine writes every cycle)
```

---

### GOVERNANCE LAYER

#### concept_registry

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

**`enabled`** is independent of `status`. An `active` concept can be disabled without demotion. A `candidate` can run in shadow before formal promotion. The evaluation engine skips `enabled = false` entirely.

**`parent_concept_id`** creates a research lineage tree. When an HMM variant is iterated, the revision references the prior version. History is navigable.

**`redundancy_group`** prevents silent over-fitting. Concepts in the same group compete — only one holds `active`. When a new concept earns promotion, it displaces the incumbent unless their IC correlation is below threshold.

---

#### concept_gate

What a concept needs to prove. Per-concept, tunable by the operator.

```sql
CREATE TABLE concept_gate (
    concept_id                UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    gate_metric_name          TEXT  NOT NULL,
        -- 'ic_sharpe', 'log_likelihood', 'ev_r', 'walk_forward_ic', 'cross_val_accuracy'
    gate_eval_method          TEXT  NOT NULL,
        -- 'oos_holdout', 'walk_forward', 'bootstrap_ci'
        -- in-sample is never valid — enforced at write time
    min_gate_metric           FLOAT   NOT NULL,
    min_gate_n                INTEGER NOT NULL DEFAULT 100,
    min_promotion_consecutive INTEGER NOT NULL DEFAULT 3,
    demotion_threshold        FLOAT,
    demotion_lookback_days    INTEGER,
    demotion_consecutive      INTEGER,
    decay_floor               FLOAT,
    regime_scope              TEXT,   -- NULL = unconditional; regime label = conditional gate
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**`gate_eval_method`** is non-negotiable. In-sample IC causes false promotions. Every gate declares its evaluation method; the evaluation engine enforces it.

**`min_promotion_consecutive`** — N consecutive evaluations above threshold before promotion fires. Default 3. One good evaluation proves nothing.

**`regime_scope`** — an edge that works only in trending regime is a real edge. Governing it conditionally is more honest than forcing it through an unconditional gate it cannot pass.

**`decay_floor`** — when `current_metric / baseline_metric_at_promotion < decay_floor`, decay demotion fires immediately without waiting for `demotion_consecutive`. Zombie edges die fast.

---

#### concept_eval_state

Evaluation engine working memory. Overwritten each cycle — not audit data.

```sql
CREATE TABLE concept_eval_state (
    concept_id             UUID  PRIMARY KEY REFERENCES concept_registry(concept_id),
    last_eval_metric       FLOAT,
    last_eval_n            INTEGER,
    last_eval_ci_lower     FLOAT,
    baseline_metric        FLOAT,   -- metric at promotion; NULL if never promoted
    decay_ratio            FLOAT,   -- last_eval_metric / baseline_metric
    promotion_consecutive  INTEGER  NOT NULL DEFAULT 0,
    demotion_consecutive   INTEGER  NOT NULL DEFAULT 0,
    last_eval_at           TIMESTAMPTZ,
    last_eval_regime       TEXT
);
```

**`baseline_metric`** is written once at promotion and never updated. `decay_ratio` is derived from it every cycle. When `decay_ratio < decay_floor`, the engine fires a decay demotion immediately.

---

#### concept_transition_log

What happened. Immutable, append-only.

```sql
CREATE TABLE concept_transition_log (
    id             BIGSERIAL    PRIMARY KEY,
    concept_id     UUID         NOT NULL REFERENCES concept_registry(concept_id),
    domain         TEXT         NOT NULL,
    name           TEXT         NOT NULL,
    from_status    TEXT         NOT NULL,
    to_status      TEXT         NOT NULL,
    trigger_reason TEXT         NOT NULL,
        -- 'promotion', 'demotion_performance', 'demotion_decay',
        -- 'demotion_redundancy', 'operator_override', 'parent_cascade'
    gate_metric    FLOAT,
    gate_n         INTEGER,
    ci_lower       FLOAT,
    decay_ratio    FLOAT,
    regime_scope   TEXT,
    triggered_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    notes          TEXT
);
```

`trigger_reason` distinguishes why a demotion fired. A decay demotion on a once-strong concept signals edge erosion. A redundancy demotion signals a better competitor emerged. These imply different research responses.

---

### KNOWLEDGE LAYER

#### concept_annotation

Versioned, typed knowledge about a concept. Append-only — annotations accumulate over time, superseded annotations are closed with `valid_to`. Same pattern as `instrument_annotations`.

```sql
CREATE TABLE concept_annotation (
    annotation_id   UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    concept_id      UUID         NOT NULL REFERENCES concept_registry(concept_id),
    annotation_type TEXT         NOT NULL CHECK (annotation_type IN (
        'thesis',           -- why this works: market microstructure or behavioral basis
        'assumption',       -- what must be true for it to hold
        'failure_mode',     -- when and how it breaks
        'observation',      -- empirical finding since deployment
        'open_question',    -- what we still do not understand
        'implementation',   -- how it is computed, which code path
        'reference'         -- paper, doc, or prior concept that inspired this
    )),
    content         TEXT         NOT NULL,
    source          TEXT         NOT NULL CHECK (source IN ('human', 'ai', 'empirical')),
        -- 'empirical' = derived from evaluation data by the evaluation engine
    confidence      FLOAT        CHECK (confidence BETWEEN 0 AND 1),
    valid_from      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    valid_to        TIMESTAMPTZ, -- NULL = still holds; set when superseded
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
```

Every concept gets a `thesis` annotation at creation — this is the intellectual basis, not a one-liner description. The `failure_mode` annotations accumulate empirically: the evaluation engine writes one when it detects a regime or volatility condition that correlates with IC collapse. `observation` annotations capture what was learned post-promotion that was not known at creation. `open_question` annotations mark things that are unresolved — they surface in the dashboard as open research items.

`source = 'empirical'` means the evaluation engine wrote it, not a human. Example: "IC correlation with alpha_pattern_momentum_exhaustion = 0.71, evaluated 2026-09-14, n = 1200 bars." This turns the evaluation engine into a self-documenting research system.

---

#### concept_dependency

Directed dependency graph between concepts.

```sql
CREATE TABLE concept_dependency (
    concept_id       UUID NOT NULL REFERENCES concept_registry(concept_id),
    depends_on_id    UUID NOT NULL REFERENCES concept_registry(concept_id),
    dependency_type  TEXT NOT NULL CHECK (dependency_type IN (
        'uses_feature',     -- alpha pattern uses this feature
        'extends',          -- this is a refinement of that concept
        'competes_with',    -- explicit competition outside redundancy_group
        'requires_method'   -- this concept requires a specific ic_method or regime_model
    )),
    PRIMARY KEY (concept_id, depends_on_id)
);
```

Enables impact analysis: "what breaks if `momentum_z_fast` is deprecated?" → query `WHERE depends_on_id = X AND dependency_type = 'uses_feature'`. The gate check at promotion time can block a concept from promoting if any of its `uses_feature` dependencies are still `candidate`.

---

#### concept_regime_ic

Full regime-stratified IC matrix. The evaluation engine writes this every cycle for every active/shadow concept. The ensemble reads it to weight concepts by current regime.

```sql
CREATE TABLE concept_regime_ic (
    concept_id   UUID         NOT NULL REFERENCES concept_registry(concept_id),
    regime_label TEXT         NOT NULL,
    ic_sharpe    FLOAT,
    ic_n         INTEGER,
    ci_lower     FLOAT,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (concept_id, regime_label)
);
```

This is richer than `regime_scope` in `concept_gate`. A concept with `regime_scope = NULL` (unconditional gate) may still show a strong regime profile here: IC Sharpe 0.8 in `trending_up`, 0.1 in `ranging`, -0.3 in `trending_down`. The ensemble uses the full matrix to apply zero weight outside the concept's strong regimes without needing to change its governance status. Regime-conditional weighting and regime-conditional promotion are separate concerns.

---

### Separation of concerns

| Table | Layer | Owner | Changes when | Query purpose |
|---|---|---|---|---|
| `concept_registry` | Governance | Operator / migration | Concept added, iterated, or deprecated | What exists and what state is it in? |
| `concept_gate` | Governance | Operator | Promotion bar tuned | What does it need to prove, and how? |
| `concept_eval_state` | Governance | Evaluation engine | Every eval cycle | What did we last observe? |
| `concept_transition_log` | Governance | Evaluation engine | Every state change | What happened and why? |
| `concept_annotation` | Knowledge | Human / AI / engine | New understanding gained | Why does it work? What breaks it? What's open? |
| `concept_dependency` | Knowledge | Operator / migration | Concept created or relationship identified | What does this depend on? What does it affect? |
| `concept_regime_ic` | Knowledge | Evaluation engine | Every eval cycle | What is the IC profile by regime? |

---

### ConceptRegistryService

Domain-scoped **lazy loading**. Active and shadow_only concepts load eagerly at daemon startup — these are in use. Candidates load lazily when the evaluation engine requests them. With hundreds of alpha pattern candidates, loading all at startup is wasteful.

Hard crash if any `active` or `shadow_only` concept has no `concept_gate` row. Candidates without gates are valid — they are not yet in formal evaluation.

Knowledge layer tables (annotation, dependency, regime_ic) are read on demand, not cached at startup. They are queried by the dashboard and the evaluation engine but not on the hot path.

---

### Domains

| Domain | Gate metric | Eval method | What it governs |
|---|---|---|---|
| `feature` | IC Sharpe + FDR | Walk-forward | Intelligence vector features (migrated from feature_registry) |
| `feature_interaction` | IC Sharpe + FDR | Walk-forward | Interaction feature candidates before FeatureVector column |
| `alpha_pattern` | IC Sharpe | OOS holdout | Alpha signal ideas competing for ensemble inclusion |
| `hmm_variant` | Held-out log-likelihood | OOS holdout | HMM architecture variants (covariance structure, obs vector, K) |
| `ic_method` | Walk-forward IC stability | Walk-forward | IC calculation variants (Spearman, rank-IC, HAC methods) |
| `ensemble_strategy` | Realized Sharpe | OOS holdout | Ensemble weighting strategies |
| `regime_model` | Cross-validated accuracy | Walk-forward | Regime classification model variants |

---

### Feature Registry migration

`feature_registry` migrates into concept_registry at build time as `domain = 'feature'`. Its separation is historical, not structural:

- **Dataclass alignment gate** — implemented per domain in ConceptRegistryService
- **Parent-cascade trigger** — application-layer logic for `domain = 'feature'`
- **SQL columns vs JSONB** — `formula_short`, `normalization`, `linear_ready`, `tier`, `group_name` etc. move to `metadata JSONB`; actual consumers (ic_engine, ensemble_trainer) load into Python at startup, no SQL-level consumers exist

`FeatureRegistryService` becomes `ConceptRegistryService` loading `domain = 'feature'`. Migration proves the design with a live domain on day one.

Feature ideas and interaction candidates enter as `domain = 'feature_interaction'` at `candidate` status, earn IC promotion, then graduate to `domain = 'feature'` when they get a FeatureVector column.

---

### Build sequence

1. Governance layer (concept_registry, concept_gate, concept_eval_state, concept_transition_log)
2. Migrate feature_registry → `domain = 'feature'`; seed `thesis` and `failure_mode` annotations for all 61 features
3. `concept_regime_ic` — evaluation engine writes from day one; feeds ensemble immediately
4. `concept_annotation` — human knowledge layer live; AI and empirical annotations accumulate
5. `concept_dependency` — populated at concept creation; gate checks dependencies before promotion
6. Dashboard: single concept view shows all seven tables — governance status, annotation history, regime IC heatmap, dependency graph

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
| State audit log | `config_history` | `shadow_transition_log` | — | `concept_transition_log` |
| Knowledge — thesis/failure modes | — | — | — | `concept_annotation` |
| Knowledge — dependency graph | — | — | — | `concept_dependency` |
| Knowledge — regime IC matrix | — | — | — | `concept_regime_ic` |
| OOS enforcement | — | No | — | Yes — `gate_eval_method` required |
| Regime-conditional gate | — | No | — | Yes — `regime_scope` |
| Sustained promotion | — | No | — | Yes — `min_promotion_consecutive` |
| Decay tracking | — | No | — | Yes — `decay_ratio` vs `baseline_metric` |
| Lineage | — | No | — | Yes — `parent_concept_id` |
| Redundancy | — | No | — | Yes — `redundancy_group` |
| Enable/disable | (key deletion) | `is_shadow` bool | — | `enabled` independent of `status` |
| Service | `ConfigService` | Shadow auditor | `VocabularyService` | `ConceptRegistryService` |
| Loading | Eager | Eager | Eager | Active/shadow eager; candidates lazy |
| Dashboard | `/config/parameters` | — | `/api/vocabulary/{ns}` | `/api/concepts/{domain}` |
