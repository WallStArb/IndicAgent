# Phase 107: Infrastructure Hygiene - Pattern Map

**Mapped:** 2026-05-25
**Files analyzed:** 12
**Analogs found:** 10 / 12

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/signal_replay_auditor_agent.py` | service | request-response | `services/bar_replay_provider_agent.py` | exact |
| `services/bar_replay_provider_agent.py` | service | request-response | `services/swarm_ledger_writer_agent.py` | role-match |
| `services/swarm_ledger_writer_agent.py` | service | CRUD | `services/feature_writer_agent.py` | role-match |
| `services/ctx_writer_agent.py` | service | request-response | `services/feature_writer_agent.py` | exact |
| `services/llm_writer_service.py` | service | request-response | `services/feature_writer_agent.py` | exact |
| `services/feature_writer_agent.py` | service | request-response | `services/ctx_writer_agent.py` | exact |
| `services/shadow_auditor_agent.py` | service | event-driven | `services/service_auditor_agent.py` | role-match |
| `services/service_auditor_agent.py` | service | event-driven | `services/shadow_auditor_agent.py` | role-match |
| `src/config/settings.py` | config | read-only | `src/config/settings.py` | self |
| `src/core/ml/shadow.py` | utility | transform | No analog (dead code) | none |
| `src/core/llm/guardrails.py` | utility | transform | No analog (dead code) | none |
| `src/intelligence/ai/TEMPLATE_agent.py` | component | request-response | `src/intelligence/ai/alpha/skeptic_agent.py` | exact |

## Pattern Assignments

### `services/signal_replay_auditor_agent.py` (service, request-response)

**Analog:** `services/bar_replay_provider_agent.py` (current state before migration)

**Migration target pattern** from `src/core/agent/base.py` (lines 77-100):

**BaseAgent constructor pattern** (lines 95-100):
```python
def __init__(
    self,
    name: str,
    max_idle_seconds: int = 0,
    settings: Settings | None = None,
) -> None:
```

**Custom lifecycle BEFORE migration** (lines 41-66 from signal_replay_auditor_agent.py):
```python
class SignalReplayAuditorAgent:
    agent_id = "signal_replay_auditor"

    def __init__(self) -> None:
        self._log = structlog.get_logger(self.agent_id)
        self._settings = Settings()
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._stop = asyncio.Event()  # Custom stop event
        self._last_unresolved_count: int = 0

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self._settings.database_url,
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )
        self._producer = KafkaProducerClient(...)
        await self._producer.start()
        self._log.info("signal_replay_auditor.started")
```

**BaseAgent migration pattern** (HYGIENE-07):
```python
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool

class SignalReplayAuditorAgent(BaseAgent):
    """Inherits full BaseAgent lifecycle."""

    def __init__(self) -> None:
        super().__init__(
            name="signal_replay_auditor",
            max_idle_seconds=600,  # Enable stall detection
        )
        # Now available: self.tracer, self._meter, self.logger, self.settings
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None

    async def _setup(self) -> None:
        # Use DatabaseManager.create_pool() (HYGIENE-08):
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="signal_replay_auditor",
            min_size=1,
            max_size=3,
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers
        )
        await self._producer.start()
        self.logger.info("signal_replay_auditor.started")

    async def _run(self) -> None:
        while self.running:
            await self._run_audit_cycle()
            await asyncio.sleep(REPLAY_INTERVAL_SECONDS)

    async def _teardown(self) -> None:
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()
```

**Direct asyncpg bypass pattern** (lines 69-75 - WRONG):
```python
# BEFORE (HYGIENE-08 violation):
async def _setup(self) -> None:
    self._pool = await asyncpg.create_pool(
        self._settings.database_url,
        pool_name="signal_replay_auditor",
        min_size=1,
        max_size=3,
    )
```

**DatabaseManager standardization pattern** (HYGIENE-08):
```python
# AFTER (from database_manager.py lines 25-30):
from src.core.database_manager import create_pool as create_db_pool

