# Phase 086: Pipeline Hardening - Research

**Researched:** 2026-05-17
**Domain:** Fault tolerance, observability, and pipeline reliability for IntelligencePipelineComputeAgent and related services
**Confidence:** HIGH

---

## Summary

Phase 086 hardens six specific failure modes in the intelligence pipeline and its surrounding services. The codebase has substantial scaffolding already — two circuit breaker implementations, DLQ infrastructure, a working `_send_to_dlq` base method, and `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` — but none of the six requirements are wired at the points specified.

The pipeline agent (`services/intelligence_pipeline_agent.py`) is the primary target for PIPE-01, PIPE-03, and PIPE-04. `services/signal_writer_agent.py` is the target for PIPE-02. `src/core/agent/base.py` is the target for OBS-03 (`last_processed_at`). `src/api/routes/health.py` and the FastAPI app are the target for OBS-02.

**Primary recommendation:** Wire existing infrastructure rather than building new. All six requirements can be satisfied by connecting pieces that exist but are not yet integrated at the required call sites.

---

## Standard Stack

### Core (already in codebase)

| Library/Module | Location | Purpose |
|---|---|---|
| `CircuitBreaker` | `src/observability/circuit_breaker.py` | Leaner CLOSED/OPEN/HALF_OPEN state machine — use this for PIPE-01 |
| `PluginCircuitBreaker` | `src/core/plugin_circuit_breaker.py` | Heavier version (state_manager, fallback_fn); NOT recommended for PIPE-01 |
| `validate_signal()` | `src/intelligence/trading/signal_schema.py` | Signal v1 field validation — use this for PIPE-02 |
| `_send_to_dlq()` | `src/core/agent/base.py` | Base DLQ routing; `SignalWriterAgent._dlq_topic()` already overridden |
| `DLQPayload` | `src/core/schemas/dlq_payload.py` | Standard DLQ envelope schema |
| `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` | `src/observability/metrics.py` | Already set by `_record_message_consumed()` |
| `CIRCUIT_BREAKER_STATE` | `src/observability/metrics.py` | Metric gauge, label `plugin_name` |
| `PLUGIN_ERRORS_TOTAL` | `src/observability/metrics.py` | Already incremented in `_collect_plugin_results` |
| `DLQ_MESSAGES_TOTAL` | `src/observability/metrics.py` | Counter for DLQ routing |

### Existing metrics to expose in OBS-02

| Metric | Source | Already emitted by |
|---|---|---|
| `persistence_consumer_lag` | `PERSISTENCE_CONSUMER_LAG` gauge | `BaseWriterAgent._report_consumer_lag()` |
| `dlq_messages_total` | `DLQ_MESSAGES_TOTAL` counter | `BaseAgent._send_to_dlq()` |
| `agent_dlq_total` | `AGENT_DLQ_TOTAL` counter | `BaseAgent._send_to_dlq()` |
| `signal_replay_unresolved_gauge` | `src/observability/metrics.py` line 497 | `signal_replay` service |
| `agent_last_message_timestamp_seconds` | `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` | `_record_message_consumed()` |

---

## Architecture Patterns

### Current plugin execution flow (I1, I2-I6, I7)

```
_run_i1() / _run_tier() / _run_i7_inner()
  -> loop.run_in_executor(executor, _timed_plugin_call, plugin, frames)
  -> asyncio.gather(*coroutines, return_exceptions=True)
  -> _collect_plugin_results(tasks, results)
     -> isinstance(out, Exception): logs PLUGIN_ERRORS_TOTAL, skips plugin
     -> isinstance(out, tuple): records PLUGIN_DURATION_MS, merges output
```

**Key insight:** `return_exceptions=True` already prevents one plugin exception from halting the bar. The gap is that there is no per-plugin circuit breaker — a plugin that raises on every bar will be attempted on every bar with no skip-ahead logic.

### PIPE-01: Per-plugin circuit breaker

**What exists:** `src/observability/circuit_breaker.py` has `CircuitBreaker` (clean dataclass, CLOSED/OPEN/HALF_OPEN, `failure_threshold=5`, `timeout_sec=60`). It does NOT require a state_manager or fallback_fn.

