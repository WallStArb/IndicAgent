# Phase 109: Config Foundation & Self-Healing Engine - Pattern Map

**Mapped:** 2026-05-28
**Files analyzed:** 13
**Analogs found:** 12 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/config/config_service.py` | service | request-response | `services/alerting_agent.py` | role-match |
| `src/config/config_schema.py` | model | N/A (schemas) | `src/intelligence/schemas.py` | role-match |
| `src/config/outbox_dispatcher.py` | service | request-response | `services/feature_writer_agent.py` | role-match |
| `src/self_healing/engine.py` | service | event-driven | `services/service_auditor_agent.py` | exact |
| `src/self_healing/strategies.py` | utility | transform | N/A (simple module) | none |
| `src/self_healing/ledger.py` | service | CRUD | `src/core/database_manager.py` | role-match |
| `src/core/agent/base.py` | base | request-response | `src/core/agent/base.py` | self-modify |
| `src/observability/metrics.py` | utility | N/A (metrics) | `src/observability/metrics.py` | self-modify |
| `services/config_service_agent.py` | service | request-response | `services/alerting_agent.py` | exact |
| `services/outbox_dispatcher_agent.py` | service | request-response | `services/feature_writer_agent.py` | exact |
| `services/self_healing_agent.py` | service | event-driven | `services/service_auditor_agent.py` | exact |
| `production/migrations/109_config_foundation.sql` | migration | batch | `production/migrations/003_timescaledb_enable_and_policies.sql` | role-match |
| `src/core/stream_keys.py` | utility | N/A (helpers) | `src/core/stream_keys.py` | self-modify |

## Pattern Assignments

### `src/config/config_service.py` (service, request-response)

**Analog:** `services/alerting_agent.py` (FastAPI service pattern)

**Imports pattern** (lines 1-21 of alerting_agent.py):
```python
from __future__ import annotations

import time

import _path_bootstrap  # noqa: F401 — project root on sys.path
import aiohttp

from src.config.settings import get_settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_alert_requests
from src.observability.metrics import ALERTING_DISPATCH_TOTAL, ALERTING_LATENCY_SECONDS
```

**DB connection pattern** (from database_manager.py lines 19-30):
```python
async def create_pool(database_url: str, pool_name: str = "default", **kwargs) -> asyncpg.Pool:
    """Create an asyncpg pool with JSONB codecs and pool size gauges."""
    pool = await asyncpg.create_pool(database_url, init=_setup_codecs, **kwargs)
    DB_POOL_SIZE.add(pool.get_size(), {"pool": pool_name})
    DB_POOL_IDLE.add(pool.get_idle_size(), {"pool": pool_name})
    return pool
```

**Transactional outbox pattern** (from database_manager.py lines 79-99):
```python
async def execute_batch(self, statement: str, params: list[list[Any]] | list[tuple]) -> None:
    """Execute a batched statement within a single transaction.

    Args:
        statement: SQL statement with positional parameters
        params: Sequence of parameter tuples/lists
    """
    if not params:
        return
    async with self.get_connection() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.executemany(statement, params)
            await tr.commit()
        except Exception as exc:
            try:
                await tr.rollback()
            except Exception:
                pass  # rollback failed; re-raise original exception
            raise exc
```

**Metric creation pattern** (from metrics.py lines 67-79):
```python
def counter(name: str, documentation: str):
    """Create a named OTel counter. Used by services that create metrics dynamically."""
    return _meter.create_counter(name, description=documentation)


def gauge(name: str, documentation: str):
    """Create a named OTel up_down_counter. Use .add(delta) for cumulative tracking."""
    return _meter.create_up_down_counter(name, description=documentation)


def point_gauge(name: str, documentation: str):
    """Create a named OTel gauge for point-in-time absolute values. Use .set(value)."""
    return _meter.create_gauge(name, description=documentation)
