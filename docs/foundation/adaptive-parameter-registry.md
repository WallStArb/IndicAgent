# Adaptive Parameter Registry (APR)

**Canonical name:** Adaptive Parameter Registry (APR)
**Informal alias:** param store (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current
**Last Updated:** 2026-06-20
**Phase introduced:** 109 (infrastructure), extended Phase 121+ (plugin thresholds), Phase 125 (full migration)

---

## What It Is

The **Adaptive Parameter Registry (APR)** is the system-wide home for all tunable numeric values — detection thresholds, indicator periods, confidence weights, governance gates, and UX preferences. Every value that a human operator, ML discovery, or user might want to change without a code deployment lives here.

"Adaptive" is the key distinction from a generic config store: APR parameters are not static configuration. They start as `[initial_estimate]` or `[conventional]` human opinions and evolve through evidence — ML discovery writes calibrated values back after sufficient sample sizes and p < 0.05. The full conversation between human judgment and empirical evidence is preserved in `config_history`.

Hard-coded numeric constants anywhere in `src/` are an architecture violation unless they are structural (DAG topology, table schemas, ring counts) or genuinely invariant mathematical definitions (π, tick size, contract multipliers).

The APR parameter lifecycle is:

```
seed → operator_tuning → ml_learned → user_override → ml_learned again
```

Every write is recorded in `config_history` with `changed_by` and `reason`. The full conversation between human judgment and empirical evidence is preserved.

### Relationship to the ECL

The Adaptive Parameter Registry and the Extrinsic Confidence Layer (ECL) are complementary systems:

- **ECL** — governs what extrinsic context vectors (CTF score, HMM regime weight) travel on signals as observable metadata. Defines the boundary between intrinsic confidence and extrinsic annotation.
- **APR** — governs the numeric thresholds and weights that control signal generation. Makes those thresholds visible and learnable by the ML optimization loop.

ECL vectors like `threshold.global.min_ctf_score` and `threshold.global.min_regime_weight` live in the APR — they are observable APR parameters, not hard-coded opinions.

---

## Infrastructure

Four tables, one service. All live. Zero new infrastructure required to use this system.
<!-- src: db/migrations/109_config_foundation.sql -->

### Table Schemas

**`config_schema`** — schema registry; defines what keys exist and how to validate them.

| Column | Type | Description |
|--------|------|-------------|
| `config_key` | TEXT PRIMARY KEY | Full dotted key, e.g. `threshold.ofi_continuation.min_bars` |
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
| `config_value` | TEXT NOT NULL | Current value as string — ConfigService parses to Python type on read |
| `version` | INT NOT NULL | Incremented on every write; used for optimistic concurrency |
| `updated_at` | TIMESTAMPTZ DEFAULT NOW() | |

**`config_history`** — immutable audit log; TimescaleDB hypertable; 1-year retention.

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | TIMESTAMPTZ NOT NULL | Write time (hypertable partition dimension) |
| `config_key` | TEXT NOT NULL | |
| `version` | INT NOT NULL | Version at this write |
| `config_value` | TEXT NOT NULL | Value at this write |
| `changed_by` | TEXT NOT NULL | `'initial_estimate'`, `'user'`, `'ml_discovery'`, `'user_override'`, `'system'` |
| `reason` | TEXT | ML writes include `n=`, `bootstrap_ci_lower=`, `p=`; user writes include rationale |
| PK | `(timestamp, config_key, version)` | |

**`config_outbox`** — transactional outbox for Kafka propagation; polled by `OutboxDispatcher`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL PRIMARY KEY | |
| `config_key` | TEXT NOT NULL | |
| `config_value` | TEXT NOT NULL | |
| `version` | INT NOT NULL | |
| `changed_at` | TIMESTAMPTZ DEFAULT NOW() | |
| `status` | TEXT DEFAULT `'pending'` | `'pending'` → `'dispatched'` after Kafka publish |
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

Point-in-time query: `ConfigService.get_at(key, timestamp)` reads `config_history` and returns the value that was live at that moment — used by backtests and replay to reconstruct the parameter state at signal fire time.

**Write flow (one transaction, all-or-nothing):**

```
caller → ConfigService.set(key, value, changed_by=…, reason=…)
           │
           ├─ 1. validate key against OPS_PREFIXES (raises ConfigValidationError if not OPS)
           ├─ 2. load config_schema → validate value against type/min/max/allowed_values
           ├─ 3. open transaction
           │       ├─ SELECT config_state FOR UPDATE (concurrency lock)
           │       ├─ check expected_version if provided (raises ConfigVersionConflict on mismatch)
           │       ├─ INSERT INTO config_history (timestamp, key, version+1, value, changed_by, reason)
           │       ├─ UPSERT config_state SET config_value=…, version=version+1
           │       └─ INSERT INTO config_outbox (key, value, version+1, status='pending')
           ├─ 4. commit — all three writes succeed or none do
           ├─ 5. invalidate in-memory cache for key
           └─ OutboxDispatcher (background) → publish to topic_config_updates → Kafka
```

**Hot reload:** Services subscribed to `topic_config_updates` receive the update and call `config_service.invalidate(key)`. The next `get()` call re-fetches from `config_state` with the new value. No restart required.

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
    "threshold.ofi_continuation.min_bars",
    learned_value,
    changed_by="ml_discovery",
    reason=f"n={n}, bootstrap_ci_lower={ci_lower:.3f}, p={p:.4f}",
)
```

---

## Namespace Convention

All keys follow `<domain>.<concept>.<param>`. The domain prefix groups parameters by functional area and determines which OPS category the parameter belongs to. `ConfigService.OPS_PREFIXES` is the authoritative list of valid prefixes — a prefix absent from this tuple will reject runtime writes with `ConfigValidationError`.

Example key structure (three representative examples):

```
threshold.trend_following.regime_min    # float gate — ML discovery is the natural writer
feature.rsi.period                      # int indicator period — user or ML learning target
ui.signals.default_timeframe            # str user preference — never an ML target
```

For the complete namespace registry — all prefixes, their natural writers, ML target status, and live key counts — see `docs/platform/platform-config.md`.
<!-- src: docs/platform/platform-config.md -->

---

## Parameter Lifecycle

Every parameter has the same lifecycle regardless of domain:

**1. Seed** -- committed in a migration with `changed_by = "initial_estimate"`. Description field documents provenance: `initial_estimate`, `rca_analysis`, or `conventional` (textbook value, not empirically validated for this instrument/regime).

**2. User or operator preference** -- written from the dashboard or via `ConfigService.set(changed_by="user")`. Overrides the seed. History preserves the reason.

**3. ML-learned** -- ML discovery writes a new value after reaching significance (`p < 0.05`, `n >= N`). The old value is not deleted -- it becomes history. The new value is live immediately via Kafka hot reload.

**4. Override** -- user or operator writes again if they disagree with the learned value. Written with `changed_by="user_override"`. ML discovery continues to monitor and may write again if the data is compelling.

This means the `config_history` table is a first-class record, not an audit footnote. It shows every step of the parameter's evolution. Point-in-time query via `ConfigService.get_at(key, timestamp)` is already implemented.

---

## `config_schema` Description Field Convention

The description field carries structured provenance. Always include:

- **Provenance tag** at the start: `[initial_estimate]`, `[rca_analysis]`, `[conventional]`, `[user_preference]`, `[learned]`
- **What the parameter controls** in plain language
- **Whether it is an ML learning target**
- **Instrument/regime specificity note** if relevant

Examples:

```
[initial_estimate] Minimum abs(trend_regime) to qualify for TrendFollowingPlugin. Not empirically validated per instrument. ML learning target.

