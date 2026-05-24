# Phase 106: Foundation Hardening - Research

**Researched:** 2026-05-23
**Domain:** Architecture hardening — observability, DAG correctness, dead code removal, plugin circuit breakers, queue backpressure, state manager scaling
**Confidence:** HIGH — all findings verified against live source files

---

## Summary

Phase 106 is the structural hardening pass that follows Phase 105's acute bug-fix sprint. Phase 105 has NOT yet been executed (no SUMMARY files exist in `.planning/phases/phase-105/`). All Phase 105 target bugs are still present in source (confirmed by grep). This creates the critical overlap concern: several items in the rough 106-01 through 106-06 plans duplicate work that Phase 105 PLANS to do. The planner must correctly sequence Phase 105 before Phase 106, and must not include Phase 105 work in Phase 106 plans.

After deduplication, Phase 106 retains six distinct work areas: (1) per-stage tier latency histograms and a single `observed_span` on `_process_bar_inner` — the only observability item NOT covered by Phase 105; (2) DAG correctness — 9 services missing from `_DAG_ORDER`, 3 systemd unit file wiring bugs, key mismatches; (3) code reuse fixes — `bar_aggregator` manual retry loop, 3 JSONB `asyncpg.create_pool` bypasses, `BaseWriterAgent._teardown()` auto-close hooks; (4) dead code removal — `ShadowRecorder` (archived stub), `GuardrailsValidator` (zero schemas loaded), 6 dead Settings fields, TEMPLATE agent audit bypass; (5) PluginCircuitBreaker wiring — currently passes `circuit_breakers={}` to the executor; (6) queue backpressure and `PluginStateManager` O(N) scan.

**Primary recommendation:** Execute Phase 105 first. Phase 106 plans must explicitly `depends_on` Phase 105 completion where they touch the same files (`intelligence_pipeline_agent.py`, `shadow_auditor_agent.py`, `metrics.py`, `bar_writer_agent.py`, `ctx_writer_agent.py`, `llm_writer_service.py`).

---

## Phase 105 vs Phase 106 Overlap Analysis

This is the critical deduplication. Phase 105 has no SUMMARY files — all bugs are still present in source as of 2026-05-23.

### Items Phase 105 Already Plans (DROP from Phase 106)

| Rough 106 Plan | Item | Phase 105 Plan That Covers It |
|----------------|------|-------------------------------|
| 106-01 Task 1 | Shadow metrics `create_up_down_counter` → `create_gauge` in `metrics.py` | 105-03 Task 1 |
| 106-01 Task 1 | Shadow auditor `.add()` → `.set()` call sites in `shadow_auditor_agent.py` | 105-04 Task 3 |
| 106-01 Task 1 | Pipeline latency instruments → `create_histogram` + `.record()` wiring | 105-03 Task 2 |
| 106-01 Task 1 | `bars_processed` + `pipeline_errors` → monotonic counters | 105-03 Task 2 |
| 106-01 Task 1 | `agent_id` label key in `base.py` `_last_msg_ts_attrs` / `_crash_attrs` | 105-03 Task 2 (via agent_id standardization) |
| 106-01 Task 1 | `BarWriterAgent._run()` calls `_record_message_consumed()` | 105-02 Task 2 (HF-7) |
| 106-03 Task 2 | `ctx_writer_agent._teardown()` calls `super()._teardown()` first | 105-01 Task 1 (HF-11) |
| 106-03 Task 2 | `llm_writer_service` stall watchdog reads `_last_message_ts` | 105-01 Task 2 (HF-6) |
| 106-03 Task 2 | `llm_writer_service._process_loop()` calls `_record_message_consumed()` | 105-01 Task 2 (HF-6) |
| 106-03 Task 2 | `llm_writer_service` uptime gauge `.add()` → `.set()` | 105-01 Task 2 (HF-3 companion) |

**Finding:** Rough 106-01 Task 1 is almost entirely duplicate of Phase 105-03 and 105-04. Rough 106-03 Task 2 duplicates 105-01. These must be DROPPED from Phase 106 plans.

### Items That Genuinely Remain for Phase 106