async def _setup(self) -> None:
    self._pool = await create_db_pool(
        self.settings.database_url,
        pool_name="signal_replay_auditor",
        min_size=1,
        max_size=3,
    )
    # Now has JSONB codecs registered and emits DB_POOL_SIZE/DB_POOL_IDLE gauges
```

---

### `services/bar_replay_provider_agent.py` (service, request-response)

**Analog:** `services/swarm_ledger_writer_agent.py` (already uses BaseAgent)

**BaseAgent migration pattern** from swarm_ledger_writer_agent.py (lines 70-86):
```python
class SwarmLedgerWriterAgent(BaseAgent):
    """Consumes swarm.alpha events and UPSERTs aggregate adjustments into signal_ai_enrichment."""

    agent_id = "swarm_ledger_writer"

    def __init__(self, **kwargs) -> None:
        setup_service_logging("logs/swarm_ledger_writer_agent.log")
        super().__init__(name="swarm_ledger_writer", **kwargs)
        self._pool: asyncpg.Pool | None = None
        self._consumer: KafkaConsumerClient | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            pool_name="swarm_ledger_writer",
            min_size=2,
            max_size=8,
        )
```

**Custom lifecycle BEFORE migration** (bar_replay_provider_agent.py lines 41-66):
```python
class BarReplayProviderAgent:
    agent_id = "bar_replay_provider"

    def __init__(self) -> None:
        self._log = structlog.get_logger(self.agent_id)
        self._settings = Settings()
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._stop = asyncio.Event()  # Custom stop event
        self._last_replayed_ts: datetime | None = None
        self._rate_bps = DEFAULT_RATE_BPS
```

**Self-termination pattern** (bar_replay_provider_agent.py lines 186-188):
```python
async def _run(self) -> None:
    while self.running:
        # Main loop here
        if completion_condition:
            self.logger.info("bar_replay_provider.complete")
            sys.exit(0)  # Self-termination on completion
```

**DatabaseManager pattern** (HYGIENE-08) from database_manager.py (lines 25-30):
```python
async def create_pool(database_url: str, pool_name: str = "default", **kwargs) -> asyncpg.Pool:
    """Create an asyncpg pool with JSONB codecs and pool size gauges."""
    pool = await asyncpg.create_pool(database_url, init=_setup_codecs, **kwargs)
    DB_POOL_SIZE.add(pool.get_size(), {"pool": pool_name})
    DB_POOL_IDLE.add(pool.get_idle_size(), {"pool": pool_name})
    return pool
```

---

### `services/swarm_ledger_writer_agent.py` (service, CRUD)

**Analog:** `services/feature_writer_agent.py` (BaseWriterAgent pattern)

**DatabaseManager bypass pattern** (swarm_ledger_writer_agent.py lines 89-95):
```python
# BEFORE (HYGIENE-08 violation):
async def _setup(self) -> None:
    self._pool = await create_db_pool(
        self.settings.database_url,
        pool_name="swarm_ledger_writer",
        min_size=2,
        max_size=8,
    )
```

**Standardization pattern** (HYGIENE-08):
```python
# AFTER (same import pattern):
from src.core.database_manager import create_pool as create_db_pool

async def _setup(self) -> None:
    self._pool = await create_db_pool(
        self.settings.database_url,
        pool_name="swarm_ledger_writer",
        min_size=2,
        max_size=8,
    )
```

---

### `services/ctx_writer_agent.py` (service, request-response)

**Analog:** `services/feature_writer_agent.py` (BaseWriterAgent with flush)

**Writer flush span instrumentation pattern** (HYGIENE-01) from spans.py (lines 18-32):
```python
from src.observability.spans import observed_span, ATTR_BATCH_SIZE, ATTR_FLUSH_MS

