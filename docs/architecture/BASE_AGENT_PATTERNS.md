# BaseAgent Patterns — Lifecycle Contract

**Version:** 1.0
**Last Updated:** 2026-03-30
**Source:** `src/core/agent/base.py`

## Overview

`BaseAgent` is the abstract base class for all IndicAgent pipeline agents. It provides the Renaissance Agentic DAG standard lifecycle: SIGTERM handling, structured logging, OTel tracing, and Prometheus metrics scaffolding.

## Location

```python
from src.core.agent import BaseAgent
```

## Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           BaseAgent Lifecycle                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. __init__(name, metrics_port)                                        │
│     └─→ Sets up logger, tracer, stop_event                              │
│                                                                         │
│  2. start()                                                             │
│     ├─→ Register signal handlers (SIGTERM/SIGINT)                       │
│     ├─→ Start Prometheus metrics server (if metrics_port set)          │
│     ├─→ Log "agent.starting"                                            │
│     ├─→ await _setup()                                                  │
│     │    └─→ Override: connect Kafka, seed history, etc.               │
│     ├─→ Launch _report_consumer_lag() as background task               │
│     ├─→ await _run()                                                    │
│     │    └─→ [ABSTRACT] Main loop until stop_event.set()               │
│     ├─→ Exception: log "agent.run_failed" and re-raise                  │
│     └─→ finally:                                                       │
│          ├─→ Cancel lag task                                            │
│          ├─→ await _teardown()                                          │
│          │    └─→ Override: drain/close Kafka/DB                       │
│          └─→ await stop()                                               │
│               └─→ Override: add flush logic                             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Abstract Methods (Must Implement)

| Method | Signature | Purpose |
|--------|-----------|---------|
| `_run()` | `async def _run(self) -> None` | Main agent loop. Runs until `_stop_event` is set. |

## Lifecycle Hooks (Optional Overrides)

| Method | Default | Purpose |
|--------|---------|---------|
| `_setup()` | No-op | Connect to Kafka, seed history, initialize state |
| `_teardown()` | No-op | Drain queues, close connections, flush buffers |
| `stop()` | Log "stopped" | Add cleanup logic (closes, flushes) |
| `_report_consumer_lag()` | No-op (sleep loop) | Emit `PERSISTENCE_CONSUMER_LAG` metrics |
| `_send_to_dlq()` | Log + discard | Route unprocessable payloads to DLQ topic |

## Properties (Override for ProcessManifest)

| Property | Default | Purpose |
|----------|---------|---------|
| `topics_consumed` | `[]` | Kafka topics this agent reads from |
| `topics_produced` | `[]` | Kafka topics this agent writes to |
| `lag_threshold_messages` | `1000` | Consumer lag threshold before alerting |

## Instance Attributes

| Attribute | Type | Purpose |
|-----------|------|---------|
| `name` | `str` | Agent identifier (used in logging/metrics) |
| `logger` | `structlog.BoundLogger` | Structured logger bound with `agent=name` |
| `tracer` | `Tracer` | OTel tracer (no-op when `init_tracing()` not called) |
| `_stop_event` | `asyncio.Event` | Set on SIGTERM/SIGINT to signal shutdown |
| `running` | `bool` | Property: `True` while stop_event is not set |

## Signal Handling

```python
def _register_signal_handlers(self) -> None:
    """Register SIGTERM and SIGINT handlers that set the stop event.

    Must be called from within a running event loop.
    Uses asyncio.get_running_loop() — NOT the deprecated get_event_loop().
    """
```

**Key Points:**
- Handlers are registered in `start()` before `_run()` begins
- Both SIGTERM and SIGINT set the same `_stop_event`
- The main `_run()` loop should check `self.running` or `await self._stop_event.wait()`

## Structured Logging

```python
self.logger = structlog.get_logger().bind(agent=name)
```

**Usage Pattern:**
```python
self.logger.info("event_type", key1=value1, key2=value2)
```

