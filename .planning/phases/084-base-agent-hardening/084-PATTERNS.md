# Phase 84: Base Agent Hardening - Pattern Map

**Mapped:** 2026-05-16
**Files analyzed:** 6 (5 source + 1 test update)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/core/agent/base.py` | base-agent | request-response | self (current state) | exact |
| `src/core/agent/base_writer.py` | base-agent | CRUD | self (current state) | exact |
| `src/core/ai/base_agent.py` | base-agent | request-response | self (current state) | exact |
| `src/core/ai/base_group_service.py` | base-agent | event-driven | self + `services/alpha_swarm_agent.py` | exact |
| `src/observability/metrics.py` | config/registry | - | self (current state) | exact |
| `tests/unit/test_base_agent.py` + `tests/unit/test_base_writer_agent.py` | test | - | self (current state) | exact |

## Pattern Assignments

---

### `src/core/agent/base.py` (INFRA-03, INFRA-05, D-09)

**Changes required:** Add `SETUP_RETRY_ATTEMPTS`/`SETUP_RETRY_BACKOFF_S`/`circuit_breaker` class attrs; rewrite `_setup_with_retry()` to use them; branch `start()` on `circuit_breaker`; add four new OTel instruments + `_cb_open` instance flag.

**Existing class attr pattern** (lines 79-82 of `base_writer.py` — copy this style to `base.py`):
```python
BATCH_SIZE: int = 100
FLUSH_INTERVAL_SECS: float = 5.0
MAX_BUFFER_SIZE: int = 10_000
BUFFER_ALERT_PCT: float = 0.80
```
Apply to `BaseAgent`:
```python
SETUP_RETRY_ATTEMPTS: int = 3
SETUP_RETRY_BACKOFF_S: float = 2.0
circuit_breaker: bool = False
```

**Existing OTel instrument creation pattern** (lines 44-65 of `base.py`):
```python
_base_meter = _otel_metrics.get_meter("indicagent")

AGENT_CRASH_TOTAL = _base_meter.create_counter(
    "agent_crash_total",
    description="Agent crashes (uncaught exceptions) from BaseAgent._run()",
)
```
New D-09 instruments follow the same module-level `_base_meter.create_*()` pattern:
```python
AGENT_DLQ_TOTAL = _base_meter.create_counter(
    "agent_dlq_total",
    description="Per-agent DLQ events (all paths, including log-only)",
)
AGENT_SETUP_RETRIES_TOTAL = _base_meter.create_counter(
    "agent_setup_retries_total",
    description="Setup retry attempts per agent",
)
AGENT_CIRCUIT_BREAKER_STATE = _base_meter.create_gauge(
    "agent_circuit_breaker_state",
    description="Agent circuit breaker state: 0=closed, 1=half-open, 2=open",
)
```
Note: `agent_last_processed_timestamp` is already covered by `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` in `src/observability/metrics.py` (line 199) with label `{agent}` and set via `_record_message_consumed()` (line 281 of `base.py`). Do NOT create a duplicate. D-09 item 2 is already satisfied.

**`__init__` cached attrs pattern** (lines 121-124 of `base.py` — add new attrs in same block):
```python
self._crash_attrs = {"agent": self._agent_label}
self._setup_success_attrs = {"agent": self._agent_label}
self._setup_latency_attrs = {"agent": self._agent_label}
# Add:
self._dlq_attrs = {"agent_id": self._agent_label}   # note: agent_id label per D-09
self._cb_attrs = {"agent": self._agent_label}
self._cb_open: bool = False  # circuit breaker open-gate flag
```

**Existing `_setup_with_retry()` body to replace** (lines 446-469 of `base.py`):
```python
async def _setup_with_retry(self) -> None:
    _attempts = 3           # <-- becomes self.SETUP_RETRY_ATTEMPTS
    _backoff_base = 2.0     # <-- becomes self.SETUP_RETRY_BACKOFF_S
    for attempt in range(_attempts):
        try:
            await self._setup()
            return
        except Exception as exc:
            if attempt == _attempts - 1:
                raise
            backoff = _backoff_base**attempt
            self.logger.warning(
                "agent.setup_retry",
                attempt=attempt + 1,
                max_attempts=_attempts,
                backoff_seconds=backoff,
                error=str(exc),
            )
            await asyncio.sleep(backoff)