```

**Error handling pattern** (from alerting_agent.py lines 80-119):
```python
start = time.monotonic()
try:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"*[CRITICAL]* {source}\n{message}"
    assert self._http_session is not None
    async with self._http_session.post(
        url,
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=aiohttp.ClientTimeout(total=10),
    ) as resp:
        elapsed = time.monotonic() - start
        if resp.status == 200:
            ALERTING_DISPATCH_TOTAL.add(
                1, {"channel": "telegram", "severity": "CRITICAL", "status": "success"}
            )
            ALERTING_LATENCY_SECONDS.record(elapsed, {"channel": "telegram"})
            return True
        else:
            ALERTING_DISPATCH_TOTAL.add(
                1, {"channel": "telegram", "severity": "CRITICAL", "status": "failure"}
            )
            self.logger.warning("alerting.telegram_failed", status=resp.status)
            return False
except Exception as exc:
    ALERTING_DISPATCH_TOTAL.add(
        1, {"channel": "telegram", "severity": "CRITICAL", "status": "failure"}
    )
    self.logger.error("alerting.telegram_error", error=str(exc))
    return False
```

---

### `src/config/config_schema.py` (model, schemas)

**Analog:** `src/intelligence/schemas.py`

**Pydantic model pattern** (from intelligence/schemas.py lines 1-50):
```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BarIntelligenceRecord(BaseModel):
    """Unified intelligence record for a single bar.

    All I1-I7 output in one atomic INSERT. No more two-phase writes.
    """

    ts: datetime
    symbol: str
    tf: str
    # ... other fields
```

**ConfigChange model pattern** (from RESEARCH.md lines 342-388):
```python
class ConfigChange(BaseModel):
    """Result of a config.set() operation."""

    key: str
    value: Any
    version: int
    changed_at: datetime
    changed_by: str
    reason: str | None = None
```

---

### `src/config/outbox_dispatcher.py` (service, request-response)

**Analog:** `services/feature_writer_agent.py` (BaseWriterAgent pattern)

**BaseWriterAgent imports and lifecycle** (from base_writer.py lines 1-78):
```python
from __future__ import annotations

import abc
import asyncio
import time
from typing import Any, ClassVar

from opentelemetry import metrics as _otel_metrics
from opentelemetry.trace import StatusCode
from pydantic import TypeAdapter, ValidationError

from src.core.agent.base import BaseAgent
from src.observability.metrics import PERSISTENCE_CONSUMER_LAG
from src.observability.spans import ATTR_BATCH_SIZE, ATTR_FLUSH_MS

_bw_meter = _otel_metrics.get_meter("indicagent")


class BaseWriterAgent(BaseAgent, abc.ABC):
    """Abstract base for writer agents that consume Kafka and write to DB.

    Provides the shared buffer/flush/commit/overflow/teardown pattern plus a
    default _run() consume loop. Subclasses that need custom routing (e.g.
    multi-topic dispatch) should override _run(); most can rely on the default.
    """

    BATCH_SIZE: int = 100
    FLUSH_INTERVAL_SECS: float = 5.0
    MAX_BUFFER_SIZE: int = 10_000
    BUFFER_ALERT_PCT: float = 0.80
    payload_model: ClassVar[Any] = None
```

**Kafka consumer pattern** (from kafka_utils.py lines 124-149):
```python
class KafkaConsumerClient:
    """Thin wrapper around AIOKafkaConsumer matching current service consumption patterns."""

    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = True,
    ) -> None:
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=enable_auto_commit,
        )

    async def start(self) -> None:
        """Subscribe to topics and start the consumer."""
        await self._consumer.start()

    async def stop(self) -> None:
        """Commit pending offsets, leave consumer group, and close the connection."""
        await self._consumer.stop()
```

**DB transaction with FOR UPDATE SKIP LOCKED** (from RESEARCH.md lines 402-406):
```python
# 1. Fetch pending outbox rows
async with self._db_pool.acquire() as conn:
    rows = await conn.fetch(
        "SELECT id, config_key, config_value, version, changed_at "
        "FROM config_outbox WHERE status = 'pending' "
        "FOR UPDATE SKIP LOCKED LIMIT 100"
    )
```

---

### `src/self_healing/engine.py` (service, event-driven)

**Analog:** `services/service_auditor_agent.py`

**Service auditor agent imports** (lines 1-46):
```python
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import _path_bootstrap  # noqa: F401 -- project root on sys.path
import aiohttp
import asyncpg

