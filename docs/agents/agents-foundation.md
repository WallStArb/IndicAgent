# Agents Foundation — BaseAgent Contract & Fundamental Patterns

**Version:** 2.8.0 | **Status:** current | **Last Updated:** 2026-05-29

---

## Purpose

Every daemon in IndicAgent is a `BaseAgent` subclass. This document explains what `BaseAgent` provides automatically, why it was built that way, and what a new service author must (and must not) do.

**Audience:** Engineers writing a new service from scratch, or debugging why an existing service is misbehaving.

`BaseAgent` exists because every agent shares the same operational concerns: SIGTERM handling, OTel instrumentation, systemd watchdog integration, structured logging, and consumer-lag reporting. Without a shared base, each service would reinvent these — inconsistently. With `BaseAgent`, all five mandatory OTel signals are inherited with no per-service code required.

---

## Design Principles

### OODA Loop Rationale

Every `BaseAgent` operates on the OODA loop (Observe-Orient-Decide-Act):

- **Observe:** Consume Kafka events and OTel metrics to understand the operational environment.
- **Orient:** Evaluate internal health — is lag too high? Is the buffer near overflow?
- **Decide:** Execute domain logic (compute, filter, rank, write).
- **Act:** Publish results to a downstream topic, flush a persistence batch, or route to DLQ.

The loop is asynchronous and event-driven. Agents do not poll on timers (with the exception of consumer-lag reporting). A message arrives, work happens, the agent waits for the next message.

### Why Async Message Processing, Not Polling

Polling threads burn CPU and add latency variance. An asyncio consumer loop yields to the event loop while waiting, consumes zero CPU, and wakes immediately when a message arrives. The sequential processing constraint (`await _process_bar`) is intentional — concurrent bar processing introduces ordering races in state-heavy plugins.

### Why Graceful Shutdown Matters

Without drain semantics, a systemd restart mid-batch leaves uncommitted Kafka offsets and partially-written DB rows. The drain mandate guarantees:

1. SIGTERM sets `_stop_event` without interrupting the current processing iteration.
2. The current batch completes and commits.
3. `_teardown()` runs (closes consumers, flushes buffers, closes pools).
4. The process exits cleanly.

This is why `BaseAgent` registers signal handlers via `asyncio.get_running_loop().add_signal_handler()` — not `signal.signal()`, which is not safe inside an asyncio event loop.

### Why Health Liveness Ties to Message Receipt

Process-alive checks (`systemctl status`) catch crashes but miss stalls: a process that is running but not processing messages. `agent_last_message_timestamp_seconds` is updated on every message via `_record_message_consumed()`. Grafana alerts when this gauge goes stale beyond 120 seconds. This catches hung consumers, topic connectivity failures, and upstream stalls that a process-alive check would miss.

### What Was Rejected

- **Thread-per-service model:** thread safety overhead, no natural drain point.
- **Synchronous pipelines:** any slow downstream blocks all upstream. Async + Kafka decouples every tier.
- **Polling loops with sleep:** wastes CPU, introduces response latency proportional to poll interval.

---

## Architecture

### `_run()` Lifecycle

```
start()
  ├─→ _register_signal_handlers()         SIGTERM/SIGINT → _stop_event.set()
  ├─→ init_otel_providers(name)            idempotent; first call wins
  ├─→ setup_otlp_logging(name)             additive to file logging
  ├─→ _setup()                             [override] connect Kafka, seed state
  ├─→ background: _report_consumer_lag()   noop in BaseAgent; overridden by writers
  ├─→ background: _watchdog_notify()       sd_notify WATCHDOG=1 at half-interval
  ├─→ background: _stall_watchdog()        sys.exit(1) if idle > max_idle_seconds
  └─→ _run()                               [ABSTRACT] main message loop
        │  exception → log agent.run_failed + AGENT_CRASH_TOTAL
        └─→ finally:
              ├─→ cancel background tasks
              ├─→ _teardown()              [override] drain/close connections
              └─→ stop()                   [override] final flush logic
```

### The Two Required Override Points

Only `_run()` is abstract — the only method you must implement. `_setup()` and `_teardown()` are optional no-ops, but nearly all real agents override them.

