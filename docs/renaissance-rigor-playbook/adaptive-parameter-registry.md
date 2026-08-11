# Adaptive Parameter Registry (APR)

**Canonical name:** Adaptive Parameter Registry (APR)
**Status:** template — pattern only, all examples are illustrative placeholders
**Source:** genericized from IndicAgent `docs/foundation/adaptive-parameter-registry.md`

---

## What It Is

The **Adaptive Parameter Registry (APR)** is the system-wide home for all tunable numeric values — detection thresholds, indicator periods, confidence weights, governance gates, and UX preferences. Every value that a human operator, ML discovery, or user might want to change without a code deployment lives here.

"Adaptive" is the key distinction from a generic config store: APR parameters are not static configuration. They start as `[initial_estimate]` or `[conventional]` human opinions and evolve through evidence — ML discovery (or any measurement process) writes calibrated values back after sufficient sample sizes and statistical significance. The full conversation between human judgment and empirical evidence is preserved in a `config_history` table.

Hard-coded numeric constants anywhere in application code are an architecture violation unless they are structural (DAG topology, table schemas, fixed layer counts) or genuinely invariant mathematical definitions (π, a fixed unit conversion, a physical constant).

The APR parameter lifecycle is:

```
seed → operator_tuning → ml_learned → user_override → ml_learned again
```

Every write is recorded in `config_history` with `changed_by` and `reason`. The full conversation between human judgment and empirical evidence is preserved.

---

## Infrastructure

Four tables, one service. All live. Zero new infrastructure required to use this system.

### Table Schemas

**`config_schema`** — schema registry; defines what keys exist and how to validate them.

| Column | Type | Description |
|--------|------|-------------|
| `config_key` | TEXT PRIMARY KEY | Full dotted key, e.g. `threshold.<component>.<param>` |
| `value_type` | TEXT NOT NULL | `'float'`, `'int'`, `'bool'`, `'json'`, `'str'` |
| `default_value` | TEXT | Seed value as string |
| `min_value` | FLOAT | Lower bound for numeric types |
| `max_value` | FLOAT | Upper bound for numeric types |
| `allowed_values` | TEXT[] | Explicit allowlist (used for bool, enum types) |
| `is_secret` | BOOL DEFAULT false | Redacted in logs and API responses |
| `version` | INT DEFAULT 1 | Schema version (rarely changes) |
| `description` | TEXT | Provenance tag + plain-language description + ML target flag |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |

**`config_state`** — live values; one row per key; the hot read surface.

| Column | Type | Description |
|--------|------|-------------|
| `config_key` | TEXT PRIMARY KEY | |
| `config_value` | TEXT NOT NULL | Current value as string — ConfigService parses to the typed value on read |
| `version` | INT NOT NULL | Incremented on every write; used for optimistic concurrency |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | |

**`config_history`** — immutable audit log; time-partitioned table (e.g. TimescaleDB hypertable); bounded retention.

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | TIMESTAMPTZ NOT NULL | Write time (partition dimension) |
| `config_key` | TEXT NOT NULL | |
| `version` | INT NOT NULL | Version at this write |
| `config_value` | TEXT NOT NULL | Value at this write |
| `changed_by` | TEXT NOT NULL | `'initial_estimate'`, `'user'`, `'ml_discovery'`, `'user_override'`, `'system'` |
| `reason` | TEXT | ML writes include `n=`, `bootstrap_ci_lower=`, `p=`; user writes include rationale |
| PK | `(timestamp, config_key, version)` | |

**`config_outbox`** — transactional outbox for propagating updates to a message bus; polled by a dispatcher process.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PRIMARY KEY | |
| `config_key` | TEXT NOT NULL | |
| `config_value` | TEXT NOT NULL | |
| `version` | INT NOT NULL | |
| `changed_at` | TIMESTAMPTZ DEFAULT NOW() | |
| `status` | TEXT DEFAULT `'pending'` | `'pending'` → `'dispatched'` after publish |
| `retry_count` | INT DEFAULT 0 | Incremented on transient failures |
| `next_attempt_at` | TIMESTAMPTZ | Backoff deadline; `NULL` means ready immediately |
| `created_at` | TIMESTAMPTZ DEFAULT NOW() | |

---

### How the Tables Interact

**Read flow:**

```
caller → ConfigService.get(key, default=X)
           │
           ├─ in-memory cache hit → return cached value  (zero DB I/O)
           │
           └─ cache miss → SELECT config_state JOIN config_schema
                             → parse string → type-safe value
                             → populate cache
                             → return value
```