class CtxWriterAgent(BaseWriterAgent):
    async def _flush(self, event_batch: list[tuple], snapshot_batch: list[tuple]) -> None:
        # Wrap entire flush in observed_span for visibility
        async with observed_span("writer.flush", tracer=self.tracer) as span:
            flush_start = time.monotonic()

            # Flush ctx_events buffer
            if event_batch:
                async with self._db.pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_INSERT_CTX_EVENT_SQL, event_batch)
                        span.set_attribute(ATTR_BATCH_SIZE, len(event_batch))
                        self._events_written.add(len(event_batch))

            # Flush ctx_snapshots buffer
            if snapshot_batch:
                async with self._db.pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.executemany(_CLOSE_PRIOR_SNAPSHOT_SQL, close_params)
                        await conn.executemany(_UPSERT_CTX_SNAPSHOT_SQL, upsert_params)
                        span.set_attribute("snapshot_batch_size", len(snapshot_batch))
                        self._snapshots_written.add(len(snapshot_batch))

            flush_ms = (time.monotonic() - flush_start) * 1000
            span.set_attribute(ATTR_FLUSH_MS, flush_ms)
```

**OTel counter .inc() AttributeError bug** (HYGIENE-03) from ctx_writer_agent.py (lines 343, 351):
```python
# BEFORE (WRONG - causes AttributeError):
async def _flush(self) -> event_batch, snapshot_batch):
    CTX_EVENTS_WRITTEN_TOTAL.inc(len(self._ctx_event_buffer))  # WRONG
    CTX_SNAPSHOTS_WRITTEN_TOTAL.inc(len(self._ctx_snapshot_buffer))  # WRONG

# AFTER (CORRECT):
async def _flush(self, event_batch: list[tuple], snapshot_batch: list[tuple]) -> None:
    # ... flush logic ...
    self._events_written.add(len(event_batch), self._batch_latency_attrs)
    self._snapshots_written.add(len(snapshot_batch), self._batch_latency_attrs)
```

**Missing super()._teardown() bug** (HYGIENE-03) from ctx_writer_agent.py (lines 376-388):
```python
# BEFORE (WRONG - final flush never runs):
async def _teardown(self) -> None:
    if self._producer:
        await self._producer.stop()
    # Missing super()._teardown() — final flush never runs

# AFTER (CORRECT):
async def _teardown(self) -> None:
    await super()._teardown()  # MUST be first — calls BaseWriterAgent._teardown()
    if self._producer:
        await self._producer.stop()
```

**BaseWriterAgent teardown contract** from base_writer.py (lines 300-320):
```python
async def _teardown(self) -> None:
    """Default teardown: final flush + stop consumer."""
    self._stopping = True
    if self._buffer:
        self.logger.info("final_flush", rows=len(self._buffer))
        try:
            await self._do_flush()
        except Exception:
            self.logger.exception("final_flush_failed")
    if self._consumer and hasattr(self._consumer, "stop"):
        try:
            await self._consumer.stop()
        except Exception:
            self.logger.exception("consumer_stop_failed")
```

---

### `services/llm_writer_service.py` (service, request-response)

**Analog:** `services/feature_writer_agent.py` (BaseWriterAgent pattern)

**AttributeError: self._pool bug** (HYGIENE-03) - pattern from feature_writer_agent.py (lines 345-349):
```python
# BEFORE (WRONG - self._pool never initialized):
async def _process_calls_message(self, msg: dict) -> None:
    async with self._pool.acquire() as conn:  # WRONG — self._pool is None
        await conn.execute(_UPDATE_PARSE_SQL, call_id, parse_success)

# AFTER (CORRECT - use DatabaseManager):
async def _process_calls_message(self, msg: dict) -> None:
    await self.db_manager.execute_command(_UPDATE_PARSE_SQL, call_id, parse_success)
