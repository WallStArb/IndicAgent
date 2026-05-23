# Phase 086: Pipeline Hardening - Pattern Map

**Mapped:** 2026-05-17
**Files analyzed:** 6 files (5 modified, 1 new)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `services/intelligence_pipeline_agent.py` | service | event-driven | self (modify in place) | exact |
| `services/signal_writer_agent.py` | service | CRUD | self (modify in place) | exact |
| `src/core/agent/base.py` | base-class | request-response | self (modify in place) | exact |
| `src/api/routes/health.py` | route | request-response | `services/service_auditor_agent.py` | role-match |
| `services/service_auditor_agent.py` | service | event-driven | self (modify in place) | exact |
| `src/observability/circuit_breaker.py` | utility | request-response | self (read-only reference) | exact |

---

## Pattern Assignments

### `services/intelligence_pipeline_agent.py` — PIPE-01, PIPE-03, PIPE-04

**Analog:** self — three distinct changes inside the same file.

---

#### PIPE-01: Per-plugin circuit breaker

**Where to add `_plugin_circuit_breakers` dict** (near line 476, alongside `_output_queue`):
```python
# In __init__ (alongside _output_queue setup):
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
from src.observability.metrics import CIRCUIT_BREAKER_STATE

self._plugin_circuit_breakers: dict[str, CircuitBreaker] = {}

def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
    if plugin_name not in self._plugin_circuit_breakers:
        self._plugin_circuit_breakers[plugin_name] = CircuitBreaker(
            failure_threshold=3, timeout_sec=300
        )
    return self._plugin_circuit_breakers[plugin_name]
```

**Skip guard — add to `_run_i1` before `tasks.append()`** (lines 1104-1126), same pattern for `_run_tier` (lines 1175-1199) and `_run_i7_inner` (lines 1301-1325):
```python
# In _run_i1, _run_tier, _run_i7_inner — before tasks.append():
cb = self._get_plugin_cb(plugin_name)
if cb.state == CircuitState.OPEN:
    continue  # skip this plugin for this bar
```

**Failure recording — add to `_collect_plugin_results` exception branch** (lines 1069-1074):
```python
# Current code at lines 1069-1074:
if isinstance(out, Exception):
    self._pipeline_errors.add(1)
    PLUGIN_ERRORS_TOTAL.add(1, {"plugin_name": task.plugin_name, "tier": tier})
    self.logger.warning(
        f"{log_prefix}.error", plugin=task.plugin_name, tier=tier, error=str(out)
    )
    # ADD: circuit breaker recording
    cb = self._get_plugin_cb(task.plugin_name)
    cb.record_failure()
    if cb.state == CircuitState.OPEN:
        CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": task.plugin_name})
        self.logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
```

**CircuitBreaker API reference** (`src/observability/circuit_breaker.py` lines 76-91):
```python
def record_failure(self) -> None:
    """Manually record a failure (for use in try/except outside call())."""
    self._failures += 1
    self._last_failure_time = time.time()
    if self._failures >= self.failure_threshold:
        self._state = CircuitState.OPEN

@property
def state(self) -> CircuitState:
    """Current circuit state."""
    return self._state
```

**Metric name for gauge:** `plugin_circuit_breaker_state` — label key `plugin_name`. Instrument: `CIRCUIT_BREAKER_STATE` from `src/observability/metrics.py` line 67. Call: `.set(1, {"plugin_name": name})`.

---

#### PIPE-03: Checkpoint write failure must raise

**Current swallowing code** (lines 1526-1537) — remove the `try/except`:
```python
# CURRENT (lines 1526-1537):
def _write_local_checkpoint(self) -> None:
    """Write hot indicator state to local file. Best-effort — never raises."""
    try:
        payload: dict = {"version": _AGENT_VERSION, "ts": datetime.now(UTC).isoformat()}
        for field in _CHECKPOINT_FIELDS:
            payload[field] = _tag_value(getattr(self, f"_{field}"))
        tmp = _CHECKPOINT_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload))
        tmp.rename(_CHECKPOINT_PATH)
        self.logger.info("state.checkpoint_written", path=str(_CHECKPOINT_PATH))
    except Exception as exc:
        self.logger.warning("state.checkpoint_write_failed", error=str(exc))

# TARGET — remove try/except, let OSError propagate:
def _write_local_checkpoint(self) -> None:
    """Write hot indicator state to local file. Raises on failure."""
    payload: dict = {"version": _AGENT_VERSION, "ts": datetime.now(UTC).isoformat()}
    for field in _CHECKPOINT_FIELDS:
        payload[field] = _tag_value(getattr(self, f"_{field}"))
    tmp = _CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(_CHECKPOINT_PATH)
    self.logger.info("state.checkpoint_written", path=str(_CHECKPOINT_PATH))
```