**What is needed:**
- A dict `_plugin_circuit_breakers: dict[str, CircuitBreaker]` on `IntelligencePipelineComputeAgent`
- In `_collect_plugin_results()`: on exception, call `cb.record_failure()`. When cb opens, emit `CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": name})` and log `plugin.circuit_breaker_opened`.
- In `_run_i1()`, `_run_tier()`, `_run_i7_inner()`: before building each `PluginTask`, check `_plugin_circuit_breakers[plugin_name].state == CircuitState.OPEN` and skip (do not build the coroutine). This is where the "subsequent bars skip it" behavior lives.
- On success in `_collect_plugin_results()`: call `cb.record_failure` is skipped; instead call `cb.call()` pattern or manually track via `cb._failures = max(0, cb._failures - 1)`.

**Simpler approach (recommended):** Add `_plugin_circuit_breakers: dict[str, CircuitBreaker]` at agent `__init__`. Wrap the per-plugin executor submission in a helper that checks `cb.state` before submitting. On exception from `gather`, call `cb.record_failure()`. On success, optionally decrement `cb._failures`. `CircuitBreaker.call()` wraps the actual call and handles state transitions — use this if you want the cleaner interface.

**Grafana visibility:** `plugin_circuit_breaker_state{plugin_name=...}` metric already exists and is set by both circuit breaker implementations.

### PIPE-02: validate_signal() at I7 output boundary in SignalWriterAgent

**What exists:**
- `validate_signal()` in `signal_schema.py` returns `bool`. Checks: `isinstance(signal, dict)`, `REQUIRED_SIGNAL_FIELDS.issubset(signal.keys())`, `type == "signal.v1"`, `confidence in [0,1]`, `direction in (+/-1)`, `targets non-empty list`.
- `SignalWriterAgent._dlq_topic()` already returns `topic_signal_writer_dlq(env_name)`.
- `_payload_to_ledger_entries()` converts signal dicts to `LedgerEntry` without any validation gate.

**What is missing:** Call `validate_signal(sig)` for each signal dict inside `_payload_to_ledger_entries()` (or in `_parse_payload()`). If invalid, call `await self._send_to_dlq(sig, ValidationError(...))` and skip the signal — do NOT include it in the returned `LedgerEntry` list.

**Where to add:** `_payload_to_ledger_entries()` is a module-level function. The simplest wiring is to filter inside the `for sig in signals:` loop, or inside `_parse_payload()` before converting. Since `_send_to_dlq` is async and `_payload_to_ledger_entries` is sync, the validation + DLQ call should move into `_parse_payload()` (which is called from the async `BaseWriterAgent._run_loop()`).

**Note:** The current `_publish_signals_or_dlq()` in the pipeline agent already asserts CIS scores and routes to `topic_signal_dlq`. That is a different DLQ (pipeline-side). PIPE-02 adds validation at the writer-side boundary (signal_writer_agent), which is the last line of defense before `signal_ledger`.

### PIPE-03: Checkpoint write failure must raise (not swallow)

**Current behavior:** `_write_local_checkpoint()` has `try/except Exception as exc: self.logger.warning(...)` — it is explicitly "Best-effort — never raises."

**Required behavior:** The success criteria says "A checkpoint write failure raises an exception that halts the bar; the error appears in structured logs; it is never silently swallowed."

**Where checkpoint is called:** `_teardown()` calls `self._write_local_checkpoint()`. There is NO per-bar checkpoint write — checkpoints happen at shutdown only.

**Interpretation:** The requirement language "halts the bar" is aspirational. The actual checkpoint call is in `_teardown()`, not `_process_bar_inner()`. The fix is: remove the swallow from `_write_local_checkpoint()` — let it raise. `_teardown()` will propagate the exception, which will log the error. Do NOT add a `try/except` around it in `_teardown()`.

**Alternatively:** If the intent is to detect mid-run checkpoint failures (e.g., disk full), a periodic checkpoint loop could be added to `_run()`. But that is not the current design — the existing checkpoint path is shutdown-only. Stick with the current design and just make the shutdown checkpoint raise.

### PIPE-04: Output queue block/retry instead of put_nowait

**Current behavior:** `_enqueue()` calls `self._output_queue.put_nowait((topic, key, value))`. On `asyncio.QueueFull`, it increments `_output_buffer_drops` and silently drops the bar's output.

**Required behavior:** When the queue is full, the producer blocks and retries rather than dropping. A full-queue event must be visible as a metric.

