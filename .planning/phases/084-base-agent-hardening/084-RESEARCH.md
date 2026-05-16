# Phase 84: Base Agent Hardening - Research

**Researched:** 2026-05-16
**Domain:** Python async agent infrastructure, OTel instrumentation, Pydantic validation
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01 (_flush_batch error contract):** `_do_flush()` re-raises `_flush_batch()` exceptions by default. Buffer stays intact. `_flush_errors_total` counter already exists; increment it then re-raise. No DLQ routing for flush failures.

**D-02 (Pydantic payload validation):** Each `BaseWriterAgent` subclass declares `payload_model: ClassVar[type[BaseModel]]`. Base validates with `model_validate()`, catches `ValidationError`, routes to DLQ. `_parse_payload()` receives the already-validated Pydantic object. Subclasses omitting `payload_model` fall back to current unvalidated behavior (backward compat for migration phase).

**D-03 (_setup_with_retry configurability):** Class attributes on `BaseAgent`: `SETUP_RETRY_ATTEMPTS: int = 3` and `SETUP_RETRY_BACKOFF_S: float = 2.0`. Subclasses override these class attrs to tune budgets.

**D-04 (circuit breaker opt-in):** `circuit_breaker: bool = False` class attribute on `BaseAgent`. When `True`, `start()` calls `_setup_with_retry()` instead of `_setup()` directly AND adds open-gate logic (setup fails all retries -> circuit opens -> blocks restart attempts until reset).

**D-05 (graduation loop deletion):** Delete `_graduation_loop()`, `has_graduation`, and all TODO comments from `BaseGroupService`. Shadow governance runs through `shadow_registry` DB table. The empty loop is never activated (`has_graduation` is never `True` in any production service — `AlphaSwarmAgent` has its own override).

**D-06 (LineageRecorder wiring):** Wire `LineageRecorder` into `BaseGroupService`. `BaseGroupService._setup()` instantiates `LineageRecorder`; `BaseAIAgent._on_error()` publishes `agent_prediction` events via it. Must have tests.

**D-07 (_on_error OTel counter):** `_on_error()` emits `ai_agent_errors_total` counter increment with `{agent_id, error_type}` labels. The `pass` body is replaced.

**D-08 (OBS-01 Grafana panel):** `PLUGIN_DURATION_MS` histogram already records `{plugin_name, tier}` at line 1077 of `intelligence_pipeline_agent.py`. OBS-01 is satisfied by adding a Grafana panel (p50/p95 ranking sorted by p95 desc). No pipeline code change.

**D-09 (four additional OTel signals):** Add to base agents:
1. `agent_dlq_total` counter `{agent_id}` - per-agent DLQ event count
2. `agent_last_processed_timestamp` gauge `{agent}` - wall-clock stall detection
3. `agent_setup_retries_total` counter `{agent}` - setup instability signal
4. `agent_circuit_breaker_state` gauge `{agent}` - 0=closed, 1=half-open, 2=open

### Claude's Discretion

- Grafana panel layout for OBS-01 plugin latency histogram (p50/p95 ranking by plugin_name)
- Circuit breaker reset logic implementation detail (timer-based vs. manual reset)
- `LineageRecorder` flush interval and batch size defaults (current: 2.0s, 50 records)
- Test approach for circuit breaker open-gate behavior

### Deferred Ideas (OUT OF SCOPE)

- Per-symbol plugin histogram granularity (`{plugin_name, tier, symbol}`) - Phase 089
- Using OBS-01 data to improve intelligence speed and latency - Phase 089
- Plugin error budget metric - derivable from existing `PLUGIN_ERRORS_TOTAL` in Grafana
</user_constraints>

---

## Summary

Phase 84 hardens three base classes (`BaseAgent`, `BaseWriterAgent`, `BaseAIAgent`) against silent failures. All decisions are pre-locked in CONTEXT.md with precise file and line references. The work is mechanical refactoring plus targeted additions — no new architectural patterns required.

The most significant risks are: (1) the `AlphaSwarmAgent` already overrides `_graduation_loop()` and has `has_graduation = True`, so the base class deletion of `has_graduation` + `_graduation_loop()` must not break `AlphaSwarmAgent`'s override pattern; (2) the LineageRecorder wiring in `BaseGroupService` will be a second instantiation for `AlphaSwarmAgent` (which already creates one in its own `_setup()`), requiring careful design to avoid double-recording.

