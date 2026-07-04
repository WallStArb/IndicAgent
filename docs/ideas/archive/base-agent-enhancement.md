# BaseAgent Enhancement — Standardized Observability & Lifecycle

**Status:** draft
**Priority:** high
**Milestone:** v2.1
**Last Updated:** 2026-03-27
**Tags:** base-agent, otel, tracing, prometheus, metrics, lifecycle, kafka, observability, process-manifest

---

## Context

`BaseAgent` was shipped in Phase 52.2 with a minimal contract: SIGTERM drain via `_stop_event`, a
structured logger, a `_report_consumer_lag()` hook, and `start()/stop()`. It's the right foundation
but it doesn't yet own the things that every agent reimplements by hand — metrics server startup,
OTel tracer acquisition, setup/teardown lifecycle slots, and DLQ routing. The `AgentRegistry`
shipped alongside it, but as a stripped-down singleton that never implemented the original intent
(tracking topics and thresholds) and needs to be replaced with a proper design.

Current gaps across the agent fleet:

- Only `IndicatorComputeAgent` inherits `BaseAgent`. `SignalGeneratorAgent`, `IntelligenceComputeAgent`,
  and `FeatureWriterService` all use sync `signal.signal()` handlers and don't inherit anything.
- `IndicatorComputeAgent` must override `start()` entirely because there's no pre-`_run()` slot for
  Kafka setup and history seeding.
- `start_metrics_server(port=...)` is called manually in each agent's entrypoint.
- `src/observability/otel.py` provides `init_tracing()` and `get_tracer()` but nothing calls them —
  the OTel SDK has been in `requirements.txt` since before Phase 52 and is completely idle.
- Error crashes in `_run()` propagate without structured logging before `stop()` is called.
- The pipeline has no way to describe its own topology at runtime.

---

## Renaissance Framing

A senior quant at Renaissance doesn't add infrastructure because it's interesting — every component
earns its place with a measurable job. The question for each item here is: *does this produce
observable signal or protect existing signal?*

- **OTel tracing**: trace data is latency data. End-to-end trace propagation answers questions
  Prometheus cannot — was the lag in compute, or sitting in the Kafka queue? Under which regime
  does `IndicatorComputeAgent` slow down? That's a training signal for future auto-scaling. It also
  protects signal quality: late features degrade I7 inputs silently. Tracing makes it visible.
- **Lifecycle standardization**: naming IS correctness. An agent that rolls its own signal handler
  is a broken invariant. Every deviation from the standard is cognitive overhead that compounds.
- **Separation of concerns**: every component has one job. Process-level initialization belongs in
  the entrypoint. Agent-level tracer acquisition belongs in `BaseAgent`. These are different scopes.
- **Self-describing systems**: a pipeline that can describe its own topology is measurably more
  maintainable than one where topology lives only in docs. The `ProcessManifest` makes the DAG
  derivable from running code, not from a wiki page.

---

## Goals

1. `BaseAgent` owns all lifecycle boilerplate so concrete agents only implement `_setup()`, `_run()`,
   and `_teardown()`.
2. Every agent gets an OTel tracer for free — no per-agent wiring required.
3. Prometheus metrics server startup is automatic when a port is specified.
4. `ProcessManifest` replaces `AgentRegistry` with a design that captures the original intent:
   self-describing topology, coordinated lifecycle, and startup validation.
5. Migrating `SignalGeneratorAgent`, `IntelligenceComputeAgent`, and `FeatureWriterAgent` to
   `BaseAgent` becomes straightforward.

---

## Part 1: BaseAgent Changes

### 1. OTel Tracer in `BaseAgent.__init__`

**What it gives us:** end-to-end trace propagation through the Kafka DAG. A bar entering
`IndicatorComputeAgent` gets a `trace_id`. That ID travels in Kafka message headers through to
`SignalGeneratorAgent` and `FeatureWriterAgent`. The resulting trace in Grafana Tempo shows exact
latency at every hop — including queue time sitting in Kafka between agents. Prometheus can't show
this; it only shows per-service aggregates.

**Separation of concerns — the key design decision:**

`init_tracing()` is a **process-level singleton** — it installs a global `TracerProvider`. It
belongs in the `if __name__ == "__main__"` entrypoint of each service, called once before
`agent.start()`. Calling it from `BaseAgent.start()` would put a process-level concern inside an
agent-level lifecycle method. Wrong scope, even if the idempotency guard makes it safe at runtime.

What `BaseAgent` owns is the **agent-level** operation: acquiring a named tracer from the
already-initialized provider.