**Fix:**
```python
async def _enqueue_blocking(self, topic: str, key: str, value: Any) -> None:
    """Blocking enqueue with full-queue metric."""
    if self._output_queue.full():
        INTELLIGENCE_PIPELINE_OUTPUT_QUEUE_FULL.add(1)  # new counter or reuse _output_buffer_drops
        self.logger.warning("output_queue.full_blocking")
    await self._output_queue.put((topic, key, value))  # blocks until space available
```

This means `_enqueue` must become `async` (currently sync). All call sites in `_process_bar_inner()` and `_run_i7_inner()` must `await` it. `_enqueue_intel_journal()` is also sync — it calls `_enqueue()` too.

**Alternative (lower refactor cost):** Keep `_enqueue()` sync for non-blocking fast path but add `async _enqueue_blocking()` for the critical path. The two I7 signal publish calls (`_publish_signals_or_dlq` and winner enqueue) are the most important to protect.

**Metric:** Rename or reuse `_output_buffer_drops` for the "queue full" signal. The requirement says "a full-queue event is visible as a metric" — the existing `intelligence_pipeline_output_buffer_drops_total` already fires on `QueueFull`, so renaming/relabeling it may satisfy the requirement without a new metric.

### OBS-02: GET /api/health/system endpoint

**What exists:** `src/api/routes/health.py` has `/` (basic), `/database` (DB ping), `/full` (components check). None of them are `/api/health/system`.

**What is missing:** A new route `GET /api/health/system` that returns:
1. Consumer lag by group (query Prometheus or Redpanda `rpk group describe`)
2. DLQ depth (query Prometheus `dlq_messages_total` or `agent_dlq_total`)
3. `signal_replay_unresolved` gauge value (query Prometheus)
4. Agent last-heartbeat timestamps (query Prometheus `agent_last_message_timestamp_seconds`)

**How to query Prometheus from FastAPI:** The service auditor already does this pattern — `aiohttp.ClientSession.get(_PROMETHEUS_URL, params={"query": ...})`. Use the same pattern in the new health endpoint. `_PROMETHEUS_URL` is `http://localhost:9090/api/v1/query`.

**Router registration:** Add to `src/api/main.py` — `app.include_router(health.router, prefix="/api/health", tags=["health"])` already routes `/health`. The new endpoint path would be `/api/health/system` (add a new route function to `health.py` or a new router).

**Response shape (required by spec):**
```json
{
  "consumer_lag": {"signal_writer_group": 0, "feature_writer_group": 0, ...},
  "dlq_depth": 0,
  "signal_replay_unresolved": 0,
  "agent_heartbeats": {
    "intelligence_pipeline_agent": "2026-05-17T10:00:00Z",
    ...
  }
}
```

### OBS-03: BaseAgent.last_processed_at + service_auditor stall detection

**What exists:**
- `BaseAgent._record_message_consumed()` sets `self._last_message_ts = time.monotonic()` (monotonic, not wall clock) and emits `AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS` (wall clock via `time.time()`).
- `BaseAgent._stall_watchdog()` already does stall detection and calls `sys.exit(1)`. It is activated when `max_idle_seconds > 0`.
- `service_auditor_agent.py` currently detects stalls via systemd state (failed/inactive) and Prometheus lag thresholds. It does NOT use `agent_last_message_timestamp_seconds` directly.

**What is missing for OBS-03:**
1. `BaseAgent` needs a public property `last_processed_at: datetime | None` that returns wall-clock UTC datetime of last processed message. The monotonic `_last_message_ts` can be converted, or a second `_last_processed_at_wall: datetime | None` can be set alongside `_last_message_ts`.
2. `service_auditor_agent` needs to query `agent_last_message_timestamp_seconds` from Prometheus and compare against current time. If an agent's last message is older than some threshold (e.g., 5 min) AND the systemd process is alive (active state = active), that is a stall — restart.

**Key distinction from existing stall watchdog:** The existing `_stall_watchdog()` is in-process (self-exits). OBS-03 requires the service_auditor (external process) to detect a stall and trigger a restart. These are complementary — the in-process watchdog is faster but the external check is the authoritative source for the health endpoint.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---|---|---|
| Circuit breaker state machine | Custom CLOSED/OPEN logic | `src/observability/circuit_breaker.py` `CircuitBreaker` |
| Signal validation | Field-by-field checks | `validate_signal()` from `signal_schema.py` |
| DLQ routing | Custom topic publish | `BaseAgent._send_to_dlq()` |
| Prometheus query from FastAPI | Custom HTTP client | `aiohttp.ClientSession` (already used in service_auditor) |
| DLQ payload schema | Custom dict | `DLQPayload` from `src/core/schemas/dlq_payload.py` |

