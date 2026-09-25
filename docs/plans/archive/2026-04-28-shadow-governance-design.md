# Shadow Governance System — Design Spec

**Date:** 2026-04-28
**Status:** Approved for implementation
**Scope:** Full Renaissance shadow system — automated promotion/demotion, unified protocol, naming cleanup

---

## Problem Statement

Three unrelated concepts share the word "shadow," causing confusion and preventing automation:

| Concept | Current form | Problem |
|---|---|---|
| ML feature capture | `signal["_shadow"]` dict in all I7 plugins | Misnamed — it's a training data snapshot, not shadow mode |
| Plugin evaluation gate | `IS_SHADOW: ClassVar[bool]` on I7 plugins | Manual promotion requires code change + redeploy; opt-in means new plugins skip evaluation by omission |
| Swarm evaluation gate | `shadow_only: bool = True` on `SwarmBaseAgent` | Different pattern, same concept — two protocols for one idea |
| Runtime shadow state | `SHADOW_PLUGINS: tuple[str, ...] = ()` in `weight_updater.py` | Hardcoded, manually maintained, currently empty |
| Promotion action | Log warning "human action required" | Antithetical to Renaissance principles |
| Gate parameters | `N_GATE = 100` hardcoded in Python | Cannot tune per-plugin without a deploy |

---

## Design Goals (Renaissance Principles)

1. **No manual steps.** Promotion and demotion run automatically when gate conditions are met.
2. **Earn the right through proof.** All new components enroll in shadow evaluation by default — opt-out, not opt-in.
3. **DB as source of truth.** Runtime shadow state lives in `shadow_registry`, not in class attributes or Python tuples.
4. **Per-component gate parameters.** Different signal frequencies and variance profiles warrant different thresholds.
5. **Immutable audit trail.** Every promotion and demotion is permanently logged with the exact statistics that triggered it.
6. **Unified protocol.** I7 plugins and swarm agents follow the same enrollment pattern.
7. **Clean naming.** ML feature capture and shadow evaluation gate are distinct concepts with distinct names.

---

## Concepts & Naming

| Old | New | What it is |
|---|---|---|
| `signal["_shadow"]` | `signal["features_snapshot"]` | Point-in-time ML training capture. I6 CTF scores, I4 macro, exhaustion state. Zero routing effect. No leading underscore — this data flows into the DB and is not transient. |
| `IS_SHADOW: ClassVar[bool]` on I7 plugins | `SHADOW_SKIP: ClassVar[bool] = True` | Rare opt-out for proven/grandfathered plugins. Absence of this flag = auto-enrolled. |
| `shadow_only: bool = True` on `SwarmBaseAgent` | `SHADOW_SKIP: ClassVar[bool] = True` | Same pattern, unified with I7. |
| Shadow runtime state (no single source) | `shadow_registry` table | DB is the authority. `is_shadow` column is current state. |

**Key conceptual shift:** Enrollment is automatic for all `TIER_I7` plugins and all `SwarmBaseAgent` subclasses. `SHADOW_SKIP = True` is the narrow exception for components that have already earned their place and don't need re-evaluation. New components can never accidentally skip the evaluation gate by omitting a flag.

---

## Data Model

### `shadow_registry` table (migration 076)

Source of truth for component shadow state and per-component gate parameters.

```sql
CREATE TABLE shadow_registry (
    component_name          TEXT PRIMARY KEY,
    component_type          TEXT NOT NULL CHECK (component_type IN ('i7_plugin', 'swarm_agent')),
    is_shadow               BOOLEAN NOT NULL DEFAULT TRUE,
    enrolled_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_at             TIMESTAMPTZ,
    demoted_at              TIMESTAMPTZ,
    -- Promotion gate (per-component tunable)
    min_n                   INTEGER NOT NULL DEFAULT 100,
    min_ev_r                FLOAT NOT NULL DEFAULT 0.0,
    ci_alpha                FLOAT NOT NULL DEFAULT 0.05,
    -- Demotion gate
    demotion_lookback_days  INTEGER NOT NULL DEFAULT 30,
    demotion_threshold_ev_r FLOAT NOT NULL DEFAULT -0.05,
    demotion_min_evaluations INTEGER NOT NULL DEFAULT 3,
    demotion_consecutive_count INTEGER NOT NULL DEFAULT 0,
    -- Stats at last evaluation
    last_eval_n             INTEGER,
    last_eval_ev_r          FLOAT,
    last_eval_ci_lower      FLOAT,
    last_eval_win_rate      FLOAT,
    last_eval_at            TIMESTAMPTZ
);
```

**`demotion_consecutive_count`**: incremented each evaluation where rolling EV[R] < `demotion_threshold_ev_r`; reset to 0 on any passing evaluation. Demotion fires when count reaches `demotion_min_evaluations`. Prevents noise-driven demotions.