```python
# Each service entrypoint (if __name__ == "__main__"):
from src.observability.otel import init_tracing
init_tracing(service_name="indicator_compute_agent")  # process singleton — one call
agent = IndicatorComputeAgent(config_file=...)
asyncio.run(agent.start())

# BaseAgent.__init__:
from src.observability.otel import get_tracer

class BaseAgent(abc.ABC):
    def __init__(self, name: str, metrics_port: int | None = None) -> None:
        self.name = name
        self._metrics_port = metrics_port
        self._stop_event = asyncio.Event()
        self.logger = structlog.get_logger().bind(agent=name)
        self.tracer = get_tracer(name)  # no-op tracer until init_tracing() is called
```

`get_tracer()` is safe to call before `init_tracing()` — the OTel SDK returns a no-op tracer via
the default `ProxyTracerProvider`. When `init_tracing()` is called in the entrypoint, the proxy
upgrades automatically. Test code that instantiates an agent without calling `init_tracing()` works
correctly — all spans are zero-cost no-ops.

**Kafka trace propagation (follow-on, not part of this change):** Injecting/extracting `traceparent`
headers from Kafka messages requires changes to `KafkaConsumerClient`/`KafkaProducerClient` using
`opentelemetry.propagators.propagate.inject/extract`. This is a `kafka_utils.py` concern — the
agent uses `self.tracer` to create spans; the transport layer handles context propagation across
process boundaries.

**Infrastructure dependency (Grafana Tempo):** Spans are silently dropped until a collector
endpoint is running. No code change needed when the collector is added — set
`OTEL_EXPORTER_OTLP_ENDPOINT` in the systemd unit file and spans start flowing. Tempo is preferred
over Jaeger because:

- Traces live in the same Grafana instance as Prometheus metrics — click a lag spike on a
  Prometheus panel and jump directly to the trace that caused it. Jaeger requires switching tools.
- Grafana Exemplars wire Prometheus histograms to specific trace IDs natively.
- Traces stored in local object storage (filesystem at this scale) — cheap long-term retention
  means historical trace data is available as a future training signal.
- Single Docker container, one Grafana datasource config. Operationally equivalent to Jaeger with
  better Grafana integration.

---

### 2. Metrics Server Auto-Start

Every agent calls `start_metrics_server(port=...)` manually. `BaseAgent` should own this.

**Config-before-super pattern** — agents currently read `metrics_port` from a YAML config dict.
The correct order is: parse config (pure function, no side effects), then pass the result to
`super().__init__()`.

```python
class IndicatorComputeAgent(BaseAgent):
    def __init__(self, config_file=None):
        cfg = self._load_config(config_file)      # pure — reads file, returns dict
        super().__init__(
            name="indicator_compute_agent",
            metrics_port=cfg.get("metrics_port", 9109),
        )
        # ... rest of init
```

`BaseAgent.start()` calls `start_metrics_server(port=self._metrics_port)` if set. Agents that
don't want auto-start pass `None` (the default) and call it themselves in `_setup()`.

---

### 3. Topic Declarations on `BaseAgent`

Every agent declares what it consumes and produces. These are the foundation of `ProcessManifest`
topology — the DAG is derivable from running code, not from docs.

```python
@property
def topics_consumed(self) -> list[str]:
    """Kafka topics this agent reads from. Override in concrete agents."""
    return []

@property
def topics_produced(self) -> list[str]:
    """Kafka topics this agent writes to. Override in concrete agents."""
    return []

@property
def lag_threshold_messages(self) -> int:
    """Consumer lag threshold before alerting. Override per agent."""
    return 1000
```

Example in a concrete agent:

```python
class IndicatorComputeAgent(BaseAgent):
    @property
    def topics_consumed(self) -> list[str]:
        return [topic_market_bars(self._env), topic_market_bars_htf(self._env)]

    @property
    def topics_produced(self) -> list[str]:
        return [topic_indicators(self._env)]

    @property
    def lag_threshold_messages(self) -> int:
        return 500  # tighter threshold for I1 — feeds the entire downstream pipeline
```

---

### 4. `_setup()` / `_teardown()` Lifecycle Hooks

The lifecycle is always: connect Kafka → seed history → run → drain → disconnect. Without pre/post
hooks, agents must override `start()` entirely — which is what `IndicatorComputeAgent` does today.

**Revised lifecycle in `start()`:**

```
start()
 ├── _register_signal_handlers()
 ├── start_metrics_server()  if metrics_port set
 ├── logger.info("agent.starting")
 ├── await _setup()              ← override for Kafka init, DB seeding, warmup
 ├── lag_task = create_task(_report_consumer_lag())
 ├── try:
 │    └── await _run()
 ├── except Exception:
 │    └── logger.exception("agent.run_failed")  → re-raise
 └── finally:
      ├── lag_task.cancel()
      ├── await _teardown()      ← override for Kafka/DB teardown
      └── await stop()
```