from src.config.settings import get_active_contracts, get_settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import (
    topic_alert_requests,
    topic_health_events,
    topic_health_events_dlq,
)
from src.observability.metrics import (
    CONSUMER_STALL_DETECTED_TOTAL,
    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL,
    SERVICE_UP_GAUGE,
)
```

**HTTP session pattern for webhook calls** (from alerting_agent.py lines 55-63):
```python
async def _setup(self) -> None:
    """Initialize Kafka consumer and HTTP session."""
    self._consumer = KafkaConsumerClient(
        topic_alert_requests(self.env_name),
        bootstrap_servers=self.settings.kafka_bootstrap_servers,
        group_id="alerting_consumer",
    )
    await self._consumer.start()
    self._http_session = aiohttp.ClientSession()
```

**Control loop pattern with pre/post measurement** (from RESEARCH.md lines 224-258):
```python
async def execute_remediation(self, alert: AlertRequest) -> RemediationResult:
    """Execute remediation with control loop feedback."""
    # 1. Measure pre-state (sensor)
    pre_value = await self._measure_state(alert.state_variable)

    # 2. Compare to setpoint
    error = pre_value - alert.threshold
    if error <= 0:
        return RemediationResult(status="no_action", ...)

    # 3. Execute action (actuator)
    strategy = REMEDIATION_STRATEGIES.get(alert.alert_id)
    if not strategy:
        return RemediationResult(status="no_strategy", ...)

    start = time.monotonic()

    # 4. Execute action with timeout
    try:
        async with asyncio.timeout(strategy.timeout_seconds):
            await strategy.execute(alert)
    except Exception as exc:
        # Record failure, don't update post_value
        await self._record_ledger(alert, pre_value, None, "failed", str(exc))
        return RemediationResult(status="failed", error=str(exc))

    # 5. Measure post-state (feedback)
    post_value = await self._measure_state(alert.state_variable)
    duration_ms = (time.monotonic() - start) * 1000

    # 6. Record outcome
    outcome = "success" if post_value < alert.threshold else "partial"
    await self._record_ledger(alert, pre_value, post_value, outcome, duration_ms)

    return RemediationResult(status=outcome, pre_value=pre_value, post_value=post_value, duration_ms=duration_ms)
```

---

### `src/self_healing/strategies.py` (utility, transform)

**No direct analog** - simple module with static strategy mapping. Pattern from RESEARCH.md lines 63-67:
```python
# Remediation Strategies (Phase 1: Conservative)
# Static mapping only, low-risk actions
REMEDIATION_STRATEGIES = {
    "disk_usage_high": RemediationStrategy(
        action="delete_old_logs",
        threshold_percent=80,
        max_per_hour=3,
        timeout_seconds=30,
    ),
    "consumer_lag_high": RemediationStrategy(
        action="restart_consumer",
        threshold_lag=1000,
        max_per_hour=2,
        timeout_seconds=60,
    ),
    # ...
}
```

---

### `src/self_healing/ledger.py` (service, CRUD)

**Analog:** `src/core/database_manager.py`

**Connection pool pattern** (lines 36-52):
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
            logger.info("Database pool initialized")
        except Exception as e:
            logger.error("Failed to initialize database pool", error=str(e))
            raise
```

**Insert pattern** (from RESEARCH.md lines 463-471):
```python
async def _record_ledger(self, alert: AlertRequest, pre_value: float, post_value: float | None,
                         outcome: str, duration_ms: int, error: str | None = None) -> None:
    """Record remediation attempt to time-series ledger."""

    remediation_id = str(uuid.uuid4())
    now = datetime.now(UTC)

    async with self._db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO remediation_ledger "
            "(timestamp, remediation_id, alert_id, state_variable, pre_value, post_value, "
            "target_value, action, outcome, duration_ms, error_message, changed_by, reason) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
            now, remediation_id, alert.alert_id, alert.state_variable, pre_value, post_value,
            alert.threshold, alert.action, outcome, duration_ms, error, "system", alert.reason
        )
```

---

### `src/core/agent/base.py` (base, request-response) - MODIFY

**Analog:** Self-modify - add config reload pattern to existing BaseAgent

**Existing _setup pattern** (lines 276-282):
```python
async def _setup(self) -> None:  # noqa: B027
    """Override to connect Kafka, seed history, etc. Called before _run().

    No-op by default — existing agents that don't override keep working.
    Not abstract: subclasses that omit _setup() are valid and common.
    """
```