```

**DatabaseManager pattern** from database_manager.py (lines 33-50):
```python
class DatabaseManager:
    """Simplified database manager for core operations."""

    def __init__(self, database_url: str):
        """Initialize database manager."""
        self.database_url = database_url
        self.pool: asyncpg.Pool | None = None

    async def initialize(self):
        """Initialize database connection pool."""
        if self.pool is not None:
            return
        try:
            self.pool = await create_pool(
                self.database_url, min_size=2, max_size=10, command_timeout=30
            )
            logger.info("✅ Database pool initialized")
        except Exception as e:
            logger.error("❌ Database pool initialization failed", error=str(e))
            raise
```

---

### `services/feature_writer_agent.py` (service, request-response)

**Analog:** `services/ctx_writer_agent.py` (BaseWriterAgent)

**Ghost-run mode bug** (HYGIENE-03) from feature_writer_agent.py (lines 402-411):
```python
# BEFORE (WRONG - service continues without DB):
async def _connect_database(self) -> None:
    dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
    try:
        mgr = DatabaseManager(dsn)
        await mgr.initialize()
        self.db_manager = mgr
        self.logger.info("Connected to database")
    except Exception as e:
        self.logger.error("feature_writer.db_connect_failed", error=str(e))
        # BUG: Falls through, db_manager stays None, service continues consuming

# AFTER (CORRECT - raise to trigger systemd restart):
async def _connect_database(self) -> None:
    dsn = self.config["database"].get("dsn") or self.config["database"].get("url")
    try:
        mgr = DatabaseManager(dsn)
        await mgr.initialize()
        self.db_manager = mgr
        self.logger.info("Connected to database")
    except Exception as e:
        self.logger.error("feature_writer.db_connect_failed", error=str(e))
        raise  # Must raise so systemd restarts the service
```

**Flush span instrumentation pattern** (HYGIENE-01) from feature_writer_agent.py (lines 323-342):
```python
# BEFORE (no span coverage):
async def _flush_batch(self, batch: list) -> None:
    if not self.db_manager:
        raise RuntimeError("No database connection")

    await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, batch)
    # Flush failures invisible to OTel

# AFTER (with observed_span):
from src.observability.spans import observed_span, ATTR_BATCH_SIZE

async def _flush_batch(self, batch: list) -> None:
    if not self.db_manager:
        raise RuntimeError("No database connection")

    async with observed_span("writer.flush", tracer=self.tracer) as span:
        await self.db_manager.execute_batch(_INSERT_FEATURE_SQL, batch)
        span.set_attribute(ATTR_BATCH_SIZE, len(batch))
```

---

### `services/shadow_auditor_agent.py` (service, event-driven)

**Analog:** `services/service_auditor_agent.py` (timer-triggered audit pattern)

**Shadow metric type violations** (HYGIENE-02) from metrics.py (lines 244-260):
```python
# BEFORE (wrong instrument type):
SHADOW_WIN_RATE = _meter.create_up_down_counter(
    "shadow_win_rate",
    description="Shadow plugin win rate",
)
# Usage: SHADOW_WIN_RATE.add(0.65, {"plugin": "rsi"})  # WRONG — accumulates forever

# AFTER (correct instrument type):
SHADOW_WIN_RATE = _meter.create_gauge(
    "shadow_win_rate",
    description="Shadow plugin win rate",
)
# Usage: SHADOW_WIN_RATE.set(0.65, {"plugin": "rsi"})  # CORRECT — absolute value

# Apply to all 5 shadow metrics:
SHADOW_N_RESOLVED = _meter.create_gauge("shadow_n_resolved", "Resolved shadow signals")
SHADOW_EV_R = _meter.create_gauge("shadow_ev_r", "Shadow plugin E[PnL_R]")
SHADOW_EV_CI_LOWER = _meter.create_gauge("shadow_ev_ci_lower", "Shadow 95% CI lower bound")
SHADOW_DAYS_TO_GATE = _meter.create_gauge("shadow_days_to_gate", "Estimated days to N=100")
```

**Shadow promotion/demotion query fixes** (HYGIENE-06):
```python
# BEFORE (WRONG - shadow signals contaminate live track):
SELECT * FROM signal_ledger
WHERE setup_plugin = $1
  AND outcome IS NOT NULL
  -- Missing: AND is_shadow = FALSE