| Method | Required | Purpose |
|--------|----------|---------|
| `_run()` | **Yes** | Main message loop. Runs until `self.running` is `False`. |
| `_setup()` | No | Connect Kafka, initialize DB pools, seed warmup state. Called once before `_run()`. |
| `_teardown()` | No | Drain in-flight work, close connections. Called after `_run()` exits (even on exception). |

### Graceful Shutdown Sequence

1. SIGTERM arrives. `_stop_event.set()` fires.
2. `_run()` checks `self.running` (which reads `not _stop_event.is_set()`). Loop exits after completing the current iteration.
3. Background tasks (`_watchdog_notify`, `_stall_watchdog`, `_report_consumer_lag`) are cancelled.
4. `_teardown()` runs: flush buffers, close Kafka consumer, close DB pool.
5. `stop()` runs: logs `agent.stopped`.
6. Process exits.

The key invariant: **no in-flight work is dropped**. Current batch completes before the loop exits. `_teardown()` flushes anything remaining.

### Setup Retry with Circuit Breaker

Set `circuit_breaker = True` on a subclass to enable exponential backoff retry on `_setup()` failures. Defaults: `SETUP_RETRY_ATTEMPTS = 3`, `SETUP_RETRY_BACKOFF_S = 2.0`. On exhaustion, the circuit breaker opens and the agent exits — systemd restarts it.

---

## Data Contracts

### 5 Mandatory OTel Signals (Phase 108 SOP, D-04)

All BaseAgent subclasses automatically emit these five signals — **no per-service code is needed**.

| Metric | Type | Label | Purpose |
|--------|------|-------|---------|
| `agent_last_message_timestamp_seconds` | Gauge | `agent_id` | Liveness. Unix timestamp of last processed message. Stale > 120s triggers a page. |
| `agent_crash_total` | Counter | `agent` | Uncaught exceptions in `_run()`. Any increment is a page. |
| `agent_dlq_total` | Counter | `agent_id` | DLQ routing events from `_send_to_dlq()`. Increment is a warning. |
| `watchdog_notify_total` | Counter | `agent_id` | Successful `sd_notify WATCHDOG=1` pings. |
| `watchdog_notify_suppressed_total` | Counter | `agent_id` | Suppressed pings: agent alive but idle or stalled. Rate > 0 is a warning. |

The label key for `agent_last_message_timestamp_seconds` is `agent_id`, not `agent`. When querying this metric from Prometheus, use `r["metric"].get("agent_id")`.

### `_record_message_consumed()`

Call this once per successfully consumed Kafka message inside your `_run()` loop. It updates `agent_last_message_timestamp_seconds` and starts the stall clock. Agents that never call it receive no stall detection.

```python
async def _run(self) -> None:
    async for _topic, _key, payload in self._consumer.messages():
        if self._stop_event.is_set():
            break
        self._record_message_consumed()   # <-- required for liveness
        await self._process(payload)
```

### Structured Logging

The logger is pre-bound with `agent=name`. Standard event names (use these consistently):

- `agent.starting` — initialization begins
- `agent.stopped` — clean shutdown
- `agent.run_failed` — unhandled exception in `_run()`
- `agent.dlq_discard` — DLQ discard (when no DLQ topic is configured)

Never use `event=` as a keyword argument to structlog — it collides with the positional event argument. Use `signal=`, `payload=`, `data=` instead.

Log files: `logs/<agent_snake_case>_agent.log`. For example, `BarAggregator` logs to `logs/bar_aggregator.log`. BaseAgent derives this path automatically from the `name` argument — pass `name="bar_aggregator"` to get the right file.

---

## How To Extend

### Minimal Agent Recipe

```python
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient

BaseAgent:(BaseAgent):

    async def _setup(self) -> None:
        self._consumer = KafkaConsumerClient(
            self._topic_name,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="my_compute_group",
            auto_offset_reset="earliest",
            enable_auto_commit=True,
        )

    async def _run(self) -> None:
        async for _topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            self._record_message_consumed()
            try:
                await self._process(payload)
            except Exception as exc:
                await self._send_to_dlq(payload, exc)

    async def _teardown(self) -> None:
        if self._consumer:
            await self._consumer.stop()
```

### What NOT To Do