The seven requirements map directly to five code change sites plus two test files. Each change is isolated; the changes do not interact except through the `start()` method flow and the `BaseGroupService._setup()` chain.

**Primary recommendation:** Implement in dependency order: base.py class attrs and CB attribute (INFRA-03, INFRA-05) first, then base_writer.py exception re-raise + Pydantic layer (INFRA-01, INFRA-02), then base_agent.py _on_error (INFRA-04), then base_group_service.py dead code deletion + LineageRecorder (INFRA-06), finally Grafana panel JSON (OBS-01).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pydantic | v2 (already used) | `payload_model` validation, `model_validate()`, `ValidationError` | Already the project's validation layer; `BaseModel`, `ClassVar`, `ValidationError` are all in use |
| opentelemetry-sdk | already imported | `create_counter`, `create_gauge`, `create_histogram` via `_meter` | Already established in `src/observability/metrics.py`; pattern is module-level `_meter.create_*()` |
| asyncio | stdlib | `_setup_with_retry()` backoff loop, CB open-gate | Already used throughout |
| structlog | already imported | Logging in all agents | Already the standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `typing.ClassVar` | stdlib | `payload_model: ClassVar[type[BaseModel]]` | Required for class-level type hints on Pydantic models |
| `abc.ABC` | stdlib | Abstract method enforcement | Already used; no change needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ClassVar[type[BaseModel]]` on subclass | Abstract property returning type | ClassVar is simpler; allows `None` default for backward compat |
| Timer-based CB reset | Manual `force_reset_plugin()` (already exists in `PluginCircuitBreaker`) | Timer-based is zero-ops; manual requires dashboard tooling |

**Installation:** No new packages required. All dependencies already present.

---

## Architecture Patterns

### Recommended Project Structure (unchanged)
```
src/core/agent/base.py           - BaseAgent (INFRA-03, INFRA-05, D-09 metrics)
src/core/agent/base_writer.py    - BaseWriterAgent (INFRA-01, INFRA-02)
src/core/ai/base_agent.py        - BaseAIAgent (INFRA-04)
src/core/ai/base_group_service.py - BaseGroupService (INFRA-06)
src/observability/metrics.py     - new counters/gauges for D-09
tests/unit/test_base_agent.py    - extend with INFRA-03, INFRA-05 tests
tests/unit/test_base_writer_agent.py - extend with INFRA-01, INFRA-02 tests
```

### Pattern 1: Class Attribute Config (already used in BaseWriterAgent)
**What:** Integer/float class attributes provide configurable constants; subclasses override by redeclaring.
**When to use:** Any knob that varies per-agent but has a reasonable default.
**Example:**
```python
# Source: src/core/agent/base_writer.py lines 79-83
class BaseWriterAgent(BaseAgent, abc.ABC):
    BATCH_SIZE: int = 100
    FLUSH_INTERVAL_SECS: float = 5.0
    MAX_BUFFER_SIZE: int = 10_000
    BUFFER_ALERT_PCT: float = 0.80
```
Apply the same pattern to `BaseAgent`:
```python
class BaseAgent(abc.ABC):
    SETUP_RETRY_ATTEMPTS: int = 3
    SETUP_RETRY_BACKOFF_S: float = 2.0
    circuit_breaker: bool = False
```

### Pattern 2: Module-Level OTel Instrument Cache
**What:** Instruments created once at module import time; attribute dict cached in `__init__`.
**When to use:** Any new OTel metric in base classes.
**Example:**
```python
# Source: src/core/agent/base.py lines 44-65
_base_meter = _otel_metrics.get_meter("indicagent")
AGENT_CRASH_TOTAL = _base_meter.create_counter("agent_crash_total", ...)
# In __init__: self._crash_attrs = {"agent": self._agent_label}
# At call site: AGENT_CRASH_TOTAL.add(1, self._crash_attrs)
```
New D-09 metrics follow identical structure: module-level counter/gauge + cached attr dict.

### Pattern 3: _do_flush() Exception Re-raise
**What:** The `except` block in `_do_flush()` currently swallows exceptions. Change it to re-raise after incrementing the counter.
**Current state (lines 280-285 of base_writer.py):**
```python
except Exception as exc:
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
    self._flush_errors_total.add(1)
    span.set_attribute("error", True)
    self.logger.exception("flush_failed", batch_size=len(batch))
    # MISSING: raise