**Standard Event Types:**
- `agent.starting` — Agent initialization
- `agent.started` — Ready to process
- `agent.stopped` — Graceful shutdown
- `agent.run_failed` — Exception in main loop
- `agent.dlq_discard` — Unprocessable payload (when DLQ not configured)

## OTel Tracing

```python
self.tracer = get_tracer(name)
```

**Usage Pattern:**
```python
with self.tracer.start_as_current_span("operation_name"):
    # ... work ...
    pass
```

**Note:** The tracer is a no-op when `init_tracing()` has not been called. Safe to use before initialization.

## Prometheus Metrics

```python
def __init__(self, name: str, metrics_port: int | None = None):
    self._metrics_port = metrics_port
    # ...
```

**If `metrics_port` is set:**
- Metrics server starts on `start()`
- Default port range: `:9100-:9199`

**Standard Metrics:**
- `PERSISTENCE_BATCH_LATENCY` — Histogram of batch write times
- `PERSISTENCE_CONSUMER_LAG` — Gauge of consumer lag (override `_report_consumer_lag()`)

## Consumer Lag Reporting

```python
async def _report_consumer_lag(self) -> None:
    """No-op consumer lag reporter.

    Override in concrete agents to emit PERSISTENCE_CONSUMER_LAG metrics.
    Loops until _stop_event is set.
    """
    while not self._stop_event.is_set():
        await asyncio.sleep(15)
```

**Override Pattern:**
```python
async def _report_consumer_lag(self) -> None:
    while self.running:
        lag = await self._get_consumer_lag()  # Your implementation
        PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(lag)
        await asyncio.sleep(15)
```

## DLQ Pattern

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

## Minimal Implementation Example

```python
from src.core.agent import BaseAgent

class MinimalAgent(BaseAgent):
    async def _run(self) -> None:
        """Main loop — runs until stop_event is set."""
        while self.running:
            await self._process_one()
            await asyncio.sleep(1)

    async def _process_one(self) -> None:
        """Do work here."""
        self.logger.info("processing", item="example")

# Usage
agent = MinimalAgent("my_agent", metrics_port=9101)
await agent.start()
```

## Full Implementation Example (WriterAgent)

```python
from src.core.agent import BaseAgent
from src.observability.metrics import PERSISTENCE_BATCH_LATENCY, PERSISTENCE_CONSUMER_LAG

class MyWriterAgent(BaseAgent):
    def __init__(self, name: str, metrics_port: int = 9111):
        super().__init__(name, metrics_port)
        self._kafka_consumer = None
        self._db_pool = None

    async def _setup(self) -> None:
        """Connect to Kafka and DB."""
        self._kafka_consumer = create_consumer(...)
        self._db_pool = await asyncpg.create_pool(...)
        self.logger.info("writer.connected")

    async def _run(self) -> None:
        """Consume and batch write."""
        batch = []
        async for msg in self._kafka_consumer:
            if not self.running:
                break
            batch.append(msg)

            if len(batch) >= 100:
                await self._write_batch(batch)
                batch = []

    async def _write_batch(self, batch: list) -> None:
        """Persist batch with metrics."""
        with PERSISTENCE_BATCH_LATENCY.labels(agent_id=self.name).time():
            async with self._db_pool.acquire() as conn:
                await conn.executemany(...)

    async def _teardown(self) -> None:
        """Flush and close."""
        await self._kafka_consumer.close()
        await self._db_pool.close()

    async def stop(self) -> None:
        """Flush remaining items."""
        await super().stop()
        # Additional flush logic here

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag metric."""
        while self.running:
            lag = self._kafka_consumer.consumer_lag()
            PERSISTENCE_CONSUMER_LAG.labels(agent_id=self.name).set(lag)
            await asyncio.sleep(15)

    @property
    def topics_consumed(self) -> list[str]:
        return ["input.topic"]

    @property
    def lag_threshold_messages(self) -> int:
        return 500  # Alert if lag > 500
```

## See Also

- `AGENT_STANDARD.md` — Role taxonomy and naming conventions
- `CURRENT_STATE.md` — Active agents and their roles
- `OBSERVABILITY.md` — Metrics and monitoring patterns
