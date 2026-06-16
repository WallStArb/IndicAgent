# Adaptive Parameter Registry (APR)

**Canonical name:** Adaptive Parameter Registry (APR)
**Informal alias:** param store (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current
**Last Updated:** 2026-06-16
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

| Component | Purpose |
|-----------|---------|
| `config_schema` | Schema registry: key, type, min, max, allowed_values, description |
| `config_state` | Current live values (one row per key) |
| `config_history` | Immutable audit log of every change: who, when, why |
| `config_outbox` | Kafka propagation via transactional outbox -- hot reload without restart |
| `ConfigService` | Transactional read/write with in-memory cache and validation |

**Access pattern for all callers:**

```python
value = await config_service.get("namespace.concept.param", default=fallback)
```

The `default` fallback keeps the system functional if the config DB is unavailable at startup. It should match the seed value in `config_state`.

**ML discovery write pattern (Level 3):**

```python
await config_service.set(
    "threshold.ofi_continuation.min_bars",
    learned_value,
    changed_by="ml_discovery",
    reason=f"n={n}, bootstrap_ci_lower={ci_lower:.3f}, p={p:.4f}",
)
```

The outbox broadcasts the change to `topic_config_updates`. Services subscribed to that topic hot-reload the value without restart. `config_history` captures full provenance.

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

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|---------------|-----|
| DB/Kafka connection strings | `.env` | INFRA -- requires restart, not runtime tunable |
| DAG topology (which plugins run) | `register_plugins.py` | STRUCT -- requires code deployment |
| Table/column schemas | Migration files | STRUCT -- requires deployment |
| Ring architecture | `src/core/` | Structural invariant |
| Mathematical constants (π, contract multipliers) | Code | Not tunable |
| Per-user personalization | Future user preferences system | Requires user identity |

---

## Dashboard

`/config/parameters` -- reads `config_state JOIN config_schema`, grouped by namespace prefix. Shows current value, type, bounds, description, last updated, version, and `changed_by`. Inline edit with optimistic update and version conflict detection.

For `config_history` detail: click any row to see the full change history for that key, including ML discovery writes with their sample size and p-value.

---

## Implementation Status

See `docs/platform/platform-config.md` for the live namespace registry: all prefixes, key counts, OPS_PREFIXES gaps, and activation instructions.
<!-- src: docs/platform/platform-config.md -->