```
**After fix:** Add `raise` as the last line of the except block.

**Impact on existing test:** `tests/unit/test_base_writer_agent.py` `TestOffsetCommit.test_no_commit_on_flush_failure` currently passes because `_do_flush()` swallows the exception. After the fix the test must `pytest.raises(RuntimeError)` instead of checking that commit was not called.

### Pattern 4: Pydantic Validation Gate in BaseWriterAgent
**What:** `_run()` calls `_parse_payload()` on the raw dict. Insert a Pydantic validation step before that call.
**When to use:** When `payload_model` is declared on the subclass.

Concrete implementation sketch:
```python
# In BaseWriterAgent._run() before the _parse_payload call:
payload_model = getattr(type(self), "payload_model", None)
if payload_model is not None:
    try:
        validated = payload_model.model_validate(payload)
        rows = self._parse_payload(validated)
    except ValidationError as exc:
        self._parse_failures_total.add(1)
        await self._maybe_route_to_dlq(payload, exc)
        continue
else:
    rows = self._parse_payload(payload)
```

The `_parse_payload` signature change (`dict` -> `BaseModel`) only affects new subclasses that opt in by declaring `payload_model`. Existing subclasses that don't declare it receive a raw dict as before (backward compat).

### Pattern 5: Circuit Breaker Open-Gate in start()
**What:** When `circuit_breaker = True`, `start()` branches to `_setup_with_retry()` instead of `_setup()`. On total failure, sets an instance flag that blocks restarts.
**When to use:** Any agent where Kafka/DB setup failure at cold start should not spin in a crash loop.

Sketch:
```python
# In BaseAgent.start():
if self.circuit_breaker:
    try:
        await self._setup_with_retry()  # uses SETUP_RETRY_ATTEMPTS / SETUP_RETRY_BACKOFF_S
    except Exception:
        self._cb_open = True
        AGENT_CIRCUIT_BREAKER_STATE.set(2, {"agent": self._agent_label})  # 2=open
        raise
else:
    await self._setup()