| Rough 106 Plan | Item | Status in Source | Confidence |
|----------------|------|-----------------|------------|
| 106-01 Task 2 | Per-stage tier latency histograms (`intelligence_pipeline_tier_latency_ms`) | Not present in `feature_pipeline_executor.py` | HIGH |
| 106-01 Task 2 | `observed_span("pipeline.process_bar_inner")` on hot path | Not present in `intelligence_pipeline_agent.py` | HIGH |
| 106-02 Task 1 | systemd unit file wiring (intelligence-pipeline After=, alerting/dlq redpanda-ready) | Still broken (not touched by 105) | HIGH |
| 106-02 Task 2 | 9 services missing from `_DAG_ORDER` | Confirmed missing (see below) | HIGH |
| 106-02 Task 2 | `_AGENT_ID_TO_UNIT` key `"feature_writer"` → `"feature_writer_agent"` | Line 130 confirmed wrong | HIGH |
| 106-02 Task 2 | `_LAG_THRESHOLDS` missing `graduation-compute` and `roll-compute` | Confirmed absent | HIGH |
| 106-02 Task 2 | `roll-compute` priority 8 — should be 3 per audit | Currently priority 8 in `_DAG_ORDER` | HIGH |
| 106-03 Task 1 | `bar_aggregator` manual retry loop — needs `circuit_breaker=True` | Manual `_MAX_ATTEMPTS` loop at lines 208-260 | HIGH |
| 106-03 Task 1 | 3 JSONB `asyncpg.create_pool` bypasses (swarm_ledger, bar_replay, signal_replay) | All three confirmed using `asyncpg.create_pool` directly | HIGH |
| 106-03 Task 2 | `BaseWriterAgent._teardown()` `hasattr` auto-close guards | Not present in base_writer | HIGH |
| 106-04 Task 1 | `ShadowRecorder` deletion | File exists; class raises deprecation warning; zero active callers | HIGH |
| 106-04 Task 1 | `GuardrailsValidator` + dead chain.py branch | File exists, imported in chain.py; zero schemas loaded | HIGH |
| 106-04 Task 1 | 6 dead Settings fields removal | Fields confirmed in settings.py; most have zero callers (SWARM_QUEUE_TIMEOUT_MS has one test caller) | HIGH |
| 106-04 Task 2 | `TEMPLATE_agent.py` calls `self._llm.generate()` bypassing audit trail | Confirmed at `src/intelligence/ai/TEMPLATE_agent.py:78` | HIGH |
| 106-04 Task 2 | `BaseAIAgent.__init__` missing `self._llm: LLMProviderChain | None = None` | Not declared in `__init__` | HIGH |
| 106-04 Task 2 | `_on_guardrail_violation` and `_audit_payload` dead hooks | Defined in base_agent.py; no subclass overrides found | HIGH |
| 106-05 Task 1 | `PluginCircuitBreaker` wiring into pipeline executor | `circuit_breakers={}` at line 284 — confirmed empty dict | HIGH |
| 106-06 Task 1 | `enqueue_blocking` for intel topic (line 507) and journal topic (line 598) | Both confirmed using non-blocking `enqueue` | HIGH |
| 106-06 Task 2 | `PluginStateManager.get_all_states_for()` O(N) linear scan | Confirmed dict comprehension at line 100 | HIGH |

---

## Current Source State (Verified)

### Observability (Phase 106 scope — NOT in Phase 105)

**Per-stage tier latency:** `src/intelligence/pipeline/feature_pipeline_executor.py` has no tier latency histogram. The hot path has five tiers (I1, I2-I3 wave, I4, I5+SMC, I6) — none timed with OTel histograms.

**`observed_span` on `_process_bar_inner`:** `services/intelligence_pipeline_agent.py` imports `observed_span` but does not wrap `_process_bar_inner`. Current latency is only measurable at the aggregate level after Phase 105 adds `.record()` wiring.

**What Phase 105 covers:** Shadow metrics → `create_gauge`, pipeline latency → `create_histogram`, `.record()` wiring, `agent_id` label. These are Phase 105 tasks; Phase 106 tier latency plan (106-01 Task 2) depends on Phase 105's histogram infrastructure.