[conventional] RSI lookback period. Standard 14-bar convention -- not validated against outcome data for ES/NQ. ML learning target.

[user_preference] Default timeframe shown in signals screen. Not an ML learning target.

[rca_analysis] Minimum consecutive OFI bars. Phase 118 RCA starting guess -- DB had no rows at calibration time. ML learning target.
```

---

## Adding a New Parameter

**Step 1 -- Migration.** Insert into `config_schema` and `config_state`:

```sql
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description)
VALUES (
    'threshold.my_plugin.my_param',
    'float',
    '0.5',
    0.0,
    1.0,
    '[initial_estimate] Description of what this controls. ML learning target.'
);

INSERT INTO config_state (config_key, config_value, version)
VALUES ('threshold.my_plugin.my_param', '0.5', 1);
```

**Step 2 -- Load in code.** Replace the hard-coded constant with a `ConfigService.get()` call at plugin or service init:

```python
# Before
my_threshold: float = 0.5

# After (load at init, store as instance attribute)
self.my_threshold = await config_service.get("threshold.my_plugin.my_param", default=0.5)
```

**Step 3 -- Remove the hard-coded constant.** No class-level default constants for parameters that live in the store.

**Step 4 -- Note in `config_schema` description** whether this is an ML learning target, so ML discovery knows to include it.

---

## Feature Indicator Periods

Indicator periods are APR parameters. They are not schema elements.

This rule deserves its own section because the temptation to bake periods into column names is strong — `rsi_14` is readable, self-documenting, and obvious. It is also an architecture violation.

**Why the period cannot be in the column name:**

A column name is a schema element. Changing a column name requires an ALTER TABLE migration, a data backfill, and updates to every query and ORM that references it. If you later discover from IC measurement that `rsi_21` has higher IC Sharpe than `rsi_14` on ETFs at 1h, you cannot act on that finding without a schema migration. The schema has frozen a researcher's initial guess.

**The correct design:**

Column names encode the **concept and scale** — the researcher's hypothesis about what temporal horizon to examine. The specific period is an APR parameter that the IC Engine can optimize:

```
Column:  rsi_fast          rsi_mid           rsi_slow
APR:     feature.period.rsi.fast = 7
         feature.period.rsi.mid  = 14
         feature.period.rsi.slow = 28