```

### Anti-Patterns to Avoid
- **Touching `AlphaSwarmAgent._graduation_loop()` override:** The base class deletes `_graduation_loop()` stub and `has_graduation`; AlphaSwarmAgent provides its own full implementation. The `_run()` in `BaseGroupService` must stop checking `has_graduation` — `AlphaSwarmAgent` overrides `_run()` OR `BaseGroupService._run()` calls `_graduation_loop()` only when the subclass has overridden it (check via `type(self)._graduation_loop is not BaseGroupService._graduation_loop`).
- **Double-instantiating LineageRecorder in AlphaSwarmAgent:** `AlphaSwarmAgent._setup()` already creates `self._lineage` (lines 180-184). The `BaseGroupService._setup()` must not overwrite it. Use `if not hasattr(self, '_lineage') or self._lineage is None` guard.
- **Calling `_setup_with_retry()` from user code:** It is called from `start()` based on `circuit_breaker` flag, not called directly by subclasses.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pydantic validation with error routing | Custom try/except per writer | `payload_model: ClassVar[type[BaseModel]]` + base class gate | D-02: base handles ValidationError -> DLQ automatically |
| Retry scaffolding | Per-agent for loops with hardcoded values | `SETUP_RETRY_ATTEMPTS`, `SETUP_RETRY_BACKOFF_S` + `_setup_with_retry()` | Three services already duplicate this; centralize once |
| CB state machine | New class | `circuit_breaker: bool` class attr + inline logic in `start()` | Phase 086 will wire `PluginCircuitBreaker` per-plugin; agent CB is simpler on/off flag |
| OTel instrument creation | Per-agent meters | Module-level `_base_meter.create_*()` with cached attrs | Pattern established in base.py lines 44-65 |

---

## Common Pitfalls

### Pitfall 1: AlphaSwarmAgent has_graduation = True breaks after base deletion
**What goes wrong:** `BaseGroupService._run()` checks `if self.has_graduation` at line 190. Deleting the attribute causes `AttributeError` unless the `_run()` check is also removed.
**Why it happens:** `AlphaSwarmAgent` declares `has_graduation = True` and overrides `_graduation_loop()`. The deletion must be coordinated.
**How to avoid:** Remove the `has_graduation` attribute AND the `if self.has_graduation` guard in `BaseGroupService._run()`. `AlphaSwarmAgent` overrides `_run()` itself (confirmed: it calls `super()._run()` indirectly via `BaseGroupService._run()` tasks). Check whether `AlphaSwarmAgent` overrides `_run()` or relies on `BaseGroupService._run()` to spawn `_graduation_loop()`.
**Warning signs:** `AttributeError: 'AlphaSwarmComputeAgent' object has no attribute 'has_graduation'` on startup.

**IMPORTANT:** Looking at `AlphaSwarmAgent`, it does NOT override `_run()`. It sets `has_graduation = True` so `BaseGroupService._run()` will create `_graduation_loop()` as a task. When `has_graduation` and the base stub are deleted, the `_run()` task list must instead check for a subclass override. The cleanest solution: remove the `has_graduation` guard entirely and change `BaseGroupService._run()` to call `_graduation_loop()` only if `type(self)._graduation_loop is not BaseGroupService._graduation_loop` (i.e., the subclass provides a real implementation). This means deleting the stub from the base while preserving `AlphaSwarmAgent`'s override.

### Pitfall 2: LineageRecorder double-init in AlphaSwarmAgent
**What goes wrong:** `BaseGroupService._setup()` creates `self._lineage` AFTER `AlphaSwarmAgent._setup()` calls `super()._setup()`, so `AlphaSwarmAgent`'s post-super assignment `self._lineage = LineageRecorder(...)` would be the one that sticks — correct order. But if `BaseGroupService._setup()` does the assignment, then `AlphaSwarmAgent._setup()` does it again, the first one is orphaned (its background flush task keeps running without a reference to stop it).
**How to avoid:** `BaseGroupService._setup()` assigns `self._lineage` before `AlphaSwarmAgent._setup()` continues (because `await super()._setup()` is called first). `AlphaSwarmAgent._setup()` then overwrites with its own instance. Solution: `AlphaSwarmAgent` deletes its own `self._lineage` assignment and relies on the base class instance. The `BaseGroupService` instance is already created with the same `self._producer` that `AlphaSwarmAgent` was using. This is the desired consolidation.

### Pitfall 3: _do_flush() re-raise breaks existing test
**What goes wrong:** `test_no_commit_on_flush_failure` (line 189 of test_base_writer_agent.py) currently calls `await agent._do_flush()` and expects it NOT to raise. After D-01, it WILL raise.
**How to avoid:** Update the test to `pytest.raises(RuntimeError)` and verify buffer still has items AND commit was not called.

### Pitfall 4: SETUP_RETRY_ATTEMPTS class attr shadows _attempts local var in _setup_with_retry
**What goes wrong:** `_setup_with_retry()` currently uses `_attempts = 3` and `_backoff_base = 2.0` as local variables (lines 452-453 of base.py). These must be replaced by `self.SETUP_RETRY_ATTEMPTS` and `self.SETUP_RETRY_BACKOFF_S`.
**How to avoid:** Change the method body to use `self.SETUP_RETRY_ATTEMPTS` and `self.SETUP_RETRY_BACKOFF_S`. Add `agent_setup_retries_total` counter increment inside the retry loop's warning branch.

### Pitfall 5: agent_dlq_total vs DLQ_MESSAGES_TOTAL naming conflict
**What goes wrong:** `DLQ_MESSAGES_TOTAL` already exists in metrics.py at line 264. D-09 adds `agent_dlq_total` as a per-agent counter. They must not duplicate tracking.
**How to avoid:** `agent_dlq_total` is in `BaseAgent.__init__` with label `{agent_id}` and incremented in `_send_to_dlq()`. `DLQ_MESSAGES_TOTAL` in metrics.py has label `{agent, topic, error_type}` and is incremented inside `_send_to_dlq()` when a producer is available. Both can coexist: `agent_dlq_total` is the per-agent rollup (fires even when no producer, i.e., log-only path); `DLQ_MESSAGES_TOTAL` fires only when actually routed to Kafka DLQ. They measure different things.

### Pitfall 6: _on_error needs access to LineageRecorder but BaseAIAgent doesn't own it
**What goes wrong:** D-06 says `BaseAIAgent._on_error()` publishes `agent_prediction` events via LineageRecorder. But `BaseAIAgent` is composed inside `BaseGroupService` and doesn't hold a direct reference to `self._lineage`.
**How to avoid:** Pass the `LineageRecorder` instance to each `BaseAIAgent` (or access it via a back-reference to the group service). Simplest: add `_lineage: LineageRecorder | None = None` to `BaseAIAgent.__init__`; `BaseGroupService._setup()` sets it on each agent after creating the recorder. `_on_error()` calls `self._lineage.record(...)` if `self._lineage is not None`.

---

## Code Examples

### Exact current state of _setup_with_retry() (base.py lines 446-469)
```python
# Source: src/core/agent/base.py
async def _setup_with_retry(self) -> None:
    _attempts = 3           # <-- hardcoded, becomes self.SETUP_RETRY_ATTEMPTS
    _backoff_base = 2.0     # <-- hardcoded, becomes self.SETUP_RETRY_BACKOFF_S
    for attempt in range(_attempts):
        try:
            await self._setup()
            return
        except Exception as exc:
            if attempt == _attempts - 1:
                raise
            backoff = _backoff_base**attempt
            self.logger.warning("agent.setup_retry", ...)
            await asyncio.sleep(backoff)