```
After fix: replace `_attempts` and `_backoff_base` with `self.SETUP_RETRY_ATTEMPTS` and `self.SETUP_RETRY_BACKOFF_S`; add `AGENT_SETUP_RETRIES_TOTAL.add(1, self._cb_attrs)` in the warning branch.

**Existing `start()` setup block to extend** (lines 187-200 of `base.py`):
```python
try:
    setup_start = time.monotonic()
    await self._setup()           # <-- branch on self.circuit_breaker here
    ...
except Exception as exc:
    self.logger.exception("agent.setup_failed")
    AGENT_SETUP_FAILURE_TOTAL.add(
        1, {"agent": self._agent_label, "error_type": type(exc).__name__}
    )
    raise
```
After fix: when `self.circuit_breaker` is `True`, call `await self._setup_with_retry()` instead of `await self._setup()`. On total failure also set `self._cb_open = True` and emit `AGENT_CIRCUIT_BREAKER_STATE.set(2, self._cb_attrs)` before re-raising.

**`_send_to_dlq()` — add `agent_dlq_total` increment** (line 332, inside the method):
The method already calls `DLQ_MESSAGES_TOTAL.add(...)` on the Kafka-routed path. Add `AGENT_DLQ_TOTAL.add(1, self._dlq_attrs)` unconditionally at the top of the method body (fires even on the log-only discard path), satisfying D-09 intent that `agent_dlq_total` is the per-agent rollup regardless of routing outcome.

---

### `src/core/agent/base_writer.py` (INFRA-01, INFRA-02)

**Changes required:** Add `payload_model: ClassVar[type[BaseModel]] | None = None`; insert Pydantic validation gate in `_run()` before `_parse_payload()`; change `_do_flush()` except block to re-raise.

**Existing class attr pattern** (lines 79-82, copy style):
```python
BATCH_SIZE: int = 100
FLUSH_INTERVAL_SECS: float = 5.0
```
Add:
```python
from typing import ClassVar
from pydantic import BaseModel, ValidationError

payload_model: ClassVar[type[BaseModel] | None] = None
```

**Existing `_do_flush()` except block to fix** (lines 280-285):
```python
except Exception as exc:
    span.set_status(StatusCode.ERROR, str(exc))
    span.record_exception(exc)
    self._flush_errors_total.add(1)
    span.set_attribute("error", True)
    self.logger.exception("flush_failed", batch_size=len(batch))
    # MISSING: raise
```
After fix: add `raise` as the last line of the except block. Buffer stays intact (already cleared only on success path line 273).

**Existing `_run()` parse+buffer block to extend** (lines 312-318):
```python
try:
    rows = self._parse_payload(payload)
    if rows is not None:
        self._buffer_rows(rows)
    else:
        self._parse_failures_total.add(1)
        await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
except Exception as exc:
    ...
    raise
```
After fix (Pydantic gate inserted before `_parse_payload()`):
```python
try:
    model_cls = type(self).payload_model
    if model_cls is not None:
        try:
            validated = model_cls.model_validate(payload)
            rows = self._parse_payload(validated)
        except ValidationError as exc:
            self._parse_failures_total.add(1)
            await self._maybe_route_to_dlq(payload, exc)
            continue
    else:
        rows = self._parse_payload(payload)
    if rows is not None:
        self._buffer_rows(rows)
    else:
        self._parse_failures_total.add(1)
        await self._maybe_route_to_dlq(payload, Exception("Parse failed"))
except Exception as exc:
    ...
    raise