### `shadow_transition_log` table (migration 076)

Immutable audit trail. Never updated — append only.

```sql
CREATE TABLE shadow_transition_log (
    id              BIGSERIAL PRIMARY KEY,
    component_name  TEXT NOT NULL,
    component_type  TEXT NOT NULL,
    from_state      TEXT NOT NULL CHECK (from_state IN ('shadow', 'live')),
    to_state        TEXT NOT NULL CHECK (to_state IN ('shadow', 'live')),
    triggered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trigger_reason  TEXT NOT NULL,
    n               INTEGER,
    ev_r            FLOAT,
    ci_lower        FLOAT,
    win_rate        FLOAT
);

CREATE INDEX ON shadow_transition_log (component_name, triggered_at DESC);
```

`trigger_reason` values: `promotion_gate_cleared`, `demotion_ev_r_degraded`.

---

## Architecture

```
[shadow_registry DB] ──read──▶  ShadowAuditorAgent  (timer, 30 min)
[signal_ledger DB]   ──read──▶         │
                                        ├──write──▶ shadow_registry (current state + demotion counter)
                                        ├──write──▶ shadow_transition_log (immutable event)
                                        ├──publish──▶ intelligence.shadow.transitions (Kafka)
                                        └──emit──▶ Prometheus SHADOW_* gauges

[IntelligencePipelineAgent]
  ├── startup: SELECT * FROM shadow_registry → _shadow_cache dict[str, bool]
  ├── every 5 min: background task refreshes _shadow_cache
  └── per-bar signal emit: _is_shadow(component_name) → cache lookup (no DB hit)

[SwarmOrchestratorAgent]
  └── startup: same cache load from shadow_registry for swarm_agent rows
```

**No new WriterAgent.** `ShadowAuditorAgent` reads and writes DB directly — consistent with the existing `indicagent-ml-data-quality`, `indicagent-ml-discovery`, and `indicagent-ml-orchestrator` timer pattern. The transition events go to Kafka for downstream consumers (dashboard, alerts); no streaming consumer is required for the auditor's own operation.

---

## New Components

### `src/core/stats_utils.py`

Shared statistical utilities extracted from `weight_updater.py`. Both `ShadowAuditorAgent` and `weight_updater` import from here.

```python
def bootstrap_ci_lower(pnl_r_values: list[float], alpha: float = 0.05, n_boot: int = 1000) -> float:
    """95% bootstrap CI lower bound on E[PnL_R]. Returns -inf on empty input."""
```

No other contents initially — grows as other shared stats utilities are identified.

### `services/shadow_auditor_agent.py`

Timer-based agent. Runs every 30 minutes (same cadence as weight update).

**Responsibilities:**
1. Load `shadow_registry` rows
2. For each component, query `signal_ledger` for resolved signals matching `component_name = setup_plugin`
3. **Promotion check** (only for `is_shadow = TRUE` components): if `n >= min_n` AND `bootstrap_ci_lower(pnl_r_values, ci_alpha) > min_ev_r` → promote
4. **Demotion check** (only for `is_shadow = FALSE` components): compute rolling EV[R] over `demotion_lookback_days`; if below `demotion_threshold_ev_r`, increment `demotion_consecutive_count`; if count reaches `demotion_min_evaluations` → demote; else reset counter
5. Write state changes to `shadow_registry`
6. Append to `shadow_transition_log`
7. Publish `ShadowTransitionEvent` to `intelligence.shadow.transitions`
8. Emit Prometheus metrics (existing `SHADOW_*` gauges — moved from `weight_updater.py`)

**Systemd units:** `indicagent-shadow-auditor.service` + `indicagent-shadow-auditor.timer`

### `ShadowTransitionEvent` in `src/intelligence/schemas.py`

```python
@dataclass
class ShadowTransitionEvent:
    component_name: str
    component_type: str   # 'i7_plugin' | 'swarm_agent'
    from_state: str       # 'shadow' | 'live'
    to_state: str         # 'shadow' | 'live'
    trigger_reason: str
    n: int
    ev_r: float
    ci_lower: float
    win_rate: float
    triggered_at: str     # UTC ISO-8601
```

### Kafka topic

`intelligence.shadow.transitions` — low volume (O(events/day) at most). Added to `stream_keys.py` as `topic_shadow_transitions(env_name)`.

---

## Auto-Enrollment Protocol

In `register_all_plugins()` (called at pipeline startup):

```python
for plugin_name in TIER_I7:
    plugin_cls = registry.get_plugin_class(plugin_name)
    if not getattr(plugin_cls, "SHADOW_SKIP", False):
        await shadow_registry_ensure(db, plugin_name, "i7_plugin")
```

`shadow_registry_ensure()`:
```python
INSERT INTO shadow_registry (component_name, component_type)
VALUES ($1, $2)
ON CONFLICT (component_name) DO NOTHING
```