Default implementations are no-ops — existing agents aren't broken:

```python
async def _setup(self) -> None:
    """Override to connect Kafka, seed history, etc. Called before _run()."""

async def _teardown(self) -> None:
    """Override to drain/close Kafka/DB. Called after _run() exits."""
```

With this, `IndicatorComputeAgent.start()` override is entirely replaced:
- `_setup()`: Kafka producer start, DB init, seed bar history, publish seeded state
- `_teardown()`: close Kafka consumer/producer, close DB pool

---

### 5. `running` Property

```python
@property
def running(self) -> bool:
    return not self._stop_event.is_set()
```

Every main loop becomes `while self.running:` instead of `while not self._stop_event.is_set():`.

---

### 6. Structured Exception Capture

Current `start()` lets exceptions from `_run()` propagate without structured logging. Agents crash
silently at the OS level — journald sees the traceback but the service log file sees nothing.

```python
try:
    await self._run()
except Exception:
    self.logger.exception("agent.run_failed", agent=self.name)
    raise
```

---

### 7. DLQ Helper Stub

Per `docs/agents/agents-foundation.md`, current DLQ behavior is: log error + discard. A base method makes this
a single upgrade point when DLQ topics are provisioned:

```python
async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
    """Route unprocessable payload to DLQ. Default: log and discard.

    Override when DLQ topics are provisioned:
        await self._kafka_producer.produce(topic_dlq(...), payload)
    """
    self.logger.error(
        "agent.dlq_discard",
        agent=self.name,
        error=str(error),
        payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
    )
```

---

## Part 2: ProcessManifest (replaces AgentRegistry)

### Why AgentRegistry is being replaced, not just dropped

The original design intent was correct:

> *"Implement AgentRegistry to track live agents, their Kafka topics, and resource thresholds."*

What was shipped was a stripped-down singleton that only stored `{name: agent_instance}` — the
topics and thresholds were never added. The implementation was wrong (singleton, no TTL, no
cross-process visibility) but the concept was sound. `ProcessManifest` implements the original
intent properly.

### Design

`AgentRegistry` described the storage mechanism. `ProcessManifest` describes the purpose: a
self-describing declaration of what a process contains and how it connects to the pipeline DAG.
Each systemd service is a node in that DAG. The manifest describes that node.

```python
class ProcessManifest:
    """Self-describing declaration of a process's agents, topics, and thresholds.

    Each systemd service instantiates one ProcessManifest. It is not a singleton —
    it is passed explicitly to any code that needs it (dependency injection, not
    global state). Safe to instantiate multiple times in tests.
    """

    def __init__(self, agents: list[BaseAgent]) -> None:
        self._agents = {a.name: a for a in agents}

    # ── Topology ─────────────────────────────────────────────────────────────

    @property
    def topics_consumed(self) -> set[str]:
        return {t for a in self._agents.values() for t in a.topics_consumed}

    @property
    def topics_produced(self) -> set[str]:
        return {t for a in self._agents.values() for t in a.topics_produced}

    def topology(self) -> dict:
        """DAG-compatible description of this process node."""
        return {
            name: {
                "consumes": agent.topics_consumed,
                "produces": agent.topics_produced,
                "lag_threshold": agent.lag_threshold_messages,
            }
            for name, agent in self._agents.items()
        }

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        """Per-agent health snapshot. Suitable for a /health HTTP endpoint."""
        return {
            name: {"running": agent.running}
            for name, agent in self._agents.items()
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all agents concurrently."""
        await asyncio.gather(*[a.start() for a in self._agents.values()])

    async def stop_all(self) -> None:
        """Stop all agents concurrently.
        Future: drain in reverse topological order (consumers before producers).
        """
        await asyncio.gather(*[a.stop() for a in self._agents.values()])

    # ── Validation ────────────────────────────────────────────────────────────

    async def validate_topics(self, admin_client) -> list[str]:
        """Return list of declared topics that don't exist in Redpanda.

        Call before start_all() to fail fast rather than silently consume nothing.
        A missing topic at startup is a configuration error, not a runtime error —
        surface it immediately.
        """
        ...
```

### Future Extensions the Design Accommodates

**Startup topic validation** (near-term, high value): before `start_all()`, call
`validate_topics(admin_client)`. If `IndicatorComputeAgent` declares it consumes
`development.market.bars` but that topic doesn't exist, the process fails fast with a clear error
instead of silently consuming nothing. Catches misconfigured environments at boot, not an hour
later when no data appears in the DB.