# AFTER (CORRECT):
SELECT * FROM signal_ledger
WHERE setup_plugin = $1
  AND outcome IS NOT NULL
  AND is_shadow = FALSE  # CRITICAL: exclude shadow signals from live stats
```

---

### `services/service_auditor_agent.py` (service, event-driven)

**Analog:** `services/shadow_auditor_agent.py` (audit pattern)

**DAG order registry pattern** (HYGIENE-04) from service_auditor_agent.py (lines 55-108):
```python
# DAG topology: unit name -> restart priority (lower = restart first)
_DAG_ORDER: dict[str, int] = {
    # Priority 0 — infrastructure sentinels
    "indicagent-redpanda-ready": 0,
    "indicagent-redpanda-watchdog": 0,
    # Layer 1 — data ingestion
    "indicagent-ibkr-provider": 1,
    "indicagent-bar-replay": 1,
    "indicagent-provider-merger": 2,
    # ... add missing 11 services here ...
}

# Lag thresholds per service (0 = not a Kafka consumer)
_LAG_THRESHOLDS: dict[str, int] = {
    "indicagent-provider-merger": 500,
    "indicant-bar-aggregator": 500,
    # ... ensure all services have thresholds ...
}

# Maps persistence_consumer_lag agent_id label -> systemd unit name
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer_agent": "indicagent-bar-writer",
    "feature_writer_agent": "indicagent-feature-writer",
    # ... keys MUST match super().__init__(name=...) calls ...
}
```

**Metric label consistency** (HYGIENE-09) from base.py (lines 95-100):
```python
# BEFORE (inconsistent label keys):
self._last_msg_ts_attrs = {"agent": name}  # BaseAgent uses "agent"
self._batch_latency_attrs = {"agent_id": self.name.lower()}  # BaseWriterAgent uses "agent_id"

# AFTER (standardized on "agent_id"):
self._last_msg_ts_attrs = {"agent_id": name}  # Changed from "agent"
self._batch_latency_attrs = {"agent_id": self.name.lower()}  # Already correct
```

---

### `src/config/settings.py` (config, read-only)

**Analog:** Self-reference (dead field removal)

**Dead Settings fields pattern** (HYGIENE-05) from settings.py (scan for unused fields):
```python
# BEFORE (8 dead fields - HYGIENE-05):
class Settings(BaseSettings):
    swarm_queue_timeout_ms: int = Field(default=5000, validation_alias="SWARM_QUEUE_TIMEOUT_MS")  # DEAD
    llm_rate_limit_rpm: int = Field(default=10, validation_alias="LLM_RATE_LIMIT_RPM")  # DEAD
    llm_rate_limit_tpm: int = Field(default=1000, validation_alias="LLM_RATE_LIMIT_TPM")  # DEAD
    shadow_correlation_threshold: float = Field(default=0.7, validation_alias="SHADOW_CORRELATION_THRESHOLD")  # DEAD
    shadow_min_samples: int = Field(default=30, validation_alias="SHADOW_MIN_SAMPLES")  # DEAD
    langfuse_host: str = Field(default="", validation_alias="LANGFUSE_HOST")  # DEAD
    mlflow_tracking_uri: str = Field(default="", validation_alias="MLFLOW_TRACKING_URI")  # DEAD
    # ... plus one orphan field ...

# AFTER (delete all 8 dead fields):
class Settings(BaseSettings):
    # Remove all unused fields above
    # Keep only actively used fields
```

---

### `src/core/ml/shadow.py` (utility, transform)

**Analog:** None (dead code deletion - HYGIENE-05)

**ShadowRecorder deletion pattern**:
```python
# BEFORE (entire file - DEAD CODE):
# src/core/ml/shadow.py