**Caller context:** `_write_local_checkpoint()` is called in `_teardown()` at line 701. Do NOT add a try/except in `_teardown()` — let it propagate so it surfaces in structured logs under `agent.run_failed`.

---

#### PIPE-04: Blocking enqueue

**Current `_enqueue` method** (lines 1017-1022):
```python
def _enqueue(self, topic: str, key: str, value: Any) -> None:
    """Non-blocking enqueue to output buffer. Drops on QueueFull."""
    try:
        self._output_queue.put_nowait((topic, key, value))
    except asyncio.QueueFull:
        self._output_buffer_drops.add(1)
```

**New async `_enqueue_blocking` method — add alongside `_enqueue`:**
```python
async def _enqueue_blocking(self, topic: str, key: str, value: Any) -> None:
    """Blocking enqueue — waits for space, emits metric on full."""
    if self._output_queue.full():
        self._output_buffer_drops.add(1)
        self.logger.warning("output_queue.full_blocking", qsize=self._output_queue.qsize())
    await self._output_queue.put((topic, key, value))
```

**Metric used:** `self._output_buffer_drops` — counter `intelligence_pipeline_output_buffer_drops_total` (line 492-493). Reuse; do NOT create a second metric.

**Call sites to convert** — replace `self._enqueue(...)` with `await self._enqueue_blocking(...)` at:
- `_publish_signals_or_dlq` (lines 1581 area) — signal publish path
- Winner enqueue in `_run_i7_inner` (lines 1505 area) — signal output path

Keep `self._enqueue(...)` (non-blocking) for:
- `_enqueue_intel_journal` (line 1687) — journal/non-critical path
- IntelligenceEvent enqueue (line 886) — non-signal path

**Pitfall:** `_enqueue_intel_journal` is sync (line 1647). If it calls `_enqueue_blocking`, it must become async and its caller in `_process_bar_inner` (line 897) must `await` it. Avoid this churn — only convert the signal paths.

---

### `services/signal_writer_agent.py` — PIPE-02

**Analog:** self — add validation gate inside `_parse_payload` with a pending DLQ buffer pattern.

**Current `_parse_payload`** (lines 92-94):
```python
def _parse_payload(self, payload: dict) -> list | None:
    rows = _payload_to_ledger_entries(payload)
    return rows if rows else None
```

**Current `_dlq_topic` override** (lines 85-87 — already wired):
```python
def _dlq_topic(self) -> str | None:
    """Route unparseable signal payloads to DLQ."""
    return topic_signal_writer_dlq(self.settings.env_name)
```

**`validate_signal` API** (`src/intelligence/trading/signal_schema.py` lines 41-58):
```python
from src.intelligence.trading.signal_schema import validate_signal

def validate_signal(signal: dict) -> bool:
    """Validate a signal.v1 dictionary. Returns True if valid."""
    if not isinstance(signal, dict):
        return False
    if not REQUIRED_SIGNAL_FIELDS.issubset(signal.keys()):
        return False
    if signal.get("type") != "signal.v1":
        return False
    conf = signal.get("confidence")
    if not isinstance(conf, (int, float)) or conf < 0.0 or conf > 1.0:
        return False
    direction = signal.get("direction")
    if direction not in (1, -1, 1.0, -1.0):
        return False
    targets = signal.get("targets")
    if not isinstance(targets, list) or len(targets) == 0:
        return False
    return True
```

**Pattern for async DLQ from sync `_parse_payload`** — use a pending buffer, drain in `_flush_batch`:
```python
def __init__(self, ...):
    # ADD in __init__:
    self._invalid_signals: list[dict] = []

def _parse_payload(self, payload: dict) -> list | None:
    from src.intelligence.trading.signal_schema import validate_signal
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    valid, invalid = [], []
    for sig in signals:
        if validate_signal(sig):
            valid.append(sig)
        else:
            invalid.append(sig)
    self._invalid_signals.extend(invalid)  # drain async in _flush_batch
    rows = _payload_to_ledger_entries({**payload, "signals": valid})
    return rows if rows else None

async def _flush_batch(self, batch: list) -> None:
    # Drain invalid signals to DLQ first
    for sig in self._invalid_signals:
        await self._send_to_dlq(sig, ValueError("validate_signal failed"))
    self._invalid_signals.clear()
    # ... existing flush logic:
    t0 = time.perf_counter()
    assert self._repo is not None
    await self._repo.insert_signals(batch)
    self._signals_written.add(len(batch))
    PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
    self.logger.info("signal_writer.flushed", count=len(batch))
```

