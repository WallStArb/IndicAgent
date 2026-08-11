# Controlled Vocabulary Registry (CVR)

**Canonical name:** Controlled Vocabulary Registry (CVR)
**Status:** template — pattern only, all examples are illustrative placeholders
**Source:** genericized from IndicAgent `docs/foundation/controlled-vocabulary-registry.md`

---

## What It Is

The **Controlled Vocabulary Registry (CVR)** is the system-wide home for symbolic taxonomies — the set of valid codes a namespace can take, plus their human-readable labels and optional groupings. It is "the APR for symbolic codes": rather than a hardcoded label dict scattered across every consumer that needs to know a given namespace has exactly some fixed set of valid codes, one migration-governed registry holds the authoritative set, and consumers read from it instead of re-declaring it.

CVR rows are **definitional, not falsifiable**. A code either exists in a namespace or it does not — no confidence, weight, or evidence attached. This is the key structural distinction from a falsifiable-classification registry (see [ITR pattern note](#relationship-to-apr-and-a-classification-registry) below): a classification claim is a hypothesis about an entity that can be measured, contradicted, and expired; a controlled-vocabulary code is a fixed symbolic definition, changed only by migration. A code like `namespace/some_code` existing as valid is not something a measurement process re-checks each week — it's the fixed name of a state some other system assigns.

The registry closes a specific failure mode: silent taxonomy drift. A live source column can start emitting a code the registry never heard of — a renamed label, a new category, a third enum value nobody registered — and every downstream consumer with a hardcoded label list just silently mishandles it. CVR makes that loud via a `VocabularyDriftAuditor`.

### Relationship to APR and a classification registry

If your project also has an Adaptive Parameter Registry ([APR](adaptive-parameter-registry.md)) and a falsifiable-classification registry (an "Instrument Tag Registry"-style system, not included in this portable set since it's usually deeply domain-specific), the three are siblings, each governing a different kind of knowledge:

- **APR** — tunable *numbers* (thresholds, weights, periods).
- **Classification registry** — falsifiable *classification claims* about entities (this entity has this property, measured with evidence).
- **CVR** — fixed *symbolic definitions* (this code is valid in this namespace, and means this).

Keep CVR **permanently separate** from a classification registry even though both look like "vocabulary" at a glance — forcing a definitional row (`timeframe/5m`) and a confidence-weighted hypothesis row (`entity_x`/`property_y`, `loading=0.71`, `p=0.02`) through one shared table would make the schema lie about what kind of row it is. No shared table, no FK, no bridging ENUM.

---

## Infrastructure

Three tables, one read-side service, one drift auditor. A dashboard is optional — a read-only API is usually sufficient.

### Table Schemas

**`controlled_vocabulary`** — flat `(namespace, code)` → label/description registry.

| Column | Type | Description |
|--------|------|--------------|
| `namespace` | TEXT NOT NULL | e.g. `status`, `timeframe` |
| `code` | TEXT NOT NULL | e.g. `active`, `5m` |
| PK | `(namespace, code)` | |
| `label` | TEXT NOT NULL | Human-readable display label |
| `description` | TEXT | |
| `sort_order` | INT NOT NULL DEFAULT 0 | Display ordering |
| `is_deprecated` | BOOLEAN NOT NULL DEFAULT FALSE | Retired code, kept for historical row compatibility |
| `created_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |

**`vocabulary_group`** — named groupings within a namespace (e.g. `status/terminal` grouping `completed` + `failed` + `cancelled`).

| Column | Type | Description |
|--------|------|--------------|
| `namespace` | TEXT NOT NULL | |
| `group_name` | TEXT NOT NULL | |
| PK | `(namespace, group_name)` | |
| `label`, `description`, `sort_order` | | Same shape as above |

**`vocabulary_group_member`** — join table; a code may belong to more than one group in the same namespace, which is why this is a join table rather than a `parent_code` column.

| Column | Type | Description |
|--------|------|--------------|
| `namespace`, `group_name`, `code` | TEXT NOT NULL | Composite PK |
| FK | `(namespace, code)` → `controlled_vocabulary`, `(namespace, group_name)` → `vocabulary_group` | Referential integrity — a membership row can never reference a code or group that doesn't exist |

### Namespaces (illustrative example)

| Namespace | Live codes | Source column it governs |
|-----------|-----------|----------------------------|
| `status` | e.g. 5 | `entities.status` |
| `timeframe` | e.g. 5 | `data_points.timeframe` |
| `category` | e.g. 3 | `entities.metadata->>'category'` |
| `tier` | — | `registry.metadata->>'tier'` |

Replace this table with your real namespaces once you have them seeded — don't leave placeholder rows in a live doc.

---

## `VocabularyService` — read side

Mirrors a config-registry service exactly: fully cached at `initialize()` (one prewarm `SELECT` per table — this corpus should stay small, tens to low hundreds of rows total across all namespaces), zero DB calls on the hot path, embedded as a library by any consumer — not a network service, not a new DAG node.

```python
vocab = VocabularyService(db_dsn, pool=pool)
await vocab.initialize()          # one-time prewarm

vocab.codes("timeframe")          # ['1m', '5m', '15m', '1h', '1d']
vocab.active_codes("timeframe")   # same, minus is_deprecated=true rows
vocab.label("status", "active")   # falls back to the code itself if unknown
vocab.group_codes("status", "terminal")  # frozenset() if unknown group
vocab.known_namespaces()          # frozenset of every namespace with >=1 cached code
```

No lazy miss-then-fetch fallback — if the corpus stays small by design, a cache miss should be answered from memory (fallback to the raw code/group name), never a DB round-trip.

The vocabulary tables are **written only at migration time** — `VocabularyService` is a pure read-side projection, never a writer.

---

## `VocabularyDriftAuditor` — write-adjacent monitoring

A oneshot batch job, not necessarily on a fixed timer — can be chained as a non-blocking step into whatever pipeline run touches the governed source columns.

For each namespace, it queries the live source column for distinct observed codes over a recent window (an APR-sourced parameter, e.g. default 30 days) and diffs against the vocabulary service's registered set. Any observed code the registry doesn't know about is a **data-superset drift** — logged as an error, counted via a metric, and recorded as an integrity-monitor fact.

```
observed codes (live column, recent window)  −  registered codes (VocabularyService)
                                    │
                          non-empty difference?
                                    │
                    yes → loud error + integrity-monitor fact + metric counter
                    no  → clean, integrity-monitor fact still recorded (passed=true)
```

**Guards against two specific false-positive shapes:**
- **Source-idle ≠ mass deprecation.** An empty observed set (no rows in the window) is skipped entirely, never misread as "every registered code just got deprecated."
- **Namespace-query drift.** A startup assertion should fail loud if this module's own hardcoded per-namespace query dict falls out of sync with what `VocabularyService` actually has cached — catches a namespace silently dropped from checking, or one whose registered codes went stale.

**Observability-only, never a hard gate** — a detected drift should never fail the pipeline run; only a genuine runtime error (DB unreachable, etc.) should propagate as a real failure.

---

## API surface

A read-only HTTP endpoint, `GET /{namespace}`, returning codes/labels/groups for a namespace. Lets any external consumer (dashboard, external tool) enumerate a namespace without importing your language's client library or hardcoding labels. Unknown namespace → 404 (not an empty 200 or a raw SQL error); genuine backend failure → 503. Not a dashboard/UI in itself — a data endpoint a UI would consume.

---

## When to Add a New Namespace

A namespace earns its place in CVR when all three hold:

1. **Membership is mutable** — the code set can change without a code deployment.
2. **External consumers need enumeration without importing your code** — e.g. a dashboard dropdown, an API caller.
3. **Metadata enrichment has real, concrete consumers** — labels/descriptions/groups are actually read somewhere, not speculative.

**Not worth it** for a fixed set no consumer enumerates — a private internal enum/literal type doesn't need a CVR namespace just because it's a set of strings.

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|-----------------|-----|
| Confidence-weighted, falsifiable classification | A dedicated classification registry, if one exists | A different epistemic kind of row — hypothesis with evidence, not a fixed definition |
| Tunable numeric values | APR (`config_state`) | CVR governs symbolic codes, not numbers |
| Evidence-gated research-artifact lifecycle status | A concept/lifecycle registry, if one exists ([UCR pattern](unified-concept-registry.md)) | A different registry type entirely |

---

## Related Docs

- [Adaptive Parameter Registry](adaptive-parameter-registry.md) — sibling registry (tunable numbers) this doc's structure mirrors.
- [Unified Concept Registry](unified-concept-registry.md) — sibling registry (evidence-gated lifecycle status).

---

## Adopting This in a New Project

1. Copy the three table schemas and the read-side/drift-auditor mechanism verbatim.
2. Replace the illustrative namespace table with your real namespaces once seeded.
3. If your project has no equivalent to a falsifiable-classification registry, delete the cross-references to it rather than leaving a dangling "if one exists" caveat once you know the answer.