**Self-publishing topology** (medium-term): on startup, serialize `topology()` and publish to
`{env}.system.manifests`. A future `PipelineTopologyService` consumes all manifest messages and
renders the full DAG — which processes consume which topics, where gaps exist. Consistent with the
event-driven architecture: the pipeline describes itself through the same bus it uses for data.

**Mermaid/DOT graph generation** (low effort once topology() exists):

```python
def to_mermaid(self) -> str:
    """Flowchart of this process's topic connections.
    Useful for architecture docs and live dashboard panels."""
```

**Prometheus alerting config derivation**: `lag_threshold_messages` per agent → generate Prometheus
alerting rules from the manifest rather than hardcoding thresholds in `alerts.yml`. The manifest
is the source of truth; the alert config is derived from it.

**Drain ordering** (when multi-agent processes exist): `stop_all()` today is `gather()` — parallel.
Correct Renaissance shutdown is reverse topological order: drain consumers before producers so
in-flight messages aren't lost. The manifest already has the topology to derive this sort; the
implementation just needs to apply it.

**Multi-agent processes**: right now one agent per process, `ProcessManifest([single_agent])`.
When compute consolidation happens (e.g., I1+I2+I3 in one process),
`ProcessManifest([i1, i2, i3])` and `start_all()` handles coordinated boot.

### What stays out of scope

- **External service catalog** (cross-process registry): Prometheus + `systemctl` already serve
  this. Build when you have 20+ services and need a dedicated catalog.
- **Topic auto-creation**: the manifest validates, it doesn't create. Topic creation is an ops
  concern.

---

## Migration Plan

### Pre-condition: rename `FeatureWriterService` → `FeatureWriterAgent`

Do this as a **single-purpose commit** before this phase touches anything else. The naming
taxonomy is a correctness invariant — `FeatureWriterService` violates it (persistence agents use
the `WriterAgent` suffix per CLAUDE.md). Fix the invariant in isolation with a clean bisect point,
then layer behaviour changes on top of a correct foundation.

```
refactor(naming): rename FeatureWriterService → FeatureWriterAgent
```

Affected: class name in `services/feature_writer_service.py`, systemd unit check, log references,
test class names.

### Agent migration order

| Service | Current pattern | Migration effort |
|---------|----------------|-----------------|
| `IndicatorComputeAgent` | Inherits BaseAgent, overrides `start()` | Low — replace `start()` override with `_setup()/_teardown()` |
| `IntelligenceComputeAgent` | sync `signal.signal()` in `__init__` | Low — inherit + move signal handler |
| `SignalGeneratorAgent` | sync `signal.signal()` in `__init__` | Medium — Kafka setup moves to `_setup()` |
| `FeatureWriterAgent` | sync `signal.signal()` in `_signal_handler` | Medium — after rename |

Async signal handlers via `BaseAgent` (`loop.add_signal_handler`) are safer than sync
`signal.signal()` in async code — they schedule the stop event on the running loop rather than
interrupting it.

---

## Infrastructure Follow-On (Out of Scope for This Change)

- **Grafana Tempo**: single Docker container + Grafana datasource. Set
  `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318` in each systemd unit file. No code changes
  required — the SDK is already initialized, spans are no-ops until the endpoint is live.
- **Kafka trace propagation**: `opentelemetry.propagators.propagate.inject/extract` in
  `KafkaConsumerClient`/`KafkaProducerClient` message headers. Enables cross-agent waterfall traces.
  Without this, each agent's spans are isolated — useful for per-agent latency but not end-to-end
  bar journey traces.

---

## Files Affected

| File | Change |
|------|--------|
| `src/core/agent/base.py` | Add `metrics_port`, `tracer`, topic declarations, `_setup()`, `_teardown()`, `running`, DLQ helper, exception capture |
| `src/core/agent/manifest.py` | New — `ProcessManifest` |
| `src/core/agent/registry.py` | Delete |
| `src/core/agent/__init__.py` | Replace registry export with manifest export |
| `tests/unit/test_base_agent.py` | Update for new constructor, topic properties, hooks |
| `tests/unit/test_process_manifest.py` | New — replaces `test_agent_registry.py` |
| `tests/unit/test_agent_registry.py` | Delete |
| `services/feature_writer_service.py` | Rename class to `FeatureWriterAgent`; inherit `BaseAgent`; add topic declarations |
| `services/indicator_compute_agent.py` | Replace `start()` override with `_setup()/_teardown()`; add topic declarations |
| `services/signal_generator_agent.py` | Inherit `BaseAgent`; move signal handler; add topic declarations |
| `services/intelligence_compute_agent.py` | Inherit `BaseAgent`; move signal handler; add topic declarations |
| Each service `__main__` block | Add `init_tracing(service_name=...)` before `agent.start()` |
