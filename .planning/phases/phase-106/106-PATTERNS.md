# Phase 106: Foundation Hardening - Pattern Map

**Mapped:** 2026-05-23
**Files analyzed:** 8 files to create or modify
**Analogs found:** 8 / 8

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/service_auditor_agent.py` | service / registry | event-driven | self (existing `_DAG_ORDER` at lines 55-154) | self-edit |
| `services/intelligence_pipeline_agent.py` | agent / orchestrator | request-response | self (existing `PluginExecutor` wiring at line 280) | self-edit |
| `src/intelligence/pipeline/executor.py` | service | CRUD | self (existing `circuit_breakers` param at line 168) | self-edit |
| `src/intelligence/pipeline/state_manager.py` | service | CRUD | `src/intelligence/pipeline/executor.py` `_plugin_circuit_breakers` dict (secondary index pattern) | role-match |
| `services/bar_aggregator_agent.py` | agent | request-response | `src/core/agent/base.py` `_setup_with_retry()` (lines 488-511) | role-match |
| `src/core/ml/shadow.py` | dead code | — | `src/core/llm/guardrails.py` (same archival pattern) | role-match |
| `src/core/llm/guardrails.py` + `src/core/llm/chain.py` | dead code + consumer | — | `src/core/ml/shadow.py` (archived stub) | role-match |
| `src/config/settings.py` | config | — | self (existing `SWARM_QUEUE_TIMEOUT_MS` field comment at line 182) | self-edit |

---

## Pattern Assignments

### `services/service_auditor_agent.py` (DAG correctness)

**Analog:** Self — existing dict definitions at `services/service_auditor_agent.py` lines 55-154.

**`_DAG_ORDER` entry format** (lines 55-96):
```python
# Priority 0 — infrastructure sentinels (not restartable)
"indicagent-redpanda-ready": 0,
"indicagent-redpanda-watchdog": 0,

# Priority 8 — timer-triggered oneshots (inactive between runs is correct)
"indicagent-ml-training": 8,  # oneshot timer service; no lag threshold needed
"indicagent-ml-signal-training-materialize": 8,  # oneshot timer service; no lag threshold needed

# Priority 10 — always-on top-level
"indicagent-service-auditor": 10,
```

**`_LAG_THRESHOLDS` entry format** (lines 99-121):
```python
_LAG_THRESHOLDS: dict[str, int] = {
    "indicagent-graduation-compute": 500,   # to be added
    "indicagent-roll-compute": 500,         # to be added
    # Existing entries follow the same pattern: unit-name -> integer threshold
    "indicagent-graduation-writer": 500,
    ...
}
```

**`_AGENT_ID_TO_UNIT` key format** (lines 126-154):
```python
# Keys MUST match the name= argument in each service's super().__init__() call
# because that becomes the agent_id label on PERSISTENCE_CONSUMER_LAG in base.py.
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "feature_writer": "indicagent-feature-writer",   # BUG: should be "feature_writer_agent"
    ...
}
```

**`_ONESHOT_UNITS` guard pattern** (to be added, per RESEARCH.md pattern):
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
# Guard in graduated restart loop (find the restart call site near line 381):
if unit_name in _ONESHOT_UNITS:
    continue  # timer-triggered; systemd timer handles restart
```

**Sorted unit helper already uses `_DAG_ORDER`** (line 312):
```python
return sorted(units, key=lambda u: _DAG_ORDER.get(u, 99))
```

---

### `services/intelligence_pipeline_agent.py` (PluginCircuitBreaker wiring + enqueue_blocking)

**Analog:** Self — existing `PluginExecutor` instantiation at line 280, and `enqueue_blocking` usage at line 529.

**Current broken wiring** (line 284):
```python
self._executor = PluginExecutor(
    thread_pool=self._thread_pool,
    plugin_cache=self._plugin_cache,
    instrument_map=self._instrument_map,
    circuit_breakers={},   # PROBLEM: always empty
    observer=PluginObserver(),
)
```

**Target: populate from plugin cache at `_setup()` time.** Pattern for `PluginCircuitBreaker` instantiation comes from `src/providers/ibkr.py` lines 105-114:
```python
_ibkr_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=180,
        success_threshold=2,
        max_half_open_calls=2,
        failure_window=120,
        performance_threshold_ms=20000.0,
    )
)
```

**`enqueue_blocking` (correct) vs `enqueue` (broken)** — line 529 is already correct:
```python
# CORRECT — signals use blocking enqueue (already done):
await self._out_queue.enqueue_blocking(...)
# BROKEN — intel topic and journal topic use non-blocking (lines 507, 598):
self._out_queue.enqueue(intel_topic, msg_key, {...})  # line 507
self._out_queue.enqueue(topic_intelligence_journal(...), msg_key, ...)  # line 598
```
Fix: change both to `await self._out_queue.enqueue_blocking(...)`.