# AFTER (delete file):
rm src/core/ml/shadow.py
# Remove all imports of ShadowRecorder across codebase
```

---

### `src/core/llm/guardrails.py` (utility, transform)

**Analog:** None (dead code deletion - HYGIENE-05)

**GuardrailsValidator deletion pattern**:
```python
# BEFORE (entire file - DEAD CODE):
# src/core/llm/guardrails.py

# AFTER (delete file):
rm src/core/llm/guardrails.py
# Remove all imports of GuardrailsValidator across codebase
```

---

### `src/intelligence/ai/TEMPLATE_agent.py` (component, request-response)

**Analog:** `src/intelligence/ai/alpha/skeptic_agent.py` (reference implementation)

**TEMPLATE bug fix** (HYGIENE-05) from TEMPLATE_agent.py (lines 37-50):
```python
# BEFORE (WRONG - agent_id format):
agent_id = "template_v1"  # WRONG - shadow_registry expects "template"

# AFTER (CORRECT):
agent_id = "template"  # CORRECT - no _v1 suffix for shadow_registry lookup
# Keep version info in prompt_version, not agent_id
```

**BaseMultiplierAgent pattern** from TEMPLATE_agent.py (lines 37-50):
```python
class TemplateComputeAgent(BaseMultiplierAgent):
    """One-line description of what this agent decides and why."""

    # Required class attributes — every multiplier agent MUST set these six.
    output_schema: ClassVar[dict] = {
        "score": float,  # agent-specific key (rename per agent)
        "confidence": float,  # always required
        "reasoning": str,  # always required
    }

    agent_id = "template"  # MUST match shadow_registry.component_name (no _v1 suffix)
    group = "alpha"  # one of: "alpha", "narrative", "risk"
    tiers_needed = frozenset({Tier.I1, Tier.I4, Tier.I6})  # tiers consumed
    latency_budget_ms = 5000.0  # asyncio.wait_for in BaseAIAgent.compute
```

---

## Shared Patterns

### BaseAgent Lifecycle (HYGIENE-07)

**Source:** `src/core/agent/base.py` (lines 77-100, 200-250)
**Apply to:** All services not already inheriting from BaseAgent

```python
from src.core.agent.base import BaseAgent

class MyService(BaseAgent):
    def __init__(self) -> None:
        super().__init__(
            name="my_service",
            max_idle_seconds=300,  # Enable stall detection
        )
        # Now available: self.tracer, self._meter, self.logger, self.settings
        self._producer: KafkaProducerClient | None = None

    async def _setup(self) -> None:
        # Initialize resources
        pass

    async def _run(self) -> None:
        while self.running:
            # Main loop here
            pass

    async def _teardown(self) -> None:
        # Cleanup resources
        pass

# Inherited from BaseAgent:
# - SIGTERM/SIGINT handlers (auto-registered in start())
# - Stall detection (self.max_idle_seconds > 0 enables watchdog)
# - OTel MeterProvider/TracerProvider (initialized in start())
# - Metrics port at :8000/metrics
# - _send_to_dlq() stub (override _dlq_topic() to enable routing)
```

### DatabaseManager Pool Standardization (HYGIENE-08)

**Source:** `src/core/database_manager.py` (lines 25-30)
**Apply to:** All services with DB connections

```python
from src.core.database_manager import create_pool as create_db_pool

async def _setup(self) -> None:
    self._pool = await create_db_pool(
        self.settings.database_url,
        pool_name="my_service",
        min_size=2,
        max_size=10,
    )
    # Now has JSONB codecs registered and emits DB_POOL_SIZE/DB_POOL_IDLE gauges
```

### Writer Flush Span Instrumentation (HYGIENE-01)

**Source:** `src/observability/spans.py` (lines 18-32)
**Apply to:** All `*_writer_agent.py` services

```python
from src.observability.spans import observed_span, ATTR_BATCH_SIZE, ATTR_FLUSH_MS

