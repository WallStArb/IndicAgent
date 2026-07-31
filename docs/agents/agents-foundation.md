# Agents Foundation — BaseDaemon Contract & Fundamental Patterns

**Version:** 2.9.0 | **Status:** current | **Last Updated:** 2026-07-31

---

## Purpose

Every daemon in IndicAgent is a `BaseDaemon` subclass (`src/core/agent/base.py`). This document explains what `BaseDaemon` provides automatically, why it was built that way, and what a new service author must (and must not) do. `BaseWriter` (`src/core/agent/base_writer.py`) and `BaseBatch` (`src/core/agent/base_batch.py`) are the two specialized subclasses — see `docs/agents/agents-writers.md` for `BaseWriter`.

**Naming note:** an earlier version of this base class was named `BaseAgent`; it was renamed to `BaseDaemon` during the v3.0 rebuild (the class no longer carries an `Agent` suffix, matching the repo-wide retirement of the `_agent` suffix from Ring 2 file/class names — see `CLAUDE.md`'s oneshot `_agent.py` exceptions list for the few deliberate holdouts). This doc previously described the `BaseAgent` contract and had drifted from the current code; it has been corrected against `src/core/agent/base.py` as of 2026-07-31.

**Audience:** Engineers writing a new service from scratch, or debugging why an existing service is misbehaving.

`BaseDaemon` exists because every agent shares the same operational concerns: SIGTERM handling, OTel instrumentation, systemd watchdog integration, structured logging, and consumer-lag reporting. Without a shared base, each service would reinvent these — inconsistently. With `BaseDaemon`, all five mandatory OTel signals are inherited with no per-service code required.

---

## Design Principles

### OODA Loop Rationale

Every `BaseDaemon` operates on the OODA loop (Observe-Orient-Decide-Act):

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

This is why `BaseDaemon` registers signal handlers via `asyncio.get_running_loop().add_signal_handler()` — not `signal.signal()`, which is not safe inside an asyncio event loop.

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
  ├─→ init_otel_providers(name)            idempotent; first call wins. HARD FAILURE if
  │                                        the OTel collector is unreachable (raises,
  │                                        crashes the process so systemd restarts visibly
  │                                        — metrics export is not optional).
  ├─→ setup_otlp_logging(name)             additive to file logging
  ├─→ _pre_setup_config_load()             [Phase 109] load OPS config snapshot from
  │                                        config_state BEFORE _setup(), non-fatal
  ├─→ _setup()                             [override] connect Kafka, seed state
  │                                        (can now read the config snapshot above);
  │                                        wrapped in _setup_with_retry() when
  │                                        circuit_breaker = True on the subclass
  ├─→ _setup_config_consumer()             [Phase 109] subscribe to Kafka for config
  │                                        hot-reload AFTER _setup(), non-fatal
  ├─→ background: _report_consumer_lag()   noop in BaseDaemon; overridden by BaseWriter
  ├─→ background: _watchdog_notify()       sd_notify WATCHDOG=1; liveness-gated once
  │                                        max_idle_seconds > 0 (suppresses pings once
  │                                        idle, letting _stall_watchdog fire first)
  ├─→ background: _stall_watchdog()        sys.exit(1) if idle > max_idle_seconds
  └─→ _run()                               [ABSTRACT] main message loop
        │  exception → log daemon.run_failed + AGENT_CRASH_TOTAL
        └─→ finally:
              ├─→ cancel background tasks (lag/watchdog/stall)
              ├─→ _teardown()              [override] drain/close connections
              ├─→ _teardown_config_consumer() [Phase 109] unsubscribe config consumer
              └─→ stop()                   [override] final flush logic; logs daemon.stopped
```

Log events use the `daemon.*` role prefix for base-class infra events (`daemon.starting`,
`daemon.stopped`, `daemon.run_failed`, `daemon.setup_failed`, `daemon.dlq_discard`,
`daemon.stall_detected`) rather than a per-service `agent_id` — an intentional exception to the
`{derived_agent_id}.action` convention used elsewhere (see `src/core/agent/base.py` docstrings).

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

All BaseDaemon subclasses automatically emit these five signals — **no per-service code is needed**.

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

The logger is pre-bound with `agent=name`. Base-class infra events use the `daemon.` prefix (not
a per-service name — see the lifecycle diagram above):

- `daemon.starting` — initialization begins
- `daemon.stopped` — clean shutdown
- `daemon.run_failed` — unhandled exception in `_run()`
- `daemon.setup_failed` — unhandled exception in `_setup()`
- `daemon.dlq_discard` — DLQ discard (when no DLQ topic is configured)
- `daemon.stall_detected` — `_stall_watchdog()` fired, process about to `sys.exit(1)`

Never use `event=` as a keyword argument to structlog — it collides with the positional event argument. Use `signal=`, `payload=`, `data=` instead.

Log files: `logs/<name>.log`, where `<name>` defaults to the snake_case conversion of the class
name (`BarAggregator` → `logs/bar_aggregator.log`) but can be overridden by passing `name=` before
`super().__init__()`. There is no `_agent` suffix — that convention was retired along with the
`BaseAgent` name itself (a handful of oneshot `_agent.py` *file* names are deliberately preserved
per CLAUDE.md, but the log path derivation never added a suffix).

---

## How To Extend

### Minimal Agent Recipe

```python
from src.core.agent.base import BaseDaemon
from src.core.kafka_utils import KafkaConsumerClient

class MyDaemon(BaseDaemon):

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
            except Exception as error:
                await self._send_to_dlq(payload, error)

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

- `alpha_swarm` → `AlphaSwarm` / `services/alpha_swarm.py` / `indicagent-alpha-swarm` / `logs/alpha_swarm.log`

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
2. `tail -50 logs/<name>.log` — any exceptions? (no `_agent` suffix — see Log File Naming above)
3. `docker exec redpanda rpk group describe <consumer_group> -t` — is the Kafka topic producing messages?

### Service Crashed (FAILED state)

```bash
sudo systemctl reset-failed indicagent-<name>
sudo systemctl start indicagent-<name>
```

The service auditor handles this automatically for most services. Manual intervention is only needed when the auditor itself has stopped or when the service has exceeded the escalation threshold (3 restarts in 10 minutes).

### Reading Logs

```bash
tail -100 logs/<name>.log
```

Log output is JSON (structlog). Key fields: `event` (log message), `agent` (agent name), `timestamp`. For grep:

```bash
grep '"level":"error"' logs/feature_vector_pipeline.log | tail -20
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
- `src/core/agent/base.py` — source of truth for lifecycle implementation (`BaseDaemon`)
- `src/core/agent/base_writer.py` — `BaseWriter` subclass, source of truth for the persistence pattern
- `src/core/agent/base_batch.py` — `BaseBatch` subclass, source of truth for oneshot batch compute jobs
- `src/observability/metrics.py` — canonical OTel metric definitions
- `src/observability/spans.py` — `observed_span()` helper and ATTR_* constants for tracing
- `CLAUDE.md` — Key Rules section (gotchas and critical patterns)