### DAG Correctness

**Services missing from `_DAG_ORDER` (verified by comparing deployed units vs dict):**

| Service | Should Be Priority | Notes |
|---------|-------------------|-------|
| `indicagent-api` | 10 | Always-on top-level |
| `indicagent-dashboard` | 10 | Always-on top-level |
| `indicagent-ml-data-quality` | 8 | Timer-triggered oneshot |
| `indicagent-ml-discovery` | 8 | Timer-triggered oneshot |
| `indicagent-ml-orchestrator` | 8 | Timer-triggered oneshot |
| `indicagent-redpanda-ready` | 0 | Infrastructure sentinel |
| `indicagent-redpanda-watchdog` | 0 | Infrastructure sentinel |
| `indicagent-shadow-auditor` | 8 | Timer-triggered oneshot |
| `indicagent-weight-updater` | 8 | Timer-triggered oneshot |

Note: The rough 106-02 plan listed `indicagent-hmm-training` and `indicagent-feature-validation` as missing. These are NOT present in the live system (not in `systemctl list-units`). Do not add phantom entries.

**`_AGENT_ID_TO_UNIT` mismatch:** Line 130 has `"feature_writer": "indicagent-feature-writer"`. The agent's `name=` arg is `"feature_writer_agent"` — the key must match.

**`_LAG_THRESHOLDS` missing:** `indicagent-graduation-compute` and `indicagent-roll-compute` are in `_DAG_ORDER` but absent from `_LAG_THRESHOLDS`. Both are Kafka consumers and need thresholds.

**Priority order issue:** `indicagent-roll-compute` is at priority 8 (analytics batch). The audit (D-10) argues it should be at priority 3 because roll events trigger contract metadata updates and ibkr-provider restarts — it must be ready before the intelligence pipeline. However, `roll-compute` is a timer-triggered oneshot — it runs once per contract roll, not continuously. Moving it to priority 3 means the service auditor restart logic would restart it before intelligence-pipeline, which is incorrect for a oneshot. This is a judgment call; the safer fix is leaving priority at 8 and adding a comment, since the auditor's graduated restart loop (which uses priorities) should skip oneshot services anyway.

**Systemd unit files (not changed by Phase 105):**
- `indicagent-intelligence-pipeline.service`: `After=` still references non-existent `indicagent-bar-aggregator-compute.service` (confirmed by rough 106-02 plan; Phase 105 does not touch systemd files)
- `indicagent-alerting-agent.service` and `indicagent-dlq-drain.service`: Still depend on non-existent `redpanda.service` rather than `indicagent-redpanda-ready.service`
- `production/systemd/indicagent-bar-aggregator.service`: No versioned reference file exists

### Code Reuse

**`bar_aggregator_agent.py`:** Manual retry loop with `_MAX_ATTEMPTS = 4` and `_BASE_DELAY = 2.0` at lines 208-260. `BaseAgent` has `circuit_breaker = True` class attribute support for `_setup_with_retry()`. Adding the class attribute removes the custom loop.

**JSONB bypasses:** Three services call `asyncpg.create_pool()` directly instead of the `create_pool` wrapper in `database_manager.py` (which registers JSONB codecs and emits pool gauges):
- `services/swarm_ledger_writer_agent.py:89`
- `services/bar_replay_provider_agent.py:60`
- `services/signal_replay_auditor_agent.py:69`

**`BaseWriterAgent._teardown()` auto-close:** Currently no `hasattr` guards for `_consumer`, `_db`, or `_pool`. Services that override `_teardown()` without calling `super()._teardown()` (which Phase 105 fixes for ctx_writer) leave connections open.

### Dead Code

**`ShadowRecorder` (`src/core/ml/shadow.py`):** Class header says "ARCHIVED in Phase 78 (D-04)". The class body raises a `DeprecationWarning` on instantiation. Zero callers in `src/` or `services/`. `src/core/ml/__init__.py:12` documents the removal. Safe to delete.