```

FeatureFactory reads the period from APR at compute time. When IC measurement shows a different period has higher predictive power, the APR value updates, `pipeline_version` bumps, and FeatureFactory recomputes for new bars — no schema change, no data ambiguity. Old bars carry the old `pipeline_version` so the IC Engine can isolate the effect of the period change.

**The exception — when a number IS the concept:**

`momentum_z_5` (5-bar log return) is correct. The 5 defines the statistical quantity being measured, not a tunable parameter. A 5-bar return and a 20-bar return are economically distinct concepts (scalping horizon vs. swing horizon). Changing 5 to 7 would produce a different feature, not the same feature with a better calibration.

The test: if changing the number produces a **different concept**, it belongs in the column name. If changing it produces a **better calibration of the same concept**, it belongs in APR.

**v3.0 `feature.period.*` namespace:**

| APR key                    | Controls                             | ML target |
|----------------------------|--------------------------------------|-----------|
| `feature.period.rsi.fast`  | RSI period for fast-scale column     | Yes       |
| `feature.period.rsi.mid`   | RSI period for mid-scale column      | Yes       |
| `feature.period.rsi.slow`  | RSI period for slow-scale column     | Yes       |
| `feature.period.cci.fast`  | CCI period for fast-scale column     | Yes       |
| `feature.period.cci.mid`   | CCI period for mid-scale column      | Yes       |
| `feature.period.cci.slow`  | CCI period for slow-scale column     | Yes       |
| `feature.period.aroon.fast`| Aroon period for fast-scale column   | Yes       |
| `feature.period.aroon.slow`| Aroon period for slow-scale column   | Yes       |

All are ML learning targets. IC Engine measures IC at the current period, proposes an optimized period, and writes back via APR after significance gate (`n >= 500`, `p < 0.05`).

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|---------------|-----|
| DB/Kafka connection strings | `.env` | INFRA -- requires restart, not runtime tunable |
| DAG topology (which plugins run) | `register_plugins.py` | STRUCT -- requires code deployment |
| Table/column schemas | Migration files | STRUCT -- requires deployment |
| Ring architecture | `src/core/` | Structural invariant |
| Mathematical constants (π, contract multipliers) | Code | Not tunable |
| Numbers that define a statistical concept (`momentum_z_5`) | Column name | The number IS the feature |
| Per-user personalization | Future user preferences system | Requires user identity |

---

## Dashboard

`/config/parameters` -- reads `config_state JOIN config_schema`, grouped by namespace prefix. Shows current value, type, bounds, description, last updated, version, and `changed_by`. Inline edit with optimistic update and version conflict detection.

For `config_history` detail: click any row to see the full change history for that key, including ML discovery writes with their sample size and p-value.

---

## Implementation Status

See `docs/platform/platform-config.md` for the live namespace registry: all prefixes, key counts, OPS_PREFIXES gaps, and activation instructions.
<!-- src: docs/platform/platform-config.md -->