| Don't | Do Instead |
|-------|-----------|
| `datetime.now()` or `datetime.utcnow()` | `datetime.now(UTC)` — always timezone-aware |
| `import prometheus_client` | Use `src/observability/metrics.py` — prometheus_client was removed in Phase 83 |
| Call `self._llm.generate()` directly | Use `self._llm_generate(context, ...)` — auto-injects audit context |
| Hardcode topic strings | Use `src/core/stream_keys.py` — all topics constructed there |
| `os.environ["KEY"]` | Use `self.settings` — the `Settings` singleton |
| `json.dumps(my_dict)` before passing to asyncpg | Pass the dict directly — asyncpg handles JSONB natively |
| `KafkaProducerClient.publish(value=x)` | Use `msg=x` — wrong kwarg silently fails at flush |
| `tracer.start_as_current_span(name)` directly | Use `observed_span(name, attributes={...})` from `src/observability/spans.py` — auto-records ERROR status and exception on raise |

### Agent Naming Convention

The class name, file name, systemd unit, and log file all derive from the same concept name:

- `alpha_signal` → `AlphaSwarm` / `services/alpha_signal_agent.py` / `indicagent-alpha-signal` / `logs/alpha_signal_agent.log`

Role suffixes map to invariant responsibilities:

| Suffix | Role |
|--------|------|
| `Provider` | External protocol → typed Kafka events. No compute, no DB. |
| `Merger` | Fan-in multiple raw streams → one authoritative stream. |
| Hot-path service | DB-ignorant, Kafka→Kafka. Deterministic transformation. |
| Writer | Kafka → batch DB write. Only role with DB write access. |
| `Tracker` | Business object lifecycle state tracking. |
| `Auditor` | Data integrity validation, not data mutation. |

---

## Failure Modes & Operations

### `agent_last_message_timestamp_seconds` is Stale

The agent is either crashed or stalled. Check in order:

1. `systemctl status indicagent-<name>` — is the process running?
2. `tail -50 logs/<agent_name>_agent.log` — any exceptions?
3. `docker exec redpanda rpk group describe <consumer_group> -t` — is the Kafka topic producing messages?

### Service Crashed (FAILED state)

```bash
sudo systemctl reset-failed indicagent-<name>
sudo systemctl start indicagent-<name>
```

The service auditor handles this automatically for most services. Manual intervention is only needed when the auditor itself has stopped or when the service has exceeded the escalation threshold (3 restarts in 10 minutes).

### Reading Logs

```bash
tail -100 logs/<agent_snake_case>_agent.log
```

Log output is JSON (structlog). Key fields: `event` (log message), `agent` (agent name), `timestamp`. For grep:

```bash
grep '"level":"error"' logs/intelligence_pipeline_agent.log | tail -20
```

---

## DAG Mandate

Every agent operates inside a strict DAG (Directed Acyclic Graph). Before writing a new agent, understand the invariants it must respect:

| Role | DB reads | DB writes | Kafka reads | Kafka writes |
|------|----------|-----------|-------------|--------------|
| `Provider` | No | No | No | Yes (raw topic only) |
| `Merger` | No | No | Yes | Yes (canonical topic only) |
| Analyzer/Aggregator | **No** | **No** | Yes | Yes |
| Writer | No | **Yes** | Yes | No |
| `Tracker` | Yes | Yes | Yes | Yes |
| `Auditor` | Yes | No | Yes | Yes (gap requests only) |

**Critical DAG principle:** DB access is a DAG violation. If your service needs historical data, that data must arrive via Kafka from a service that read it — not via a direct DB query in the hot path.

The full DAG mandate and all seven architectural invariants are in `docs/foundation/design-principles.md` (Principle 11) and `docs/architecture/architecture-dag-topology.md`.

---

## See Also

- `docs/agents/agents-writers.md` — BaseWriter and the persistence pattern
- `docs/agents/agents-operations.md` — service mesh management and DAG topology
- `docs/architecture/architecture-dag-topology.md` — full system map: every service, topic, and invariant
- `docs/foundation/design-principles.md` — DAG invariants (Principle 11) and all architectural north stars
- `src/core/agent/base.py` — source of truth for lifecycle implementation
- `src/observability/metrics.py` — canonical OTel metric definitions
- `src/observability/spans.py` — `observed_span()` helper and ATTR_* constants for tracing
- `CLAUDE.md` — Key Rules section (gotchas and critical patterns)