**Config consumer pattern to add** (from RESEARCH.md lines 185-213):
```python
class BaseAgent:
    async def _setup(self) -> None:
        # Load DB snapshot on startup
        self._config_cache = await config_service.list()

        # Subscribe to config updates (only for OPERATIONAL layer)
        if self._config_layer == "OPS":
            self._config_consumer = KafkaConsumerClient("topic_config_updates", ...)
            asyncio.create_task(self._reload_config_loop())

    async def _reload_config_loop(self) -> None:
        """Hot-reload config on Kafka message."""
        async for _topic, _key, payload in self._config_consumer.messages():
            key = payload["config_key"]
            value = payload["config_value"]
            version = payload["version"]

            # Update cache
            self._config_cache[key] = value

            # Emit metric
            CONFIG_RELOAD_TOTAL.add(1, {"agent": self.name, "key": key})

            self.logger.info("config.reloaded", key=key, version=version)

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get config value from in-memory cache (hot path)."""
        return self._config_cache.get(key, default)
```

---

### `src/observability/metrics.py` (utility, metrics) - MODIFY

**Analog:** Self-modify - add config + self-healing metrics

**Existing metric patterns** (lines 86-99):
```python
PLUGIN_FALLBACK_TOTAL = _meter.create_counter(
    "intelligence_pipeline_plugin_fallback_total",
    description="Plugin fallbacks to direct calculation",
)
PLUGIN_DURATION_MS = _meter.create_histogram(
    "intelligence_pipeline_plugin_duration_ms",
    description="Per-plugin execution latency",
    unit="ms",
)
```

**Metrics to add** (from CONTEXT.md lines 86-88):
```python
# Config metrics
CONFIG_SET_TOTAL = _meter.create_counter(
    "config_set_total",
    description="Config set operations by key and outcome",
)
CONFIG_VALIDATION_FAILED_TOTAL = _meter.create_counter(
    "config_validation_failed_total",
    description="Config validation failures by key and reason",
)
CONFIG_REVERT_TOTAL = _meter.create_counter(
    "config_revert_total",
    description="Config revert operations by key",
)
CONFIG_OUTBOX_PENDING = _meter.create_up_down_counter(
    "config_outbox_pending",
    description="Pending config outbox entries awaiting Kafka publish",
)
CONFIG_OUTBOX_PUBLISH_LATENCY_SECONDS = _meter.create_histogram(
    "config_outbox_publish_latency_seconds",
    description="Config outbox to Kafka publish latency",
    unit="s",
)
CONFIG_RELOAD_TOTAL = _meter.create_counter(
    "config_reload_total",
    description="Config hot-reload events by agent and key",
)

# Self-healing metrics
REMEDIATION_ATTEMPT_TOTAL = _meter.create_counter(
    "remediation_attempt_total",
    description="Remediation attempts by state_variable and action",
)
REMEDIATION_SUCCESS_TOTAL = _meter.create_counter(
    "remediation_success_total",
    description="Successful remediation outcomes",
)
REMEDIATION_DURATION_SECONDS = _meter.create_histogram(
    "remediation_duration_seconds",
    description="Remediation execution latency",
    unit="s",
)
REMEDIATION_SUCCESS_RATE = _meter.create_gauge(
    "remediation_success_rate",
    description="30-day rolling success rate per action",
)
WEBHOOK_RECEIVED_TOTAL = _meter.create_counter(
    "webhook_received_total",
    description="Alertmanager webhook requests received",
)
WEBHOOK_VALIDATION_FAILED_TOTAL = _meter.create_counter(
    "webhook_validation_failed_total",
    description="Webhook payload validation failures",
)
```

---

### `services/config_service_agent.py` (service, request-response)

**Analog:** `services/alerting_agent.py`

**Service entry point pattern** (alerting_agent.py lines 161-165):
```python
if __name__ == "__main__":
    import asyncio

    asyncio.run(AlertingComputeAgent().start())
```

**FastAPI service pattern** (from api/main.py lines 170-176):
```python
# Create FastAPI application
app = FastAPI(
    title="IndicAgent API",
    description="Market Intelligence & Technical Analysis Platform",
    version="2.0.0-clean",
    lifespan=lifespan,
)
```

---