The `default` fallback is returned only if the key is absent from `config_state` (e.g., before the seeding migration runs). It should always match the seed value in `config_state`.

Point-in-time query: `ConfigService.get_at(key, timestamp)` reads `config_history` and returns the value that was live at that moment — useful for backtests or replay that must reconstruct the parameter state at a past decision point.

**Write flow (one transaction, all-or-nothing):**

```
caller → ConfigService.set(key, value, changed_by=…, reason=…)
           │
           ├─ 1. validate key against a namespace allowlist (reject if unknown)
           ├─ 2. load config_schema → validate value against type/min/max/allowed_values
           ├─ 3. open transaction
           │       ├─ SELECT config_state FOR UPDATE (concurrency lock)
           │       ├─ check expected_version if provided (reject on mismatch)
           │       ├─ INSERT INTO config_history (timestamp, key, version+1, value, changed_by, reason)
           │       ├─ UPSERT config_state SET config_value=…, version=version+1
           │       └─ INSERT INTO config_outbox (key, value, version+1, status='pending')
           ├─ 4. commit — all three writes succeed or none do
           ├─ 5. invalidate in-memory cache for key
           └─ dispatcher (background) → publish to a "config updated" topic → message bus
```

**Hot reload:** Services subscribed to the config-update topic receive the update and invalidate their cache for that key. The next read re-fetches from `config_state` with the new value. No restart required.

**Concurrency:** `SELECT FOR UPDATE` inside the transaction prevents two concurrent writers from creating a split-brain. The `version` column enables optimistic locking: pass `expected_version=N` to reject the write if another writer updated the key between your read and your write.

---

### Access Patterns in Code

**Standard read at init (async):**

```python
value = await config_service.get("namespace.concept.param", default=fallback)
```

**Hot-path read after pre-warming (sync, zero I/O):**

```python
value = config_service.get_sync("namespace.concept.param", default=fallback)
```

**ML discovery write:**

```python
await config_service.set(
    "threshold.my_component.min_bars",
    learned_value,
    changed_by="ml_discovery",
    reason=f"n={n}, bootstrap_ci_lower={ci_lower:.3f}, p={p:.4f}",
)
```

---

## Namespace Convention

All keys follow `<domain>.<concept>.<param>`. The domain prefix groups parameters by functional area and determines which validation category the parameter belongs to. Maintain an authoritative allowlist of valid domain prefixes — a prefix absent from that list should reject runtime writes.

Example key structure (illustrative — your domains will differ):

```
threshold.<component>.<gate_name>     # float gate — ML discovery is the natural writer
feature.<indicator>.period            # int parameter — user or ML learning target
ui.<screen>.default_view              # str user preference — never an ML target
```

Maintain a single reference doc (e.g. `docs/platform-config.md`) listing the complete namespace registry — all prefixes, their natural writers, ML-target status, and live key counts. Don't duplicate that list here; this doc describes the mechanism, that doc describes current state.

---

## Parameter Lifecycle

Every parameter has the same lifecycle regardless of domain:

**1. Seed** -- committed in a migration with `changed_by = "initial_estimate"`. Description field documents provenance: `initial_estimate`, `rca_analysis`, or `conventional` (textbook value, not empirically validated for this specific context).

**2. User or operator preference** -- written from a dashboard or via `ConfigService.set(changed_by="user")`. Overrides the seed. History preserves the reason.

**3. ML-learned** -- a measurement process writes a new value after reaching significance (`p < 0.05`, `n >= N`). The old value is not deleted — it becomes history. The new value is live immediately via hot reload.

**4. Override** -- user or operator writes again if they disagree with the learned value. Written with `changed_by="user_override"`. The measurement process continues to monitor and may write again if the data is compelling.

This means the `config_history` table is a first-class record, not an audit footnote. It shows every step of the parameter's evolution. Point-in-time query via `ConfigService.get_at(key, timestamp)` should be implemented from day one, not deferred.

---

## `config_schema` Description Field Convention

The description field carries structured provenance. Always include:

- **Provenance tag** at the start: `[initial_estimate]`, `[rca_analysis]`, `[conventional]`, `[user_preference]`, `[learned]`
- **What the parameter controls** in plain language
- **Whether it is an ML learning target**
- **Context specificity note** if relevant (e.g. "not validated per segment/instrument/region")

Examples:

```
[initial_estimate] Minimum abs(score) to qualify for entry gate. Not empirically validated per segment. ML learning target.

[conventional] Lookback window. Standard 14-period convention -- not validated against outcome data for this context. ML learning target.

[user_preference] Default view shown on the dashboard. Not an ML learning target.

[rca_analysis] Minimum consecutive observations. Starting guess from root-cause analysis -- DB had no rows at calibration time. ML learning target.
```