**`GuardrailsValidator` (`src/core/llm/guardrails.py`):** 53-line file. Imported in `chain.py:17` and instantiated as `_guardrails = GuardrailsValidator()` at `chain.py:37`. The chain docstring at line 3 mentions it. However, the validator's `_schemas` dict is never populated in any code path (the `register_schema()` method exists but is never called), so `has_schema()` always returns `False` and the validation branch is dead. The import and `_guardrails` instance exist but have no effect. Chain.py comment says "GuardrailsValidator" in the composition list, but the actual validation path is a no-op.

**Dead Settings fields:** The following fields in `src/config/settings.py` have zero callers outside of `settings.py` itself:
- `LLM_RATE_LIMIT_RPM` — zero callers
- `LLM_RATE_LIMIT_TPM` — zero callers
- `SHADOW_CORRELATION_THRESHOLD` — zero callers
- `SHADOW_MIN_SAMPLES` — zero callers (the shadow auditor uses its own constants)
- `LANGFUSE_HOST` — zero callers
- `MLFLOW_TRACKING_URI` — zero callers (ml_training_compute_agent uses `_MLFLOW_TRACKING_URI` local constant at line 63)
- `SWARM_QUEUE_TIMEOUT_MS` — has ONE caller in `tests/unit/services/test_alpha_swarm_agent.py:570` (used as a constructor kwarg in test fixtures). Must verify whether the Settings field is used in production code before removing.

**TEMPLATE agent:** `src/intelligence/ai/TEMPLATE_agent.py:78` calls `self._llm.generate(...)` directly, bypassing the `_llm_generate()` audit trail wrapper in `BaseAIAgent`. Every agent copied from this template will silently bypass the LLM audit log.

**`BaseAIAgent.__init__`:** Does not declare `self._llm: LLMProviderChain | None = None`. Subclasses that fail to wire `_llm` in `_setup()` get `AttributeError` at the first LLM call instead of a clear `RuntimeError`.

**Dead hooks in `base_agent.py`:**
- `_on_guardrail_violation(self, output: AgentOutput) -> None: pass` — no subclass overrides found
- `_audit_payload(self) -> dict: return {}` — no subclass overrides found

### PluginCircuitBreaker

**Location:** `src/core/plugin_circuit_breaker.py` — 584-line file. Class `PluginCircuitBreaker` at line 89.

**Current usage in pipeline:** `services/intelligence_pipeline_agent.py:284` passes `circuit_breakers={}` to `PluginExecutor`. The dict is always empty — no plugin has a circuit breaker assigned.

**Existing usage elsewhere:** Already used for IBKR connection (`src/providers/ibkr.py:105`) and LLM providers (`src/core/llm/providers.py:48,61`). The class is functional; only the pipeline wiring is missing.

**What's needed:**
1. Add `enabled: bool` flag to `PluginCircuitBreaker.__init__` (shadow mode — transparent when `False`)
2. Add `PLUGIN_CB_ENABLED` env var for global enable
3. Add OTel gauge for state export (`intelligence_pipeline_plugin_cb_state`)
4. Add `structlog.warning` on state transition to open
5. Populate `circuit_breakers` dict from plugin registry at `_setup()` time
6. Verify `PluginExecutor` uses the dict (already has `_get_plugin_cb()` or equivalent)

**Note on wave ordering:** Plan 106-05 depends on Plan 106-01 (histogram infrastructure from 106-01 is needed for the OTel gauge in the circuit breaker). But 106-01 Task 2 (tier latency + observed_span) does NOT depend on 106-01 Task 1 (which is now Phase 105 scope). The wave 2 dependency for 106-05 remains valid if it depends on Phase 105 completion + 106-01 Task 2.

### Queue Backpressure and State Manager

**Enqueue calls in `intelligence_pipeline_agent.py`:**
- Line 507: `self._out_queue.enqueue(intel_topic, ...)` — non-blocking, drops silently under pressure
- Line 598: `self._out_queue.enqueue(...)` — journal topic, also non-blocking
- Lines 529-537: Signal enqueue calls already use `enqueue_blocking` — correct, leave alone

**`OutputQueue` API:** Both `enqueue()` (non-blocking) and `enqueue_blocking()` (async, awaitable) exist in `src/intelligence/pipeline/output_queue.py`. No `size()` method currently (needs to be added for the queue depth gauge).