---

## Common Pitfalls

### Pitfall 1: Using PluginCircuitBreaker instead of CircuitBreaker for PIPE-01

**What goes wrong:** `src/core/plugin_circuit_breaker.py` `PluginCircuitBreaker` requires a `fallback_fn` parameter. I7 plugins have no valid fallback — they either fire or don't. Using it would require wrapping every plugin call in a lambda returning `no_signal()`, which adds complexity with no benefit.

**How to avoid:** Use `src/observability/circuit_breaker.py` `CircuitBreaker` (no fallback needed). Maintain a `dict[str, CircuitBreaker]` keyed by plugin name.

### Pitfall 2: Making _enqueue async breaks _enqueue_intel_journal (sync method)

**What goes wrong:** `_enqueue_intel_journal()` is a sync method that calls `_enqueue()`. If `_enqueue` becomes async, the call site chain breaks silently.

**How to avoid:** Either (a) make `_enqueue_intel_journal` also async (requires `await` at its call site in `_process_bar_inner`), or (b) use `asyncio.Queue.put_nowait` with a retry loop at the async level only for the critical I7 signal path, leaving the journal path as non-blocking.

### Pitfall 3: Checkpoint raise propagates through _teardown and hides original error

**What goes wrong:** If `_teardown()` raises from checkpoint, a previous unrelated error in `_run()` may be shadowed.

**How to avoid:** Log the checkpoint failure with level ERROR (not WARNING) before re-raising, so both errors appear in logs. The original `_run()` error is already in `agent.run_failed`.

### Pitfall 4: validate_signal fails on backfill signals that predate signal_schema_version field

**What goes wrong:** `validate_signal()` checks `type == "signal.v1"` and `REQUIRED_SIGNAL_FIELDS`. Older backfill signals in the Kafka topic may not have all required fields. The writer would DLQ all backfill signals.

**How to avoid:** `validate_signal()` only applies at the writer boundary for NEW signals. The pipeline already stamps `signal_schema_version` on every signal before publish. Check the `type` field first — if missing or wrong, DLQ; otherwise validate required fields.

### Pitfall 5: OBS-02 health endpoint blocks on slow Prometheus query

**What goes wrong:** Prometheus queries can take > 500ms under load, making the health endpoint timeout.

**How to avoid:** Add a `aiohttp.ClientTimeout(total=3)` timeout and return degraded values on timeout rather than a 503.

### Pitfall 6: service_auditor stall threshold vs _stall_watchdog threshold must not conflict

**What goes wrong:** If service_auditor triggers a restart at 5 minutes but the in-process `_stall_watchdog` also exits at 5 minutes (`max_idle_seconds=300`), both fire simultaneously causing a race on systemd restart counter.

**How to avoid:** Set service_auditor stall threshold to `max_idle_seconds + 60s` grace (e.g., 6 minutes) so the in-process exit fires first and is the primary restart mechanism.

---

## Code Examples

### PIPE-01: Circuit breaker wire-up pattern

```python
# In __init__:
from src.observability.circuit_breaker import CircuitBreaker, CircuitState
self._plugin_circuit_breakers: dict[str, CircuitBreaker] = {}

def _get_plugin_cb(self, plugin_name: str) -> CircuitBreaker:
    if plugin_name not in self._plugin_circuit_breakers:
        self._plugin_circuit_breakers[plugin_name] = CircuitBreaker(
            failure_threshold=3, timeout_sec=300
        )
    return self._plugin_circuit_breakers[plugin_name]

# In _run_i1 / _run_tier / _run_i7_inner — before building PluginTask:
cb = self._get_plugin_cb(plugin_name)
if cb.state == CircuitState.OPEN:
    continue  # skip this plugin for this bar

# In _collect_plugin_results — on exception:
cb = self._get_plugin_cb(task.plugin_name)
cb.record_failure()
if cb.state == CircuitState.OPEN:
    CIRCUIT_BREAKER_STATE.set(1, {"plugin_name": task.plugin_name})
    self.logger.warning("plugin.circuit_breaker_opened", plugin=task.plugin_name)
```