**`OutputQueue` API** (from `src/intelligence/pipeline/output_queue.py`):
```python
# Non-blocking — drops on QueueFull:
def enqueue(self, topic: str, key: str, value: Any) -> None: ...

# Blocking — backs up instead of dropping:
async def enqueue_blocking(self, topic: str, key: str, value: Any) -> None: ...
```

---

### `src/intelligence/pipeline/executor.py` (PluginCircuitBreaker instantiation)

**Analog:** Self — `PluginExecutor.__init__` at lines 163-184, `_get_plugin_cb` at line 199.

**Current `circuit_breakers` param wiring** (lines 163-174):
```python
def __init__(
    self,
    thread_pool: ThreadPoolExecutor,
    plugin_cache: dict,
    instrument_map: dict,
    circuit_breakers: dict,
    observer: PluginObserver | NoOpPluginObserver | None = None,
) -> None:
    ...
    self._plugin_circuit_breakers: dict[str, CircuitBreaker] = dict(circuit_breakers)
```

**`_get_plugin_cb` lazy-init pattern** (line 199):
```python
def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
    cb = self._plugin_circuit_breakers.get(plugin_name)
    # If None, creates and stores a default CircuitBreaker for the plugin
    self._plugin_circuit_breakers[plugin_name] = cb
```

**Note:** `executor.py` uses `src.observability.circuit_breaker.CircuitBreaker` (the simple local one), NOT `src.core.plugin_circuit_breaker.PluginCircuitBreaker` (the 584-line IBKR-style one). The RESEARCH.md's shadow-mode `enabled: bool` flag targets `PluginCircuitBreaker`; the executor uses the lighter `CircuitBreaker`. Verify which class to wire before writing the plan actions.

**Import pattern in executor.py** (lines 42-46):
```python
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
from src.observability.metrics import (
    FEATURES_COMPUTED_TOTAL,
    counter,
)
```

---

### `src/intelligence/pipeline/state_manager.py` (O(1) secondary index)

**Analog:** `src/intelligence/pipeline/executor.py` — the `_plugin_circuit_breakers` dict uses the same secondary-index pattern: `dict[str, X]` built at write time, O(1) at read time.

**Current O(N) scan** (`state_manager.py` lines 91-102):
```python
def get_all_states_for(self, symbol: str, tf: str) -> dict[str, dict]:
    return {
        plugin_name: state
        for (plugin_name, s, t), state in self._plugin_states.items()
        if s == symbol and t == tf
    }
```

**Target secondary index pattern** (from RESEARCH.md — verified against state_manager.py `__init__` at line 68):
```python
# In __init__ (after line 71 which declares _plugin_states):
self._states_by_key: dict[tuple[str, str], dict[str, dict]] = {}

# In update() (after line 127 which writes to _plugin_states):
def update(self, key: tuple, state: dict) -> None:
    self._plugin_states[key] = state
    plugin_name, symbol, tf = key
    self._states_by_key.setdefault((symbol, tf), {})[plugin_name] = state

# In update_batch() — same pattern per entry:
def update_batch(self, state_updates: dict) -> None:
    for key, state in state_updates.items():
        self._plugin_states[key] = state
        plugin_name, symbol, tf = key
        self._states_by_key.setdefault((symbol, tf), {})[plugin_name] = state

# get_all_states_for becomes O(1):
def get_all_states_for(self, symbol: str, tf: str) -> dict[str, dict]:
    return dict(self._states_by_key.get((symbol, tf), {}))

# Checkpoint restore — rebuild derived index, do NOT serialize _states_by_key:
self._states_by_key = {}
for (plugin_name, symbol, tf), state in self._plugin_states.items():
    self._states_by_key.setdefault((symbol, tf), {})[plugin_name] = state
```

---

### `services/bar_aggregator_agent.py` (remove manual retry loop)

**Analog:** `src/core/agent/base.py` — `_setup_with_retry()` at lines 488-511.

**Current manual retry loop** (`bar_aggregator_agent.py` lines 203-267):
```python
async def _setup(self) -> None:
    import aiokafka
    from aiokafka.errors import KafkaConnectionError as _KCE

    _MAX_ATTEMPTS = 4  # 1 initial + 3 retries
    _BASE_DELAY = 2.0  # seconds

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            ...
            return
        except _KCE as exc:
            # cleanup ...
            if attempt == _MAX_ATTEMPTS:
                raise
            delay = _BASE_DELAY * (2 ** (attempt - 1))
            await asyncio.sleep(delay)
```