Idempotent — never overwrites existing rows, so custom gate parameters tuned in DB are preserved across restarts. A plugin that clears the gate and has `is_shadow = FALSE` in DB keeps that state on restart.

Same pattern in `SwarmOrchestratorAgent` for swarm agents.

---

## Changes to Existing Code

### `src/intelligence/weight_updater.py`
- Remove `compute_shadow_plugin_stats()` entirely (moves to `shadow_auditor_agent.py`)
- Remove `SHADOW_PLUGINS` tuple
- Remove `_bootstrap_ci_lower()` (moves to `src/core/stats_utils.py`)
- Remove call to `compute_shadow_plugin_stats()` from `run_weight_update()`
- Import `bootstrap_ci_lower` from `src/core/stats_utils.py` for the weight update's own CI computations

### All I7 plugins (`src/intelligence/trading/*.py`)
- `signal["_shadow"] = capture_signal_features(...)` → `signal["features_snapshot"] = capture_signal_features(...)`
- `IS_SHADOW: ClassVar[bool] = False` → remove (plugin is live, not enrolled in shadow — default behavior)
- If a plugin should be in shadow for evaluation: no attribute needed (auto-enrolled by default)
- If a plugin should never be evaluated: add `SHADOW_SKIP: ClassVar[bool] = True`

### `src/intelligence/trading/confidence_utils.py`
- Docstring: update all references from `signal["_shadow"]` to `signal["features_snapshot"]`
- Function name `capture_signal_features()` unchanged — it's accurate

### `src/core/swarm/base_agent.py`
- Remove `shadow_only: bool = True` instance attribute
- Add `SHADOW_SKIP: ClassVar[bool] = False` class var (default = enrolled)
- `AgentResult.shadow_only` field: populated from `_shadow_cache` lookup at result construction time, not from class attribute

### `src/intelligence/swarm/aggregator.py`
- `any_shadow` computation reads from pipeline `_shadow_cache` rather than `result.shadow_only` class attribute

### `IntelligencePipelineAgent` (wherever signal emit lives)
- Add `_shadow_cache: dict[str, bool]` loaded from `shadow_registry` at startup
- Add 5-min background refresh task
- Replace `getattr(plugin_inst, "IS_SHADOW", False)` with `_is_shadow(plugin_name)`

### `src/intelligence/swarm/agents/` (all three: correlation, volume, skeptic)
- Remove `shadow_only = True` instance attribute
- These are auto-enrolled via `SwarmOrchestratorAgent` startup scan

---

## What Gets Deleted

| Item | Location | Replacement |
|---|---|---|
| `SHADOW_PLUGINS: tuple[str, ...] = ()` | `weight_updater.py` | `shadow_registry` table |
| `compute_shadow_plugin_stats()` | `weight_updater.py` | `shadow_auditor_agent.py` |
| `_bootstrap_ci_lower()` | `weight_updater.py` | `src/core/stats_utils.py` |
| `IS_SHADOW: ClassVar[bool]` | `dual_divergence.py` | removed (plugin is live) |
| `shadow_only: bool = True` | `SwarmBaseAgent` + 3 subclasses | `SHADOW_SKIP` pattern |
| "human action required" log warning | `weight_updater.py` | automated transition |
| `signal["_shadow"]` key | all 37 I7 plugins | `signal["features_snapshot"]` |

---

## Migration

**File:** `production/migrations/076_shadow_governance.sql`

Creates `shadow_registry` and `shadow_transition_log`. No data migration needed — `shadow_registry` starts empty and is populated by auto-enrollment on next pipeline startup.

---

## Testing

- Unit tests for `bootstrap_ci_lower()` in `tests/unit/test_stats_utils.py`
- Unit tests for `ShadowAuditorAgent` promotion/demotion logic with mock DB rows
- Unit tests for `shadow_registry_ensure()` idempotency
- Existing I7 plugin tests: update any assertions on `signal["_shadow"]` → `signal["features_snapshot"]`
- Integration: verify `features_snapshot` key present in emitted signals after restart

---

## Prometheus Metrics (unchanged, moved)

`SHADOW_N_RESOLVED`, `SHADOW_WIN_RATE`, `SHADOW_EV_R`, `SHADOW_EV_CI_LOWER`, `SHADOW_DAYS_TO_GATE`, `SHADOW_PROMOTION_READY` — same gauges, same label `plugin=`. Move from `weight_updater.py` to `shadow_auditor_agent.py`. No Grafana dashboard changes needed.

---

## CLAUDE.md Updates

- Remove stale "Shadow modes: CROSS_ASSET active; ROLL_MONITOR disabled; trad_DualDivergence IS_SHADOW=True"
- Add shadow governance section: `shadow_registry` as source of truth, `SHADOW_SKIP` opt-out, `ShadowAuditorAgent` cadence
- Update `features_snapshot` description in plugin system section