```
Note: `type(self).payload_model` not `self.payload_model` — avoids instance attribute shadowing.

**Abstract method signature change for `_parse_payload`** (line 144):
```python
@abc.abstractmethod
def _parse_payload(self, payload: dict) -> list | None:
```
The signature must remain `dict` (backward compat for subclasses without `payload_model`). Subclasses that declare `payload_model` receive a `BaseModel` instance instead of a raw dict; document this in the docstring only, no type annotation change at the base.

---

### `src/core/ai/base_agent.py` (INFRA-04)

**Change required:** Replace `pass` in `_on_error()` with OTel counter increment. Optionally wire `LineageRecorder`.

**Existing `_on_error()` body** (lines 266-271):
```python
async def _on_error(self, error: Exception) -> None:
    """Hook: called when _compute() raises exception.

    Future phase: wire to OTel span + alert.
    """
    pass  # <-- replace with counter increment
```

**Counter to add at module level** (follow `AI_AGENT_INVOCATIONS_TOTAL` pattern at line 350 of `metrics.py`):
```python
# In src/observability/metrics.py:
AI_AGENT_ERRORS_TOTAL = _meter.create_counter(
    "ai_agent_errors_total",
    description="AI agent _compute() errors by agent_id and error_type",
)
```
Import and call in `base_agent.py`:
```python
from src.observability.metrics import AI_AGENT_ERRORS_TOTAL, ...

async def _on_error(self, error: Exception) -> None:
    """Called when _compute() raises or times out. Emits OTel counter."""
    AI_AGENT_ERRORS_TOTAL.add(
        1, {"agent_id": self.agent_id, "error_type": type(error).__name__}
    )
    if self._lineage is not None:
        from uuid import UUID
        self._lineage.record(
            signal_id=UUID(int=0),  # sentinel for agent-level (non-signal) error
            event_type="agent_prediction",
            source=self.agent_id,
            metadata={"error": str(error), "error_type": type(error).__name__},
        )
```

**LineageRecorder back-reference** (D-06 wiring):
Add `_lineage: LineageRecorder | None = None` to `BaseAIAgent.__init__`. `BaseGroupService._setup()` sets it on each agent after creating the recorder. `_on_error()` guards with `if self._lineage is not None`.

```python
# In BaseAIAgent.__init__:
self._lineage: LineageRecorder | None = None
```

**`LineageRecorder.record()` required signature** (lines 44-56 of `src/core/ai/lineage.py`):
```python
def record(
    self,
    *,
    signal_id: UUID,          # Use UUID(int=0) as sentinel for non-signal errors
    event_type: str,           # "agent_prediction"
    source: str,               # agent_id
    dag_order: int | None = None,
    multiplier: float | None = None,
    metadata: dict | None = None,
    is_shadow: bool = True,
    symbol: str = "",
    tf: str = "",
) -> None:
```

---

### `src/core/ai/base_group_service.py` (INFRA-06)

**Changes required:** Delete `_graduation_loop()` stub and `has_graduation` class attr; fix `_run()` to dispatch `_graduation_loop()` only when subclass overrides it; wire `LineageRecorder` in `_setup()` and `_teardown()`; set `_lineage` on each agent after creation.

**Dead code to delete:**

1. Class attribute `has_graduation: bool = False` (line 46).
2. Method `_graduation_loop()` (lines 282-303) — the entire method body including docstring.
3. In `_run()`, the block `if self.has_graduation:` (lines 190-192).

**`_run()` replacement for graduation task dispatch** (lines 182-199):
```python
# Current (lines 190-192):
if self.has_graduation:
    graduation_task = asyncio.create_task(self._graduation_loop())
    tasks.append(graduation_task)

# Replace with (subclass override detection):
if type(self)._graduation_loop is not BaseGroupService._graduation_loop:
    graduation_task = asyncio.create_task(self._graduation_loop())
    tasks.append(graduation_task)