**`PluginStateManager.get_all_states_for()`:** Line 100 uses a dict comprehension scanning all `_plugin_states` entries. At 58 symbols with 132 plugins this is tolerable; at 116 symbols it doubles. The secondary `_states_by_key` index is not present in `__init__` (line 71 only declares `_plugin_states`).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB connection pool with JSONB | Direct `asyncpg.create_pool()` | `database_manager.create_pool` wrapper | Registers JSONB codecs, emits pool gauges |
| Service retry on setup failure | Manual `_MAX_ATTEMPTS` loop | `circuit_breaker = True` class attr on `BaseAgent` | Shared backoff schedule, no thundering herd |
| Per-service teardown close | Custom consumer/pool close in each service | `BaseWriterAgent._teardown()` auto-close hooks | Prevents double-close errors, consistent |
| Plugin-level circuit breaking | Custom per-plugin failure tracking | `PluginCircuitBreaker` (already exists) | 584 lines of tested logic already in place |

---

## Common Pitfalls

### Pitfall 1: Phase 105 / Phase 106 file overlap
**What goes wrong:** Plans for both phases modify the same files. If Phase 106 plans are written without the overlap analysis, agents executing them will either re-apply already-done fixes (idempotent but wasteful) or conflict with pending Phase 105 changes.
**How to avoid:** Phase 106 plans that touch `intelligence_pipeline_agent.py`, `metrics.py`, `shadow_auditor_agent.py`, `bar_writer_agent.py`, `ctx_writer_agent.py`, `llm_writer_service.py` must `depends_on` Phase 105 completion.

### Pitfall 2: Oneshot services in _ONESHOT_UNITS
**What goes wrong:** Adding timer-triggered oneshot services (weight-updater, shadow-auditor, ml-orchestrator, etc.) to `_DAG_ORDER` without guarding the graduated restart loop causes the auditor to restart them on its schedule instead of letting systemd timers control them.
**How to avoid:** Add a `_ONESHOT_UNITS` frozenset (or check if one exists). Guard the restart call with `if unit_name in _ONESHOT_UNITS: continue`.

### Pitfall 3: SWARM_QUEUE_TIMEOUT_MS has a test caller
**What goes wrong:** Deleting `SWARM_QUEUE_TIMEOUT_MS` from settings.py breaks `tests/unit/services/test_alpha_swarm_agent.py:570` which passes it as a constructor kwarg.
**How to avoid:** Before removing this field, verify whether `alpha_swarm_agent` actually reads `settings.SWARM_QUEUE_TIMEOUT_MS` in production code. If yes, keep the field. If no (test is passing a dead kwarg), remove both the field and the test usage.

### Pitfall 4: GuardrailsValidator import in chain.py
**What goes wrong:** Deleting `guardrails.py` without removing the import and `_guardrails` usage from `chain.py` causes an import error at startup that kills all LLM operations.
**How to avoid:** Plan 106-04 Task 1 correctly specifies: remove the import, remove the `_guardrails.has_schema()` dead branch from `_generate_inner()`, then delete the file. The order matters.

### Pitfall 5: PluginCircuitBreaker circular import
**What goes wrong:** Adding `from src.observability.metrics import _meter` in `plugin_circuit_breaker.py` may create a circular import if `metrics.py` imports anything from the plugin system.
**How to avoid:** Use `opentelemetry.metrics.get_meter("indicagent")` directly in `plugin_circuit_breaker.py` instead of importing `_meter`. The meter is a singleton — getting it multiple times is safe.

### Pitfall 6: _states_by_key checkpoint restore
**What goes wrong:** Serializing `_states_by_key` to the checkpoint file creates a duplicate of `_plugin_states` data. On restore, both are loaded but only `_plugin_states` is authoritative.
**How to avoid:** `_states_by_key` must NOT be serialized. After loading `_plugin_states` from checkpoint, rebuild `_states_by_key` in a loop. The rough 106-06 plan has this correct.

---

## Architecture Patterns