**BaseAgent retry class attributes** (`src/core/agent/base.py` lines 91-92):
```python
SETUP_RETRY_ATTEMPTS: int = 3
SETUP_RETRY_BACKOFF_S: float = 2.0
```

**`_setup_with_retry()` in BaseAgent** (lines 488-511):
```python
async def _setup_with_retry(self) -> None:
    for attempt in range(self.SETUP_RETRY_ATTEMPTS):
        try:
            await self._setup()
            return
        except Exception as exc:
            if attempt == self.SETUP_RETRY_ATTEMPTS - 1:
                raise
            backoff = self.SETUP_RETRY_BACKOFF_S**attempt
            AGENT_SETUP_RETRIES_TOTAL.add(1, self._cb_attrs)
            self.logger.warning(
                "agent.setup_retry",
                attempt=attempt + 1,
                max_attempts=self.SETUP_RETRY_ATTEMPTS,
                backoff_seconds=backoff,
                error=str(exc),
            )
            await asyncio.sleep(backoff)
```

**Migration pattern:** Delete the manual loop from `bar_aggregator_agent._setup()`. The loop is called via `_setup_with_retry()` automatically (see `base.py` line 218: `await self._setup_with_retry()`). Override `SETUP_RETRY_ATTEMPTS = 4` and `SETUP_RETRY_BACKOFF_S = 2.0` as class attributes if the exact behavior needs to match the current 4-attempt / 2s schedule.

---

### `src/core/ml/shadow.py` (dead code deletion)

**Analog:** `src/core/llm/guardrails.py` — same pattern (53-line file, class with no active callers, import chain to clean up).

**Deletion checklist from `shadow.py`:**
- Module docstring says "ARCHIVED in Phase 78 (D-04)" (line 1)
- Module-level `warnings.warn(DeprecationWarning)` fires on import (lines 17-21)
- `ShadowRecorder` class at line 42
- `src/core/ml/__init__.py:12` documents the removal — verify it does not re-export `ShadowRecorder`
- Grep for any `from src.core.ml.shadow import` or `import shadow` before deleting

**Safe deletion sequence:**
1. `grep -rn "shadow.ShadowRecorder\|from src.core.ml.shadow\|ml.shadow" src/ services/ tests/` — confirm zero callers
2. Delete `src/core/ml/shadow.py`
3. If `src/core/ml/__init__.py` references it, remove that line

---

### `src/core/llm/guardrails.py` + `src/core/llm/chain.py` (dead code deletion with chain cleanup)

**Analog:** Same archival pattern as `shadow.py`, but with an active import chain that must be cleaned first.

**`guardrails.py`** (`src/core/llm/guardrails.py` lines 1-53):
```python
class GuardrailsValidator:
    def __init__(self) -> None:
        self._schemas: dict[str, Any] = {}  # never populated
    def register(self, call_type: str, schema: Any) -> None: ...
    def has_schema(self, call_type: str) -> bool:
        return call_type in self._schemas  # always False
    def validate(self, ...) -> dict[str, Any] | None: ...
```

**`chain.py` import and usage to remove** (lines 17, 37, 194-203):
```python
# Line 17 — remove this import:
from src.core.llm.guardrails import GuardrailsValidator

# Line 37 — remove this singleton:
_guardrails = GuardrailsValidator()

# Lines 194-203 — remove this dead branch (has_schema always False):
if _guardrails.has_schema(self._call_type):
    validated = _guardrails.validate(self._call_type, response)
    if validated is None:
        LLM_GUARDRAILS_REJECTIONS.add(1, {"call_type": self._call_type})
        record_llm_call(...)
        return None
```

**`LLM_GUARDRAILS_REJECTIONS` metric** — also imported from `src/observability/metrics.py` at chain.py line 25. If the only usage was the dead branch, remove that import too. Verify before removing.

**Safe deletion sequence:**
1. Remove import from chain.py line 17
2. Remove `_guardrails = GuardrailsValidator()` from chain.py line 37
3. Remove the `if _guardrails.has_schema(...)` block from `_generate_inner()` (lines 194-203)
4. Remove `LLM_GUARDRAILS_REJECTIONS` from chain.py import if no other callers
5. Delete `src/core/llm/guardrails.py`
6. Update chain.py docstring at line 3 (remove "GuardrailsValidator" from composition list)

---

### `src/config/settings.py` (dead Settings fields removal)

**Analog:** Self — existing field `SWARM_QUEUE_TIMEOUT_MS` at line 179 demonstrates the `Field(default=..., description="Deprecated — ...")` approach for fields that need to be kept for env-var compatibility.