### `services/outbox_dispatcher_agent.py` (service, request-response)

**Analog:** `services/feature_writer_agent.py`

**Writer agent lifecycle** (feature_writer_agent.py lines 1-13):
```python
#!/usr/bin/env python3
"""Feature Writer Agent — persists BarIntelligenceRecord to intelligence_features hypertable.

Consumes development.intelligence.record via Kafka consumer group 'feature_writer_group'
and batch-writes complete rows to the intelligence_features TimescaleDB hypertable.

Phase 44.3: Single atomic INSERT per bar from BarIntelligenceRecord.
No more i7/i8 two-phase UPSERT writes — every row is complete at insert time.

Version: 3.0.0
Last Updated: 2026-04-13
Status: Phase 68 Plan 02 — migrated to BaseWriterAgent
"""
```

---

### `services/self_healing_agent.py` (service, event-driven)

**Analog:** `services/service_auditor_agent.py`

** systemd restart pattern** (service_auditor_agent.py lines 200-250):
```python
async def _restart_service(self, unit_name: str) -> bool:
    """Restart a systemd service via dbus.

    Returns True if restart succeeded, False otherwise.
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"http://{self._dbus_addr}/org/freedesktop/systemd1/unit/{unit_name}"
            async with session.post(url, json={"action": "restart"}) as resp:
                if resp.status == 200:
                    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"unit": unit_name, "status": "success"})
                    return True
                else:
                    SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"unit": unit_name, "status": "failure"})
                    return False
    except Exception as exc:
        SERVICE_AUDITOR_SERVICE_RESTARTS_TOTAL.add(1, {"unit": unit_name, "status": "error"})
        self.logger.error("service.restart_failed", unit=unit_name, error=str(exc))
        return False
```

---

### `production/migrations/109_config_foundation.sql` (migration, batch)

**Analog:** `production/migrations/003_timescaledb_enable_and_policies.sql`

**Hypertable creation pattern** (lines 1-23):
```sql
-- Enable TimescaleDB (idempotent)
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Convert tables to hypertables (time partition by timestamp; space partition by symbol)
SELECT create_hypertable('features', 'timestamp', 'symbol', number_partitions => 8, if_not_exists => TRUE);
SELECT create_hypertable('intelligence', 'timestamp', 'symbol', number_partitions => 8, if_not_exists => TRUE);

-- Enable native compression and add policies
ALTER TABLE features SET (timescaledb.compress = true);
ALTER TABLE intelligence SET (timescaledb.compress = true);

-- Compress chunks older than 7 days (tune per environment)
SELECT add_compression_policy('features', INTERVAL '7 days');
SELECT add_compression_policy('intelligence', INTERVAL '7 days');
```

**Config tables to create** (from CONTEXT.md lines 130-173):
```sql
CREATE TABLE config_schema (
  config_key TEXT PRIMARY KEY,
  value_type TEXT NOT NULL,
  default_value TEXT,
  min_value FLOAT,
  max_value FLOAT,
  allowed_values TEXT[],
  depends_on TEXT,
  category TEXT NOT NULL,
  is_secret BOOLEAN DEFAULT FALSE,
  version INT DEFAULT 1,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE config_state (
  config_key TEXT PRIMARY KEY,
  config_value TEXT NOT NULL,
  version INT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE config_history (
  timestamp TIMESTAMPTZ NOT NULL,
  config_key TEXT NOT NULL,
  version INT NOT NULL,
  config_value TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  reason TEXT,
  PRIMARY KEY (timestamp, config_key, version)
);
SELECT create_hypertable('config_history', 'timestamp');

CREATE TABLE config_outbox (
  id BIGSERIAL PRIMARY KEY,
  config_key TEXT NOT NULL,
  config_value TEXT NOT NULL,
  version INT NOT NULL,
  changed_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Remediation ledger pattern** (from CONTEXT.md lines 176-194):
```sql
CREATE TABLE remediation_ledger (
  timestamp TIMESTAMPTZ NOT NULL,
  remediation_id TEXT NOT NULL,
  alert_id TEXT NOT NULL,
  state_variable TEXT NOT NULL,
  pre_value FLOAT,
  post_value FLOAT,
  target_value FLOAT,
  action TEXT NOT NULL,
  outcome TEXT NOT NULL,
  duration_ms INT,
  error_message TEXT,
  changed_by TEXT NOT NULL,
  reason TEXT,
  PRIMARY KEY (timestamp, remediation_id)
);
SELECT create_hypertable('remediation_ledger', 'timestamp');
```

---

### `src/core/stream_keys.py` (utility, helpers) - MODIFY

**Analog:** Self-modify - add topic_config_updates function

**Topic builder pattern** (lines 40-48):
```python
def env_prefix(env_name: str) -> str:
    """Return Kafka topic prefix: 'dev.' for env_name='dev', '' for env_name=''."""
    return f"{env_name}." if env_name else ""