**`_send_to_dlq` API** (`src/core/agent/base.py` lines 355-385 — inherited):
```python
async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
    # Emits AGENT_DLQ_TOTAL, builds DLQPayload, publishes to _dlq_topic()
    # Already wired — SignalWriterAgent._dlq_topic() returns topic_signal_writer_dlq(env_name)
```

---

### `src/core/agent/base.py` — OBS-03

**Analog:** self — add `last_processed_at` property alongside existing `_last_message_ts` monotonic field.

**Current `__init__` (line 116) and `_record_message_consumed` (lines 295-304):**
```python
# In __init__ (line 116):
self._last_message_ts: float | None = None

def _record_message_consumed(self) -> None:
    self._last_message_ts = time.monotonic()
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.set(time.time(), self._last_msg_ts_attrs)
```

**Changes:**
```python
# ADD to __init__ (after line 116):
from datetime import UTC, datetime
self._last_processed_at: datetime | None = None

# ADD property after _record_message_consumed:
@property
def last_processed_at(self) -> "datetime | None":
    """Wall-clock UTC datetime of last successfully processed message."""
    return self._last_processed_at

# MODIFY _record_message_consumed to set wall-clock alongside monotonic:
def _record_message_consumed(self) -> None:
    self._last_message_ts = time.monotonic()
    self._last_processed_at = datetime.now(UTC)   # ADD THIS LINE
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.set(time.time(), self._last_msg_ts_attrs)
```

**Import note:** `datetime` is not yet imported at the top of `base.py`. The `_record_message_consumed` method already uses `time` (imported at line 29). Add `from datetime import UTC, datetime` to the import block.

---

### `src/api/routes/health.py` — OBS-02 (new `/system` route)

**Analog:** `services/service_auditor_agent.py` — `_query_prometheus` method (lines 598-608) is the exact pattern to copy for aiohttp Prometheus queries.

**Prometheus query pattern** (`services/service_auditor_agent.py` lines 598-608):
```python
async def _query_prometheus(self, query: str) -> list[dict]:
    assert self._http_session is not None
    async with self._http_session.get(
        _PROMETHEUS_URL,
        params={"query": query},
        timeout=aiohttp.ClientTimeout(total=5),
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
    return data.get("data", {}).get("result", [])
```

**Existing route structure** (`src/api/routes/health.py` lines 1-73) — add the new route at bottom of file using the same `@router.get(...)` pattern:
```python
@router.get("/system")
async def system_health():
    """Machine-readable system health: lag, DLQ depth, agent heartbeats."""
    import aiohttp
    from datetime import UTC, datetime

    prom_url = "http://localhost:9090/api/v1/query"
    timeout = aiohttp.ClientTimeout(total=3)
    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "consumer_lag": {},
        "dlq_depth": None,
        "signal_replay_unresolved": None,
        "agent_heartbeats": {},
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Consumer lag by agent_id (label key matches PERSISTENCE_CONSUMER_LAG attrs)
        try:
            async with session.get(prom_url, params={"query": "persistence_consumer_lag_records"}) as r:
                data = await r.json()
                for item in data.get("data", {}).get("result", []):
                    agent_id = item["metric"].get("agent_id", "unknown")
                    result["consumer_lag"][agent_id] = int(float(item["value"][1]))
        except Exception:
            pass

        # DLQ depth — sum all agent_dlq_total
        try:
            async with session.get(prom_url, params={"query": "agent_dlq_total"}) as r:
                data = await r.json()
                total = sum(float(i["value"][1]) for i in data.get("data", {}).get("result", []))
                result["dlq_depth"] = int(total)
        except Exception:
            pass

        # signal_replay_unresolved
        try:
            async with session.get(prom_url, params={"query": "signal_replay_unresolved_gauge"}) as r:
                data = await r.json()
                items = data.get("data", {}).get("result", [])
                if items:
                    result["signal_replay_unresolved"] = int(float(items[0]["value"][1]))
        except Exception:
            pass

        # Agent heartbeats (label key is "agent" per _last_msg_ts_attrs in base.py)
        try:
            async with session.get(
                prom_url, params={"query": "agent_last_message_timestamp_seconds"}
            ) as r:
                data = await r.json()
                for item in data.get("data", {}).get("result", []):
                    agent = item["metric"].get("agent", "unknown")
                    ts = float(item["value"][1])
                    result["agent_heartbeats"][agent] = datetime.fromtimestamp(ts, tz=UTC).isoformat()
        except Exception:
            pass

    return result
```