```
This preserves `AlphaSwarmAgent._graduation_loop()` (the real implementation at lines 217-230 of `alpha_swarm_agent.py`) while deleting the base stub. No change required in `AlphaSwarmAgent`.

**`AlphaSwarmAgent` `has_graduation = True`** (line 121 of `alpha_swarm_agent.py`):
Delete this class attribute after the base class no longer references it. The dispatch now relies on method override detection, not the flag.

**`LineageRecorder` wiring in `_setup()`** — add after `self._llm_chain` setup and before `_seed_context_cache()`:
```python
# Add in BaseGroupService._setup(), using AlphaSwarmAgent._setup() lines 180-184 as the pattern:
from src.core.ai.lineage import LineageRecorder

if not hasattr(self, "_lineage") or self._lineage is None:
    self._lineage = LineageRecorder(
        producer=self._producer,
        env_name=self.env_name,
    )
    await self._lineage.start()

# Wire lineage back-reference to each agent (for _on_error)
for agent in self.agents:
    agent._lineage = self._lineage
```
The guard `if not hasattr(self, "_lineage") or self._lineage is None` prevents double-instantiation when a subclass (currently `AlphaSwarmAgent`) already creates its own. **After this is merged, `AlphaSwarmAgent._setup()` must remove its own `LineageRecorder` construction** (lines 180-184), relying on the base class instance.

**`LineageRecorder` cleanup in `_teardown()`** (add to lines 201-210):
```python
async def _teardown(self) -> None:
    if hasattr(self, "_lineage") and self._lineage is not None:
        await self._lineage.stop()
    if self._pool:
        ...  # existing teardown continues
```

**`AlphaSwarmAgent._setup()` lines to remove** (after base class provides the recorder):
```python
# Lines 180-184 to DELETE from alpha_swarm_agent.py after base wiring is complete:
self._lineage = LineageRecorder(
    producer=self._producer,
    env_name=self.env_name,
)
await self._lineage.start()
```

---

### `src/observability/metrics.py` (D-09 + INFRA-04)

**Changes required:** Add four new OTel instruments. Follow existing `_meter.create_*()` pattern throughout the file.

**Instrument creation pattern** (lines 264-267 as concrete example):
```python
DLQ_MESSAGES_TOTAL = _meter.create_counter(
    "dlq_messages_total",
    description="Total messages routed to Dead Letter Queue",
)
```

**New instruments to add** (group near "Agent liveness" section at line 196):
```python
# ---------------------------------------------------------------------------
# Base agent hardening metrics (Phase 84)
# ---------------------------------------------------------------------------

AGENT_DLQ_TOTAL = _meter.create_counter(
    "agent_dlq_total",
    description="Per-agent DLQ event count (all paths, including log-only discard)",
)
AGENT_SETUP_RETRIES_TOTAL = _meter.create_counter(
    "agent_setup_retries_total",
    description="Setup retry attempts per agent (each retry loop iteration)",
)
AGENT_CIRCUIT_BREAKER_STATE = _meter.create_gauge(
    "agent_circuit_breaker_state",
    description="Agent setup circuit breaker state: 0=closed, 1=half-open, 2=open",
)
AI_AGENT_ERRORS_TOTAL = _meter.create_counter(
    "ai_agent_errors_total",
    description="AI agent _compute() errors by agent_id and error_type",
)
```

**Gauge vs up_down_counter:** The existing `CIRCUIT_BREAKER_STATE` at line 67 uses `_meter.create_gauge()`. Follow the same for `AGENT_CIRCUIT_BREAKER_STATE`.

**Naming collision check:**
- `DLQ_MESSAGES_TOTAL` (line 264): label `{agent, topic, error_type}`, fires only on Kafka-routed DLQ. Different from `AGENT_DLQ_TOTAL` (label `{agent_id}`, fires on every DLQ path). No conflict.
- `CIRCUIT_BREAKER_STATE` (line 67): label `{plugin_name}`. Different domain from `AGENT_CIRCUIT_BREAKER_STATE` label `{agent}`. No conflict.
- `AI_AGENT_INVOCATIONS_TOTAL` (line 350): label `{agent_id, group, status}`. `AI_AGENT_ERRORS_TOTAL` is additive with label `{agent_id, error_type}`. No conflict.

---

### Test files (INFRA-01, INFRA-02, INFRA-03, INFRA-05 coverage)

**`tests/unit/test_base_writer_agent.py`**

**Test to update — `test_no_commit_on_flush_failure`** (lines 189-206):
```python
# Current — expects _do_flush() to swallow the exception:
await agent._do_flush()
assert len(agent._buffer) == 1
agent._consumer.commit.assert_not_awaited()