```

### Exact current state of _do_flush() exception block (base_writer.py lines 280-285)
```python
# Source: src/core/agent/base_writer.py
except Exception as exc:
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
    self._flush_errors_total.add(1)
    span.set_attribute("error", True)
    self.logger.exception("flush_failed", batch_size=len(batch))
    # <-- no raise here; exception is swallowed
```

### Exact current state of _on_error() (base_agent.py line 266-271)
```python
# Source: src/core/ai/base_agent.py
async def _on_error(self, error: Exception) -> None:
    """Hook: called when _compute() raises exception.
    Future phase: wire to OTel span + alert.
    """
    pass  # <-- entire body is pass
```

### Existing OTel creation pattern to follow for D-09 metrics
```python
# Source: src/core/agent/base.py lines 44-65
_base_meter = _otel_metrics.get_meter("indicagent")
AGENT_CRASH_TOTAL = _base_meter.create_counter(
    "agent_crash_total",
    description="Agent crashes (uncaught exceptions) from BaseAgent._run()",
)
# In __init__: self._crash_attrs = {"agent": self._agent_label}
# At call site: AGENT_CRASH_TOTAL.add(1, self._crash_attrs)
```

### LineageRecorder.record() signature (lineage.py lines 44-56)
```python
# Source: src/core/ai/lineage.py
def record(
    self,
    *,
    signal_id: UUID,
    event_type: str,  # 'transform' | 'agent_prediction' | 'lifecycle'
    source: str,      # transform_id or agent_id
    dag_order: int | None = None,
    multiplier: float | None = None,
    metadata: dict[str, Any] | None = None,
    is_shadow: bool = True,
    symbol: str = "",
    tf: str = "",
) -> None:
```

### PLUGIN_DURATION_MS recording location (intelligence_pipeline_agent.py line 1077)
```python
# Source: services/intelligence_pipeline_agent.py
PLUGIN_DURATION_MS.record(
    duration_ms, {"plugin_name": task.plugin_name, "tier": tier}
)
```
OBS-01 needs a Grafana panel consuming this metric. No code change required.

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `_graduation_loop()` with TODO stub in BaseGroupService | Delete stub; `AlphaSwarmAgent` owns full implementation | Eliminates 15-min sleep loop in base that never runs |
| Hardcoded `_attempts = 3`, `_backoff_base = 2.0` in `_setup_with_retry()` | Class attrs `SETUP_RETRY_ATTEMPTS`, `SETUP_RETRY_BACKOFF_S` | Three services with duplicated retry scaffolding can migrate |
| `_on_error(self, error)` body is `pass` | OTel counter + LineageRecorder publish | Every AI agent error becomes observable |
| `_do_flush()` swallows exceptions after logging | Re-raises after incrementing counter | Flush failures propagate; systemd restart recovers cleanly |
| No per-agent DLQ event count | `agent_dlq_total` counter | Grafana alerting on DLQ spikes per agent |

**Key duplication identified:** Three services have inline retry scaffolding that `_setup_with_retry()` + class attrs will replace:
1. `bar_aggregator_agent.py` lines 209-268: `_MAX_ATTEMPTS = 4`, `_BASE_DELAY = 2.0`
2. `bar_writer_agent.py` lines 198-218: `_cache_attempts = 3`, `_cache_backoff = 5.0`
3. `signal_tracker_compute_agent.py` lines 913-923: `_BOOTSTRAP_BACKOFF_SECONDS` list

Note: These services are NOT being migrated in Phase 84 (that is Phase 085 scope). Phase 84 only adds the configurable class attrs to `BaseAgent` and verifies `_setup_with_retry()` uses them.

---

## Open Questions

1. **AlphaSwarmAgent _run() task spawning after has_graduation deletion**
   - What we know: `BaseGroupService._run()` checks `if self.has_graduation` to add `_graduation_loop` to tasks. `AlphaSwarmAgent` sets `has_graduation = True` and overrides `_graduation_loop()` with a real implementation.
   - What's unclear: The cleanest way to delete `has_graduation` without breaking `AlphaSwarmAgent`.
   - Recommendation: Replace `if self.has_graduation` check with `if type(self)._graduation_loop is not BaseGroupService._graduation_loop`. Delete `has_graduation` class attr and the stub method from base. `AlphaSwarmAgent`'s override is preserved as-is.

2. **LineageRecorder in _on_error() requires signal_id (UUID)**
   - What we know: `LineageRecorder.record()` requires `signal_id: UUID` as a keyword arg.
   - What's unclear: `_on_error(self, error: Exception)` has no `signal_id` — the error might not be associated with a specific signal.
   - Recommendation: Use `UUID(int=0)` as a sentinel for "no signal" OR make `signal_id` optional in `LineageRecorder.record()`. Check D-06 intent: "publishes `agent_prediction` events via it" likely means recording agent-level error events, not signal-specific. A nil UUID sentinel is the simplest approach; no signature change to `LineageRecorder` needed.

3. **agent_circuit_breaker_state gauge vs CIRCUIT_BREAKER_STATE in metrics.py**
   - What we know: `CIRCUIT_BREAKER_STATE` (line 67 of metrics.py) already exists with label `{plugin_name}`. D-09 adds `agent_circuit_breaker_state` with label `{agent}`.
   - What's unclear: Should they share the same metric name with different label keys, or be distinct instruments?
   - Recommendation: Keep distinct instruments. `CIRCUIT_BREAKER_STATE` is for per-plugin CB in `PluginCircuitBreaker`; `agent_circuit_breaker_state` is for per-agent setup CB. Different semantic domains.

---

## Sources

### Primary (HIGH confidence)
- `src/core/agent/base.py` - Full source read; exact line numbers for `_setup_with_retry()` (446), `start()` (160), `_send_to_dlq()` (332)
- `src/core/agent/base_writer.py` - Full source read; exact lines for `_do_flush()` except block (280-285), class attrs pattern (79-83)
- `src/core/ai/base_agent.py` - Full source read; confirmed `_on_error()` is `pass` at line 266-271
- `src/core/ai/base_group_service.py` - Full source read; confirmed `_graduation_loop()` is stub with TODOs (282-302), `has_graduation` at line 46
- `src/core/ai/lineage.py` - Full source read; confirmed complete implementation with `start()`, `stop()`, `record()`, `flush()`
- `src/observability/metrics.py` - Full source read; confirmed `PLUGIN_DURATION_MS` at line 39, `DLQ_MESSAGES_TOTAL` at line 264, `AI_AGENT_INVOCATIONS_TOTAL` at line 350
- `services/intelligence_pipeline_agent.py` - Confirmed `PLUGIN_DURATION_MS.record()` at line 1077 with `{plugin_name, tier}` labels
- `services/alpha_swarm_agent.py` - Confirmed `has_graduation = True` at line 121, full `_graduation_loop()` override at line 217, `LineageRecorder` instantiated at lines 180-184
- `tests/unit/test_base_agent.py` - Full source read; understand existing test structure
- `tests/unit/test_base_writer_agent.py` - Full source read; identified test that must be updated (line 189)

### Secondary (MEDIUM confidence)
- `services/bar_aggregator_agent.py` lines 204-268 - Confirmed duplicate retry scaffolding pattern
- `services/bar_writer_agent.py` lines 198-218 - Confirmed second duplicate retry scaffolding pattern
- `services/signal_tracker_compute_agent.py` lines 913-923 - Confirmed third duplicate retry scaffolding pattern

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in use; no new dependencies
- Architecture: HIGH - exact file/line references verified from source
- Pitfalls: HIGH - identified from reading actual code state, not theoretical
- AlphaSwarmAgent interaction: MEDIUM - the graduation loop override pattern is clear but the cleanest deletion strategy requires a judgment call on `_run()` dispatch

**Research date:** 2026-05-16
**Valid until:** 2026-06-16 (stable base classes; changes are in this phase)