### PIPE-02: validate_signal at writer boundary

```python
# In SignalWriterAgent._parse_payload():
from src.intelligence.trading.signal_schema import validate_signal

def _parse_payload(self, payload: dict) -> list | None:
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals = payload.get("signals", [])
    valid_signals = []
    invalid_signals = []
    for sig in signals:
        if validate_signal(sig):
            valid_signals.append(sig)
        else:
            invalid_signals.append(sig)
    # DLQ invalid signals
    for sig in invalid_signals:
        # Note: _send_to_dlq is async; must be called from async context
        # Use a pending list pattern or make _parse_payload async
        self._pending_dlq.append((sig, ValueError("validate_signal failed")))
    rows = _payload_to_ledger_entries({**payload, "signals": valid_signals})
    return rows if rows else None
```

**Note:** `_parse_payload` is sync in `BaseWriterAgent`. The DLQ call is async. Either make `_parse_payload` async (and update `BaseWriterAgent._run_loop`), or accumulate invalid signals and flush DLQ in `_flush_batch`. The cleanest approach: make `_parse_payload` accept `async` and update the base class.

### PIPE-03: Checkpoint raise on failure

```python
def _write_local_checkpoint(self) -> None:
    """Write hot indicator state to local file. Raises on failure."""
    payload: dict = {"version": _AGENT_VERSION, "ts": datetime.now(UTC).isoformat()}
    for field in _CHECKPOINT_FIELDS:
        payload[field] = _tag_value(getattr(self, f"_{field}"))
    tmp = _CHECKPOINT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.rename(_CHECKPOINT_PATH)
    self.logger.info("state.checkpoint_written", path=str(_CHECKPOINT_PATH))
    # No try/except — let OSError propagate; _teardown caller logs it
```

### PIPE-04: Blocking enqueue

```python
async def _enqueue_blocking(self, topic: str, key: str, value: Any) -> None:
    """Blocking enqueue — waits for space, emits metric on full."""
    if self._output_queue.full():
        self._output_buffer_drops.add(1)  # repurpose existing metric for visibility
        self.logger.warning("output_queue.full_blocking", qsize=self._output_queue.qsize())
    await self._output_queue.put((topic, key, value))

# Replace put_nowait calls in _publish_signals_or_dlq and winner enqueue
# with: await self._enqueue_blocking(topic, key, value)
```

### OBS-02: /api/health/system route

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
        # Consumer lag by group
        try:
            async with session.get(prom_url, params={"query": "persistence_consumer_lag"}) as r:
                data = await r.json()
                for item in data.get("data", {}).get("result", []):
                    agent_id = item["metric"].get("agent_id", "unknown")
                    result["consumer_lag"][agent_id] = int(float(item["value"][1]))
        except Exception:
            pass

        # DLQ depth
        try:
            async with session.get(prom_url, params={"query": "dlq_messages_total"}) as r:
                data = await r.json()
                total = sum(
                    float(i["value"][1])
                    for i in data.get("data", {}).get("result", [])
                )
                result["dlq_depth"] = int(total)
        except Exception:
            pass

        # signal_replay_unresolved
        try:
            async with session.get(
                prom_url, params={"query": "signal_replay_unresolved_gauge"}
            ) as r:
                data = await r.json()
                items = data.get("data", {}).get("result", [])
                if items:
                    result["signal_replay_unresolved"] = int(float(items[0]["value"][1]))
        except Exception:
            pass

        # Agent heartbeats
        try:
            async with session.get(
                prom_url, params={"query": "agent_last_message_timestamp_seconds"}
            ) as r:
                data = await r.json()
                for item in data.get("data", {}).get("result", []):
                    agent = item["metric"].get("agent", "unknown")
                    ts = float(item["value"][1])
                    result["agent_heartbeats"][agent] = datetime.fromtimestamp(
                        ts, tz=UTC
                    ).isoformat()
        except Exception:
            pass

    return result
```

### OBS-03: last_processed_at on BaseAgent

```python
# In BaseAgent.__init__:
self._last_processed_at: datetime | None = None

@property
def last_processed_at(self) -> datetime | None:
    """Wall-clock UTC datetime of last successfully processed message."""
    return self._last_processed_at