**Calibration backlog:** keep a running doc that tracks which gate-shaped `[initial_estimate]` keys still need a real empirical study, so this doesn't require re-grepping all `config_schema` rows each time you audit. Update it when a key moves from guess to validated.

---

## Adding a New Parameter

**Step 1 -- Migration.** Insert into `config_schema` and `config_state`:

```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.my_component.my_param',
    'float',
    '0.5',
    0.0,
    1.0,
    '[initial_estimate] Description of what this controls. ML learning target.'
);

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.my_component.my_param', '0.5', 1);
```

**Step 2 -- Load in code.** Replace the hard-coded constant with a `ConfigService.get()` call at component init:

```python
# Before
my_threshold: float = 0.5

# After (load at init, store as instance attribute)
self.my_threshold = await config_service.get("threshold.my_component.my_param", default=0.5)
```

**Step 3 -- Remove the hard-coded constant.** No class-level default constants for parameters that live in the store.

**Step 4 -- Note in `config_schema` description** whether this is an ML learning target, so any automated calibration process knows to include it.

---

## Feature Indicator Periods (Naming Interaction)

Indicator periods are APR parameters. They are not schema elements.

This rule deserves its own section because the temptation to bake periods into column names is strong — `rsi_14` is readable, self-documenting, and obvious. It is also an architecture violation.

**Why the period cannot be in the column name:**

A column name is a schema element. Changing a column name requires an ALTER TABLE migration, a data backfill, and updates to every query and ORM that references it. If you later discover from measurement that a different period performs better, you cannot act on that finding without a schema migration. The schema has frozen a researcher's initial guess.

**The correct design:**

Column names encode the **concept and scale** — the researcher's hypothesis about what horizon to examine. The specific period is an APR parameter that a measurement engine can optimize:

```
Column:  rsi_fast          rsi_mid           rsi_slow
APR:     feature.period.rsi.fast = 7
         feature.period.rsi.mid  = 14
         feature.period.rsi.slow = 28
```

The compute layer reads the period from APR at compute time. When measurement shows a different period has higher predictive power, the APR value updates, a pipeline version bumps, and the compute layer recomputes for new rows — no schema change, no data ambiguity. Old rows carry the old pipeline version so downstream measurement can isolate the effect of the period change.

**The exception — when a number IS the concept:**

A column like `momentum_z_5` (5-period log return) is correct if the 5 defines the statistical quantity being measured, not a tunable parameter. A 5-period return and a 20-period return can be economically or semantically distinct concepts. Changing 5 to 7 would produce a different feature, not the same feature with a better calibration.

The test: if changing the number produces a **different concept**, it belongs in the column name. If changing it produces a **better calibration of the same concept**, it belongs in APR. See [naming-system.md §7](naming-system.md#7-gradient-scale-vocabulary) for the full naming-side treatment of this distinction.

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|---------------|-----|
| DB/message-bus connection strings | `.env` | Infra — requires restart, not runtime tunable |
| DAG topology (which components run) | Registration code | Structural — requires code deployment |
| Table/column schemas | Migration files | Structural — requires deployment |
| Layer/ring architecture | Core module structure | Structural invariant |
| Mathematical constants (π, fixed conversions) | Code | Not tunable |
| Numbers that define a statistical concept (`momentum_z_5`) | Column name | The number IS the feature |
| Per-user personalization | A dedicated user-preferences system | Requires user identity |

---

## Dashboard

A `/config/parameters`-style admin view — reads `config_state JOIN config_schema`, grouped by namespace prefix. Shows current value, type, bounds, description, last updated, version, and `changed_by`. Inline edit with optimistic update and version conflict detection.

For `config_history` detail: clicking any row should show the full change history for that key, including any automated-learning writes with their sample size and significance.

---

## Adopting This in a New Project

1. Copy the four table schemas and the read/write flow diagrams verbatim — the mechanism is domain-agnostic.
2. Replace every `threshold.<component>.<gate_name>`-style example with your own real namespace once you have a handful of parameters actually living in the store. Don't pre-populate this doc with invented namespaces.
3. Write your own namespace-registry doc (the `docs/platform-config.md` this doc points to) and keep it separate from this one — this doc is mechanism, that doc is current state, and they drift at different rates.
4. If your domain has no equivalent to "indicator period," delete the "Feature Indicator Periods" section rather than leaving a trading-specific example in a project that isn't trading.