### Phase Dependency Model
```
Phase 105 (must execute first)
  105-01: ctx_writer + llm_writer fixes
  105-02: feature_writer + bar_writer + swarm_ledger fixes
  105-03: metrics.py shadow gauges + pipeline histograms
  105-04: executor is_shadow stamp + signal_processor filter + shadow_auditor .set()
  105-05: regression tests + full suite green

Phase 106 (depends on 105 completion for files it shares)
  Wave 1 (parallel, no 106 dependencies):
    106-01: Tier latency histograms + observed_span (depends on 105-03 histogram infra)
    106-02: DAG correctness + systemd unit files (independent)
    106-03: Code reuse — bar_aggregator, JSONB, BaseWriterAgent (independent)
    106-04: Dead code removal (independent)
    106-06: Queue backpressure + state manager index (independent)
  Wave 2:
    106-05: PluginCircuitBreaker wiring (depends on 106-01 OTel gauge infra)
```

### Correct `_DAG_ORDER` Structure for Missing Services
```python
# Priority 0 — infrastructure sentinels (not restartable)
"indicagent-redpanda-ready": 0,
"indicagent-redpanda-watchdog": 0,

# Priority 8 — timer-triggered oneshots (inactive between runs is correct)
"indicagent-weight-updater": 8,
"indicagent-shadow-auditor": 8,
"indicagent-ml-orchestrator": 8,
"indicagent-ml-data-quality": 8,
"indicagent-ml-discovery": 8,

# Priority 10 — always-on top-level
"indicagent-api": 10,
"indicagent-dashboard": 10,
```

### `_ONESHOT_UNITS` Guard Pattern
```python
_ONESHOT_UNITS: frozenset[str] = frozenset({
    "indicagent-weight-updater",
    "indicagent-shadow-auditor",
    "indicagent-ml-orchestrator",
    "indicagent-ml-data-quality",
    "indicagent-ml-discovery",
    "indicagent-ml-training",
    "indicagent-ml-signal-training-materialize",
})
# In graduated restart loop:
if unit_name in _ONESHOT_UNITS:
    continue  # timer-triggered; systemd timer handles restart
```

### PluginCircuitBreaker Shadow Mode
```python
# In PluginCircuitBreaker.__init__:
_GLOBALLY_ENABLED = os.environ.get("PLUGIN_CB_ENABLED", "false").lower() == "true"

def __init__(self, name: str, enabled: bool = False, ...):
    self._enabled = enabled or _GLOBALLY_ENABLED
    ...

def allow_request(self) -> bool:
    if not self._enabled:
        return True  # transparent passthrough
    return <existing state machine logic>
```

### Secondary Index Pattern for PluginStateManager
```python
# In __init__:
self._plugin_states: dict[tuple, dict] = {}
self._states_by_key: dict[tuple[str, str], dict[str, dict]] = {}

# In every write path (after writing to _plugin_states):
key = (symbol, tf)
if key not in self._states_by_key:
    self._states_by_key[key] = {}
self._states_by_key[key][plugin_name] = state

# In get_all_states_for (O(1) lookup):
return dict(self._states_by_key.get((symbol, tf), {}))

# In checkpoint restore (rebuild derived cache):
self._states_by_key = {}
for (plugin_name, symbol, tf), state in self._plugin_states.items():
    key = (symbol, tf)
    self._states_by_key.setdefault(key, {})[plugin_name] = state
```

---

## Open Questions

1. **`roll-compute` priority**
   - What we know: Currently priority 8. Audit D-10 says it should be priority 3 (starts before intelligence-pipeline). But `roll-compute` is a timer-triggered oneshot, not a daemon.
   - What's unclear: The service auditor's graduated restart logic uses priority for ordering — should a oneshot appear at priority 3 in restart ordering when it's not a daemon?
   - Recommendation: Keep at priority 8, add to `_ONESHOT_UNITS`. The audit finding assumes a daemon restart model that doesn't apply to timer services.

2. **`SWARM_QUEUE_TIMEOUT_MS` test usage**
   - What we know: `tests/unit/services/test_alpha_swarm_agent.py:570` passes this as a constructor kwarg. The field is in settings.py.
   - What's unclear: Whether `alpha_swarm_agent` actually reads `settings.SWARM_QUEUE_TIMEOUT_MS` in production code, or whether the test is passing a dead kwarg.
   - Recommendation: Check `services/alpha_swarm_compute_agent.py` for this field reference. If production code uses it, keep the field.