async def _flush(self, batch: list) -> None:
    async with observed_span("writer.flush", tracer=self.tracer) as span:
        flush_start = time.monotonic()

        # Flush logic here
        await self._write_to_db(batch)

        flush_ms = (time.monotonic() - flush_start) * 1000
        span.set_attribute(ATTR_BATCH_SIZE, len(batch))
        span.set_attribute(ATTR_FLUSH_MS, flush_ms)

    # If flush raises, observed_span auto-sets ERROR status and records exception
```

### OTel Metric Type Corrections (HYGIENE-02)

**Source:** `src/observability/metrics.py` (lines 44-56)
**Apply to:** All metric definitions

```python
from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("indicagent")

# Counter: Monotonically increasing count (never decreases)
MY_COUNTER = _meter.create_counter("my_counter", description="Total count")
# Usage: MY_COUNTER.add(1, {"label_key": value})

# UpDownCounter: Gauge that goes up and down (cumulative delta)
MY_UP_DOWN = _meter.create_up_down_counter("my_up_down", description="Current value")
# Usage: MY_UP_DOWN.add(delta, {"label_key": value})

# Gauge: Point-in-time absolute value (NOT cumulative)
MY_GAUGE = _meter.create_gauge("my_gauge", description="Current value")
# Usage: MY_GAUGE.set(value, {"label_key": value})

# Histogram: Distribution of values (latency, batch size)
MY_HISTOGRAM = _meter.create_histogram("my_histogram", description="Latency", unit="ms")
# Usage: MY_HISTOGRAM.record(value, {"label_key": value})
```

### Metric Label Consistency (HYGIENE-09)

**Source:** `src/core/agent/base.py` (lines 95-100)
**Apply to:** All services

```python
# Standardize on "agent_id" everywhere
self._last_msg_ts_attrs = {"agent_id": name}  # Changed from "agent"
self._batch_latency_attrs = {"agent_id": self.name.lower()}
```

### AttributeError Bug Prevention (HYGIENE-03)

**Source:** Multiple files (ctx_writer_agent.py, llm_writer_service.py, feature_writer_agent.py)
**Apply to:** All services

```python
# 1. Use .add() for OTel counters, NOT .inc()
MY_COUNTER.add(delta, attrs)  # CORRECT
MY_COUNTER.inc(delta)  # WRONG - AttributeError

# 2. Always call super()._teardown() when overriding
async def _teardown(self) -> None:
    await super()._teardown()  # MUST be first
    # Your cleanup code here

# 3. Raise on DB connection failure in writer services
async def _connect_database(self) -> None:
    try:
        self.db_manager = DatabaseManager(dsn)
        await self.db_manager.initialize()
    except Exception as e:
        self.logger.error("db_connect_failed", error=str(e))
        raise  # MUST raise so systemd restarts the service

# 4. Use DatabaseManager, NOT self._pool
await self.db_manager.execute_command(sql, *params)  # CORRECT
async with self._pool.acquire() as conn:  # WRONG if _pool never initialized
```

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/core/ml/shadow.py` | utility | transform | Dead code deletion - no analog needed |
| `src/core/llm/guardrails.py` | utility | transform | Dead code deletion - no analog needed |

## Metadata

**Analog search scope:** `services/`, `src/core/agent/`, `src/core/database_manager.py`, `src/observability/`
**Files scanned:** 15
**Pattern extraction date:** 2026-05-25

**Key insights:**
- BaseAgent lifecycle pattern is well-established (38/42 services already use it)
- DatabaseManager pool pattern is consistent across most services
- Writer flush span coverage is the primary gap (HYGIENE-01)
- OTel metric type violations are localized to shadow metrics (HYGIENE-02)
- AttributeError bugs follow predictable patterns (HYGIENE-03)
- DAG order registry needs 11 missing services added (HYGIENE-04)
- Dead code deletion is straightforward git revert if needed (HYGIENE-05)