# After D-01 fix — must wrap with pytest.raises:
with pytest.raises(RuntimeError, match="DB down"):
    await agent._do_flush()
assert len(agent._buffer) == 1      # buffer stays intact
agent._consumer.commit.assert_not_awaited()
```

**Test to update — `test_flush_errors_counter_increments_on_failure`** (lines 309-329):
Same pattern: wrap `await agent._do_flush()` with `pytest.raises(RuntimeError)`.

**New tests to add for INFRA-01 (Pydantic gate):**
```python
# Pattern: declare payload_model on a test subclass, verify ValidationError routes to DLQ
class TypedWriterAgent(BaseWriterAgent):
    from pydantic import BaseModel
    class MyModel(BaseModel):
        id: int
    payload_model = MyModel
    ...

@pytest.mark.asyncio
async def test_pydantic_validation_error_routes_to_dlq():
    agent = TypedWriterAgent()
    agent._consumer = AsyncMock()
    bad_payload = {"id": "not_an_int"}
    # Should route to DLQ, not raise, buffer stays empty
    ...
```

**`tests/unit/test_base_agent.py`**

**New tests to add for INFRA-03 (class attr configurability):**
```python
# Pattern: follow existing test_base_agent_tracks_setup_failure() structure (lines 397-419)
def test_setup_retry_class_attrs_default():
    a = MinimalAgent(name="x")
    assert a.SETUP_RETRY_ATTEMPTS == 3
    assert a.SETUP_RETRY_BACKOFF_S == 2.0
    assert a.circuit_breaker is False

def test_setup_retry_class_attrs_overridable():
    class FastRetryAgent(BaseAgent):
        SETUP_RETRY_ATTEMPTS = 1
        SETUP_RETRY_BACKOFF_S = 0.1
        async def _run(self): pass
    a = FastRetryAgent(name="y")
    assert a.SETUP_RETRY_ATTEMPTS == 1
```

**New tests for INFRA-05 (circuit breaker):**
```python
# Pattern: follow test_teardown_called_on_run_exception() (lines 159-176)
@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_all_retries_fail():
    class AlwaysFailSetupAgent(BaseAgent):
        circuit_breaker = True
        SETUP_RETRY_ATTEMPTS = 1
        SETUP_RETRY_BACKOFF_S = 0.0
        async def _setup(self): raise RuntimeError("always fails")
        async def _run(self): pass

    with patch("src.core.agent.base.BaseAgent._register_signal_handlers"):
        a = AlwaysFailSetupAgent(name="cb_test")
        with pytest.raises(RuntimeError):
            await a.start()
    assert a._cb_open is True
```

---

## Shared Patterns

### OTel instrument creation
**Source:** `src/observability/metrics.py` lines 17-18, 264-267
**Apply to:** All new metrics in `metrics.py` and `base.py`
```python
_meter = otel_metrics.get_meter("indicagent")
INSTRUMENT = _meter.create_counter("metric_name", description="...")
```
Call-site: `INSTRUMENT.add(1, {"label_key": value})` for counters, `.set(value, {...})` for gauges, `.record(value, {...})` for histograms.

### Cached attribute dict for OTel labels
**Source:** `src/core/agent/base.py` lines 121-124
**Apply to:** All new per-agent OTel instruments in `base.py`
```python
self._crash_attrs = {"agent": self._agent_label}
```
Cache in `__init__`, reuse at call sites. Never construct `{"agent": ...}` inline in hot paths.

### Class attribute configuration
**Source:** `src/core/agent/base_writer.py` lines 79-82
**Apply to:** New `SETUP_RETRY_ATTEMPTS`, `SETUP_RETRY_BACKOFF_S`, `circuit_breaker` in `base.py`
```python
BATCH_SIZE: int = 100
FLUSH_INTERVAL_SECS: float = 5.0
```
Plain class-level type-annotated assignments. Subclasses redeclare to override. No `ClassVar` required for simple int/float/bool (only needed for `payload_model` because it holds a type reference).

### Module-level instrument cache (BaseWriterAgent pattern)
**Source:** `src/core/agent/base_writer.py` lines 41-61
**Apply to:** Any per-agent-instance instrument in `BaseWriterAgent` subclasses
```python
_gauges: dict = {}
_counters: dict = {}