**Router registration:** `src/api/main.py` — verify `app.include_router(health.router, prefix="/api/health", ...)` is already present. The new `/system` function on the existing router will be served at `/api/health/system` automatically.

---

### `services/service_auditor_agent.py` — OBS-03 (stall detection via Prometheus)

**Analog:** self — add stall detection to the existing `_prometheus_check_loop` using the same `_query_prometheus` helper.

**Existing `_fetch_prometheus_lag` pattern** (lines 556-563) — copy same query structure:
```python
async def _fetch_prometheus_lag(self) -> dict[str, int]:
    results = await self._query_prometheus("persistence_consumer_lag")
    out: dict[str, int] = {}
    for r in results:
        unit = _AGENT_ID_TO_UNIT.get(r["metric"].get("agent_id", ""))
        if unit:
            out[unit] = int(float(r["value"][1]))
    return out
```

**New method to add:**
```python
_STALL_THRESHOLD_SECONDS: int = 360  # 6 min = max_idle_seconds(300) + 60s grace

async def _fetch_stalled_agents(self) -> list[str]:
    """Return agent names that have not processed a message in STALL_THRESHOLD_SECONDS."""
    results = await self._query_prometheus("agent_last_message_timestamp_seconds")
    now = time.time()
    stalled: list[str] = []
    for r in results:
        ts = float(r["value"][1])
        agent = r["metric"].get("agent", "")
        if now - ts > _STALL_THRESHOLD_SECONDS and agent:
            stalled.append(agent)
    return stalled
```

**Wire into `_prometheus_check_loop`** (line 296) — call `_fetch_stalled_agents()` alongside existing checks, restart via existing `_restart_unit()` or `_trigger_restart()` helper (check which exists in the file).

---

## Shared Patterns

### OTel Metric Call Conventions
**Source:** `src/observability/metrics.py` + `CLAUDE.md`
**Apply to:** All metric calls in PIPE-01, PIPE-04

```python
# Counter: .add(1, {label: value})
PLUGIN_ERRORS_TOTAL.add(1, {"plugin_name": task.plugin_name, "tier": tier})
AGENT_DLQ_TOTAL.add(1, self._dlq_attrs)

# Gauge: .set(value, {label: value})
CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": task.plugin_name})
AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.set(time.time(), self._last_msg_ts_attrs)

# Histogram: .record(value, {label: value})
PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
```

**Never import `prometheus_client`** — fully removed in Phase 83.

### Structured Logging
**Source:** All existing agents
**Apply to:** All new log statements

```python
# Always use keyword args, never positional string formatting
self.logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
self.logger.error("state.checkpoint_write_failed", error=str(exc))
self.logger.warning("output_queue.full_blocking", qsize=self._output_queue.qsize())

# Never use event= as a kwarg (structlog collision — see CLAUDE.md)
# Use signal=, payload=, data= instead
```

### DLQ Routing
**Source:** `src/core/agent/base.py` lines 355-400
**Apply to:** PIPE-02 (signal_writer_agent), any new DLQ path

```python
# _send_to_dlq is async, inherited from BaseAgent.
# Prerequisites: _dlq_topic() must be overridden to return a topic string.
# SignalWriterAgent already overrides _dlq_topic() at lines 85-87.
await self._send_to_dlq(payload_dict, ValueError("reason"))
# Emits: AGENT_DLQ_TOTAL counter, DLQ_MESSAGES_TOTAL counter, publishes DLQPayload
```

### Prometheus Query (aiohttp)
**Source:** `services/service_auditor_agent.py` lines 598-608
**Apply to:** OBS-02 health route, OBS-03 stall detection

```python
async with self._http_session.get(
    _PROMETHEUS_URL,          # "http://localhost:9090/api/v1/query"
    params={"query": query},
    timeout=aiohttp.ClientTimeout(total=5),
) as resp:
    if resp.status != 200:
        return []
    data = await resp.json()
return data.get("data", {}).get("result", [])
```

For the health route (no persistent session): wrap in `aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))` context manager. Swallow all exceptions — return degraded values, never 503.

---

## No Analog Found

No files in this phase lack analogs. All patterns are satisfied by existing code in the repository.

---

## Metadata

**Analog search scope:** `services/`, `src/core/agent/`, `src/api/routes/`, `src/observability/`, `src/intelligence/trading/`
**Files scanned:** 9 (read directly) + grep across all services
**Pattern extraction date:** 2026-05-17