3. **`_on_guardrail_violation` and `_audit_payload` — are they truly dead?**
   - What we know: `grep -rn "_on_guardrail_violation\|_audit_payload" src/ services/` returned zero results outside `base_agent.py`. Only the definitions exist.
   - Recommendation: Verify before deletion in the execution task. The zero-caller check is part of the plan's task already.

4. **`intelligence-pipeline` priority vs `cross-asset`**
   - What we know: Both are at priority 5 in current `_DAG_ORDER`. The audit (D-8) says cross-asset should be 5 and intelligence-pipeline should be 6 (cross-asset must start first since intelligence-pipeline depends on cross-asset topic output).
   - Recommendation: Change `indicagent-intelligence-pipeline` to priority 6. This aligns with the rough 106-02 plan and the audit finding.

---

## Sources

### PRIMARY (HIGH confidence — verified by reading source files)
- `services/service_auditor_agent.py` lines 55-140 — `_DAG_ORDER`, `_LAG_THRESHOLDS`, `_AGENT_ID_TO_UNIT` current state
- `services/intelligence_pipeline_agent.py` lines 176-193, 284, 507-598 — instrument types, enqueue calls, circuit_breakers empty dict
- `src/intelligence/pipeline/state_manager.py` lines 71-202 — `_plugin_states` key structure, `get_all_states_for()` comprehension
- `src/intelligence/pipeline/output_queue.py` — `enqueue()` and `enqueue_blocking()` API, no `size()` method
- `src/observability/metrics.py` lines 224-248 — shadow metrics still `create_up_down_counter`
- `src/core/ml/shadow.py` — ARCHIVED label on `ShadowRecorder`, zero callers
- `src/core/llm/guardrails.py` + `src/core/llm/chain.py` — `GuardrailsValidator` present but zero schemas
- `src/config/settings.py` — 6 dead fields confirmed
- `src/intelligence/ai/TEMPLATE_agent.py:78` — `self._llm.generate()` bypass confirmed
- `src/core/ai/base_agent.py` lines 291-299 — dead hooks confirmed
- `services/bar_aggregator_agent.py` lines 208-260 — manual retry loop confirmed
- `services/swarm_ledger_writer_agent.py`, `bar_replay_provider_agent.py`, `signal_replay_auditor_agent.py` — `asyncpg.create_pool` bypass confirmed
- `services/ctx_writer_agent.py` lines 376-387 — missing `super()._teardown()` confirmed
- `services/llm_writer_service.py` lines 946-948 — `_last_msg_ts` undefined attr confirmed
- `src/core/plugin_circuit_breaker.py` — `PluginCircuitBreaker` exists, 584 lines, functional
- `systemctl list-units --all` output — 9 missing services identified exactly
- `.planning/phases/phase-105/` — no SUMMARY files; Phase 105 not yet executed

### SECONDARY (MEDIUM confidence)
- Audit docs (`docs/architecture/audit-2026-05-23-*.md`) — findings cross-referenced against source
- `.planning/phases/phase-106/106-01 through 106-06-PLAN.md` — rough plans read for overlap analysis

---

## Metadata

**Confidence breakdown:**
- Phase 105 / Phase 106 overlap analysis: HIGH — verified by reading both plan sets and source files
- DAG correctness items: HIGH — verified against `systemctl list-units` and `service_auditor_agent.py`
- Dead code items: HIGH — verified by grep for zero callers; `ShadowRecorder` archived status confirmed
- Code reuse items: HIGH — all three JSONB bypasses confirmed in source; bar_aggregator loop confirmed
- PluginCircuitBreaker: HIGH — confirmed `circuit_breakers={}` at line 284
- Queue backpressure: HIGH — confirmed non-blocking `enqueue` at lines 507, 598
- State manager O(N): HIGH — confirmed dict comprehension at line 100

**Research date:** 2026-05-23
**Valid until:** 2026-06-23 (stable codebase; re-verify if Phase 105 execution changes file structure)