def _record_message_consumed(self) -> None:
    """Call once per successfully consumed message."""
    self._last_message_ts = time.monotonic()
    self._last_processed_at = datetime.now(UTC)  # ADD THIS
    AGENT_LAST_MESSAGE_TIMESTAMP_SECONDS.set(time.time(), self._last_msg_ts_attrs)
```

```python
# In service_auditor _prometheus_check_loop — add stall detection using the metric:
# Query agent_last_message_timestamp_seconds, compare to now.
# If delta > STALL_THRESHOLD_SECONDS AND systemd reports active/running -> restart.
STALL_THRESHOLD_SECONDS = 360  # 6 minutes (max_idle_seconds=300 + 60s grace)
```

---

## State of the Art

| Old Approach | Current Approach | Impact for Phase 086 |
|---|---|---|
| `prometheus_client` | OTel SDK (Phase 83) | Use `.add()` for counters/up_down_counters, `.record()` for histograms, `.set()` for gauges — NOT prometheus_client |
| BaseAgent.circuit_breaker (agent setup level) | PluginCircuitBreaker per-plugin | PIPE-01 needs per-plugin CB on the plugin execution path, not the agent setup path |
| put_nowait drops silently | Requirement: block/retry | PIPE-04 wires `asyncio.Queue.put()` (blocking) |
| Checkpoint best-effort | Requirement: raise on failure | PIPE-03 removes the exception swallow |

---

## Open Questions

1. **PIPE-04 scope: all enqueue paths or only signal path?**
   - What we know: `_enqueue()` is called for IntelligenceEvent, signals, and journal. Blocking all paths could back-pressure the I7 hot path.
   - What's unclear: Does the requirement apply to the intelligence event and journal paths too, or only the signal output path?
   - Recommendation: Apply blocking only to `_publish_signals_or_dlq()` and the winner enqueue (signal paths). Keep the intelligence event and journal enqueue as non-blocking with metric.

2. **PIPE-02 async/sync boundary in BaseWriterAgent**
   - What we know: `_parse_payload` is sync; `_send_to_dlq` is async. DLQ routing for invalid signals requires async.
   - What's unclear: Whether to make `_parse_payload` async (touching base class) or accumulate invalid signals in a separate list and DLQ them in `_flush_batch`.
   - Recommendation: Add an `_invalid_signals: list` buffer; drain it in `_flush_batch` via `await self._send_to_dlq(...)`. This minimizes base class churn.

3. **OBS-03: Prometheus query URL**
   - What we know: Service auditor uses `http://localhost:9090/api/v1/query`. Prometheus is scraped via OTel Collector at `:8889`.
   - What's unclear: Whether `agent_last_message_timestamp_seconds` is actually scraped and queryable at `:9090` or only at `:8889`.
   - Recommendation: Verify with `curl 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds'` before implementing. If not at 9090, use `:8889/metrics` scrape endpoint instead and parse directly.

---

## Sources

### Primary (HIGH confidence)
- `services/intelligence_pipeline_agent.py` — full pipeline agent, plugin execution, checkpoint, output queue
- `src/core/agent/base.py` — BaseAgent, `_record_message_consumed`, `_stall_watchdog`, `_send_to_dlq`
- `src/observability/circuit_breaker.py` — `CircuitBreaker` implementation
- `src/core/plugin_circuit_breaker.py` — `PluginCircuitBreaker` implementation (NOT recommended for PIPE-01)
- `src/intelligence/trading/signal_schema.py` — `validate_signal()`, `REQUIRED_SIGNAL_FIELDS`
- `services/signal_writer_agent.py` — `_payload_to_ledger_entries`, `_dlq_topic`, `_parse_payload`
- `src/api/routes/health.py` — existing health routes
- `src/api/main.py` — FastAPI app, router registrations
- `src/observability/metrics.py` — all metric instruments
- `services/service_auditor_agent.py` — `_prometheus_check_loop`, `_fetch_prometheus_lag`, stall detection patterns

### Secondary (MEDIUM confidence)
- `.planning/REQUIREMENTS.md` — PIPE-01..04, OBS-02, OBS-03 requirement text
- `src/core/schemas/dlq_payload.py` — DLQPayload schema

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified directly in code
- Architecture: HIGH — read full pipeline agent and base agent
- Pitfalls: HIGH — derived from code reading, not documentation
- Open questions: MEDIUM — implementation choices not verified by running code

**Research date:** 2026-05-17
**Valid until:** 2026-06-17 (30 days; codebase is actively changing)