def _get_or_create_counter(name: str, doc: str):
    if name not in _counters:
        _counters[name] = _bw_meter.create_counter(name, description=doc)
    return _counters[name]
```
Module-level `base.py` instruments (`AGENT_CRASH_TOTAL`, etc.) are already deduplicated by being module-level singletons — no cache dict needed for them.

### Subclass override detection (graduation loop dispatch)
**Source:** `services/alpha_swarm_agent.py` line 217 (override) + `base_group_service.py` line 190 (dispatch)
```python
# Replace flag-based dispatch:
if type(self)._graduation_loop is not BaseGroupService._graduation_loop:
    tasks.append(asyncio.create_task(self._graduation_loop()))
```

### structlog event key collision rule
**Source:** CLAUDE.md key rules
Never pass `event=<value>` as a keyword argument to structlog. Use `signal=`, `payload=`, `data=`, or descriptive names instead.

---

## No Analog Found

All files have exact analogs (they are self-referential modifications to existing base classes).

| File | Role | Data Flow | Note |
|------|------|-----------|------|
| n/a | n/a | n/a | All changes are in-place modifications to well-established base classes |

---

## Critical Pitfalls (from RESEARCH.md — must be embedded in plan actions)

1. **`_do_flush()` re-raise breaks two tests** — `test_no_commit_on_flush_failure` (line 189) and `test_flush_errors_counter_increments_on_failure` (line 309) in `test_base_writer_agent.py` both call `await agent._do_flush()` without `pytest.raises`. Both must be updated before the implementation change or CI will fail.

2. **`AlphaSwarmAgent.has_graduation = True` becomes orphan** — after deleting `has_graduation` from `BaseGroupService`, remove `has_graduation = True` from `AlphaSwarmAgent` (line 121 of `alpha_swarm_agent.py`). The dispatch now uses method override detection.

3. **`AlphaSwarmAgent` double-LineageRecorder** — `BaseGroupService._setup()` must guard with `if not hasattr(self, "_lineage") or self._lineage is None`. Then `AlphaSwarmAgent._setup()` lines 180-184 must be deleted to consolidate onto the base instance.

4. **`_setup_with_retry()` local var shadowing** — Replace `_attempts = 3` and `_backoff_base = 2.0` (lines 452-453) with `self.SETUP_RETRY_ATTEMPTS` and `self.SETUP_RETRY_BACKOFF_S` throughout the method body. Failing to replace one still leaves the hardcoded value in effect.

5. **`agent_last_processed_timestamp` already exists** — `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` in `metrics.py` (line 199) with label `{agent}` satisfies D-09 item 2. Do not create a duplicate `agent_last_processed_timestamp` instrument.

6. **`_on_error` needs `LineageRecorder` but `BaseAIAgent` doesn't own it** — inject via `agent._lineage = self._lineage` in `BaseGroupService._setup()` after the recorder is created. Guard all `.record()` calls with `if self._lineage is not None`.

---

## Metadata

**Analog search scope:** `src/core/agent/`, `src/core/ai/`, `src/observability/`, `tests/unit/`, `services/alpha_swarm_agent.py`, `src/core/plugin_circuit_breaker.py`
**Files scanned:** 10
**Pattern extraction date:** 2026-05-16