def topic_market_ticks(env_name: str) -> str:
    """Kafka topic for raw tick data from TWS daemon."""
    return f"{env_prefix(env_name)}market.ticks"
```

**Function to add** (from CONTEXT.md line 70):
```python
def topic_config_updates(env_name: str) -> str:
    """Kafka topic for config change propagation (compacted).

    Partition key: config_key (ensures ordering per key).
    Schema: config_key, config_value, version, changed_by, changed_at, reason, redacted, correlation_id.
    """
    return f"{env_prefix(env_name)}config.updates"
```

---

## Shared Patterns

### Database Connection (asyncpg pool)
**Source:** `src/core/database_manager.py`
**Apply to:** All services writing to DB (config_service, outbox_dispatcher, self_healing)
```python
from src.core.database_manager import create_pool

# In _setup()
self.pool = await create_pool(
    settings.database_url,
    min_size=2,
    max_size=10,
    command_timeout=30
)

# In queries
async with self.pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(...)
```

### Kafka Producer/Consumer
**Source:** `src/core/kafka_utils.py`
**Apply to:** All Kafka-consuming/producing services
```python
from src.core.kafka_utils import KafkaProducerClient, KafkaConsumerClient

# Producer
self._producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
await self._producer.start()
await self._producer.publish(topic, payload, key=key)

# Consumer
self._consumer = KafkaConsumerClient(
    topic_name(env_name),
    bootstrap_servers=settings.kafka_bootstrap_servers,
    group_id="my_consumer",
)
await self._consumer.start()
async for _topic, _key, payload in self._consumer.messages():
    # Process
```

### OTel Metrics Creation
**Source:** `src/observability/metrics.py`
**Apply to:** All services emitting metrics
```python
from opentelemetry import metrics as otel_metrics

_meter = otel_metrics.get_meter("indicagent")

MY_COUNTER = _meter.create_counter(
    "my_metric_total",
    description="My counter metric",
)
MY_HISTOGRAM = _meter.create_histogram(
    "my_duration_seconds",
    description="My duration metric",
    unit="s",
)
```

### OTel Spans
**Source:** `src/observability/spans.py`
**Apply to:** ConfigService.set(), SelfHealingEngine.execute_remediation()
```python
from src.observability.spans import observed_span, ATTR_BATCH_SIZE

async with observed_span("config.set", tracer=self.tracer, key=key) as span:
    span.set_attribute("value_type", type(value).__name__)
    result = await self._do_set(key, value)
```

### Systemd Service Template
**Source:** `production/systemd/indicagent-alerting-agent.service`
**Apply to:** New systemd units (config-service, outbox-dispatcher, self-healing)
```ini
[Unit]
Description=IndicAgent <Service Name>
After=network-online.target indicagent-infrastructure.target
Requires=indicagent-infrastructure.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/<service>.py
Restart=always
WatchdogSec=60
NotifyAccess=main
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-<service>

[Install]
WantedBy=multi-user.target
```

### Structlog Pattern
**Source:** All agents via BaseAgent (src/core/agent/base.py lines 134-135)
**Apply to:** All services
```python
import structlog

logger = structlog.get_logger().bind(agent="my_agent")
logger.info("event.message", key=value, error=str(exc))
```

---

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/self_healing/strategies.py` | utility | transform | Simple static mapping module; no analog needed |
| `src/config/config_schema.py` | model | schemas | Pydantic pattern is standard; schemas.py provides structure |

## Metadata

**Analog search scope:** services/, src/config/, src/core/, src/observability/, src/api/, production/
**Files scanned:** 20
**Pattern extraction date:** 2026-05-28