**Dead fields confirmed** (lines 221-242):
```python
LLM_RATE_LIMIT_RPM: int = Field(default=60, description="Default LLM requests per minute")
LLM_RATE_LIMIT_TPM: int = Field(default=100_000, description="Default LLM tokens per minute")

SHADOW_CORRELATION_THRESHOLD: float = Field(
    default=0.4, description="Min Pearson rho for promotion"
)
SHADOW_MIN_SAMPLES: int = Field(default=100, description="Min N for promotion consideration")

MLFLOW_TRACKING_URI: str = Field(
    default="http://localhost:5000", description="MLflow server URI"
)
LANGFUSE_HOST: str = Field(default="http://localhost:3010", description="LangFuse server URI")
```

**`SWARM_QUEUE_TIMEOUT_MS` — verify before removing** (line 179):
```python
SWARM_QUEUE_TIMEOUT_MS: int = Field(
    default=250,
    validation_alias="SWARM_QUEUE_TIMEOUT_MS",
    description="Deprecated — semaphore timeout removed (D-07). Kafka lag-skip is the backpressure valve. Setting retained for env-var compatibility.",
)
```
The description says "retained for env-var compatibility" — the test at `tests/unit/services/test_alpha_swarm_agent.py:570` passes it as a constructor kwarg. Before removing: check `services/alpha_swarm_compute_agent.py` for `settings.SWARM_QUEUE_TIMEOUT_MS`. If not used in production, remove the field AND fix the test.

**Safe deletion sequence:**
```
grep -rn "LLM_RATE_LIMIT_RPM\|LLM_RATE_LIMIT_TPM\|SHADOW_CORRELATION_THRESHOLD\|SHADOW_MIN_SAMPLES\|LANGFUSE_HOST\|MLFLOW_TRACKING_URI" src/ services/ tests/
```
Confirm zero callers outside `settings.py`, then delete the fields.

---

## Shared Patterns

### JSONB Pool Creation (3 services need migration)

**Source:** `src/core/database_manager.py` lines 25-30
**Apply to:** `services/swarm_ledger_writer_agent.py:89`, `services/bar_replay_provider_agent.py:60`, `services/signal_replay_auditor_agent.py:69`

```python
# WRONG (direct asyncpg, skips JSONB codecs):
self._pool = await asyncpg.create_pool(
    self.settings.database_url,
    min_size=2,
    max_size=8,
)

# CORRECT (wrapper registers JSONB codecs + emits pool gauges):
from src.core.database_manager import create_pool as create_db_pool
self._pool = await create_db_pool(
    self.settings.database_url,
    pool_name="swarm_ledger_writer",  # distinct name per service
    min_size=2,
    max_size=8,
)
```

### PluginCircuitBreaker Instantiation

**Source:** `src/providers/ibkr.py` lines 104-114
**Apply to:** `src/intelligence/pipeline/executor.py` (when building per-plugin dict)

```python
from src.core.plugin_circuit_breaker import (
    CircuitBreakerConfig,
    PluginCircuitBreaker,
)

_ibkr_circuit_breaker = PluginCircuitBreaker(
    config=CircuitBreakerConfig(
        failure_threshold=3,
        recovery_timeout=180,
        success_threshold=2,
        max_half_open_calls=2,
        failure_window=120,
        performance_threshold_ms=20000.0,
    )
)
```
Note: `executor.py` currently uses the lighter `src.observability.circuit_breaker.CircuitBreaker`, not `PluginCircuitBreaker`. The plan must decide which class to use per RESEARCH.md requirement (shadow mode `enabled: bool` flag is on `PluginCircuitBreaker`).

### Structlog Warning on State Transition

**Source:** `src/intelligence/pipeline/executor.py` lines 261-262:
```python
self._observer.record_circuit_breaker_change(task.plugin_name, "open")
self._logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
```

### OTel Metric via `opentelemetry.metrics.get_meter` (avoid circular import)

**Source:** RESEARCH.md Pitfall 5 — use `opentelemetry.metrics.get_meter("indicagent")` directly in `plugin_circuit_breaker.py` rather than importing `_meter` from `src/observability/metrics.py`.

```python
# Safe pattern to avoid circular import:
from opentelemetry import metrics as _otel_metrics
_meter = _otel_metrics.get_meter("indicagent")
_cb_state_gauge = _meter.create_gauge(
    "intelligence_pipeline_plugin_cb_state",
    description="Plugin circuit breaker state (0=closed, 1=open, 2=half-open)",
)
```

---

## No Analog Found

All files have analogs in the existing codebase. The patterns required are either self-edits or direct copies from existing implementations.

---

## Metadata

**Analog search scope:** `services/`, `src/intelligence/pipeline/`, `src/core/`, `src/config/`, `src/observability/`, `src/providers/`
**Files scanned:** 14 source files read directly
**Pattern extraction date:** 2026-05-23
