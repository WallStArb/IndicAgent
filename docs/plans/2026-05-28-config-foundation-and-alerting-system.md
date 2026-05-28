# Config Foundation and Alerting System Design

**Date:** 2026-05-28
**Status:** Design Draft
**Principles:** Renaissance-style — mathematical rigor, provable correctness, time-series thinking, strong foundation

## Executive Summary

Build a unified config system and alerting infrastructure that treats all state as time-series data, validates at write time, propagates via Kafka, and enables zero-downtime runtime tuning.

**Core insight:** Alerts are a signal processing problem. All events (metrics, logs, traces) are time-series features with information content, noise ratio, risk/reward, and regime awareness. The system processes these signals to extract meaning, not just fire on static thresholds.

**Everything OFF by default.** Infrastructure ready, operators enable when needed.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                          ALL EVENTS → KAFKA (unified bus)                           │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         CONFIG FOUNDATION (New System)                              │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  ConfigSchemaRegistry — what keys exist, types, constraints                   │   │
│  │  config_schema table + validation logic                                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  ConfigService — set/get/revert with validation                              │   │
│  │  • set(key, value, changed_by) → validates → writes DB → emits Kafka         │   │
│  │  • get(key) → in-memory cache (hot) else DB (cold)                           │   │
│  │  • revert_key(key, version) → atomic rollback                                 │   │
│  │  • list() → all current config                                               │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Storage Layer                                                               │   │
│  │  • config_state (current: fast lookup)                                        │   │
│  │  • config_history (time-series: audit, rollback, time-travel)                 │   │
│  │  • config_schema (registry: validation)                                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Propagation Layer                                                           │   │
│  │  topic_config_updates → all services subscribe → hot-reload                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         ALERT FOUNDATION (Consumer of Config)                        │
│                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  AlertSignalProcessor — Layer 8 brain (NEW)                                  │   │
│  │  • Consume all events (metrics, logs, traces, business signals)              │   │
│  │  • Apply rules (dedupe, aggregate, correlate)                                │   │
│  │  • Query ConfigService for enable/disable                                    │   │
│  │  • Emit to topic_alert_requests                                               │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                      │                                              │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  AlertingAgent (EXISTS) — Layer 9 dispatcher                                 │   │
│  │  • Consume topic_alert_requests                                              │   │
│  │  • CRITICAL → Telegram, HIGH/MEDIUM → Discord                               │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Three Semantic Config Layers

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 1: INFRASTRUCTURE (ENV) — "Where is the system?"                            │
│  • Database URLs, Kafka brokers, secrets, IBKR config                             │
│  • Change = restart                                                               │
│  • No validation needed (system fails fast on bad config)                         │
│  • Location: .env file, read by settings.py                                      │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 2: STRUCTURE (Code/YAML) — "What exists?"                                  │
│  • Plugin tiers (TIER_I1...TIER_I7), DAG order, service definitions                │
│  • Change = deploy (code review, testing)                                         │
│  • Version-controlled with code                                                   │
│  • Location: register_plugins.py, service_auditor_agent.py                       │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 3: OPERATIONAL (DB + Kafka) — "How does it behave?"                        │
│  • Feature flags, thresholds, windows, enable/disable                              │
│  • Change = hot-reload (no restart)                                               │
│  • Validated, versioned, auditable, rollback-able                                 │
│  • Location: config_state DB + Kafka propagation                                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Key insight:** These layers are orthogonal. Never mix them.

---

## Database Schema

### config_schema (Registry)

```sql
-- Config schema: what keys exist, types, constraints
CREATE TABLE config_schema (
    config_key TEXT PRIMARY KEY,
    value_type TEXT NOT NULL,  -- 'float', 'int', 'bool', 'string', 'json'
    default_value JSONB NOT NULL,
    min_value FLOAT,           -- For numeric types
    max_value FLOAT,
    allowed_values JSONB,      -- For enum types: [0.6, 0.7, 0.8]
    depends_on TEXT[],         -- Keys that affect this one
    constraints TEXT,          -- Validation rules (JSON schema or expression)
    description TEXT,
    category TEXT,             -- 'alert', 'swarm', 'regime', 'roll', etc.
    version INTEGER NOT NULL DEFAULT 1
);

-- Example entries
INSERT INTO config_schema (config_key, value_type, default_value, min_value, max_value, description, category) VALUES
  ('regime.prob_min', 'float', '0.30', 0.0, 1.0, 'Regime gate probability floor', 'regime'),
  ('regime.prob_soft_max', 'float', '0.55', 0.0, 1.0, 'Regime gate soft band ceiling', 'regime'),
  ('swarm.min_confidence', 'float', '0.6', 0.0, 1.0, 'Minimum confidence for swarm enrichment', 'swarm'),
  ('swarm.max_concurrent_calls', 'int', '8', 1, 16, 'Max concurrent LLM calls', 'swarm'),
  ('alert.disk_space_critical.enabled', 'bool', 'false', NULL, NULL, 'Disk space critical alert enable', 'alert'),
  ('alert.service_down.enabled', 'bool', 'false', NULL, NULL, 'Service down alert enable', 'alert');

-- Constraint: prob_soft_max must be > prob_min
UPDATE config_schema SET depends_on = ARRAY['regime.prob_min'] WHERE config_key = 'regime.prob_soft_max';
```

### config_state (Current)

```sql
-- Current config state: fast lookup
CREATE TABLE config_state (
    config_key TEXT PRIMARY KEY REFERENCES config_schema(config_key),
    config_value JSONB NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Initialize with defaults (INSERT ... SELECT from config_schema)
INSERT INTO config_state (config_key, config_value)
SELECT config_key, default_value FROM config_schema;
```

### config_history (Time-Series)

```sql
-- Config history: time-series audit trail
CREATE TABLE config_history (
    timestamp TIMESTAMPTZ NOT NULL,
    config_key TEXT NOT NULL,
    config_value JSONB NOT NULL,
    version INTEGER NOT NULL,
    changed_by TEXT NOT NULL DEFAULT 'system',
    PRIMARY KEY (config_key, timestamp, version)
);

-- Index for time-series queries
CREATE INDEX config_history_key_ts ON config_history (config_key, timestamp DESC);

-- Hypertable for time-series optimization (optional)
SELECT add_hypertable('config_history', 'timestamp');
```

---

## ConfigService API

```python
class ConfigService:
    """Unified config management with validation, history, and rollback."""

    async def set(
        self,
        key: str,
        value: Any,
        changed_by: str = "system",
        validate: bool = True,
    ) -> dict:
        """Set config value with validation and history.

        1. Validate against config_schema (type, range, constraints)
        2. Write to config_state + config_history (transaction)
        3. Publish to topic_config_updates (Kafka)
        4. Return confirmation + new version

        On error: rollback transaction, no Kafka emit.
        """

    async def get(self, key: str, default: Any = None) -> Any:
        """Get current config value (in-memory cache, else DB)."""

    async def get_at(self, key: str, t: datetime) -> Any:
        """Time-travel query: what was value at timestamp T?"""

    async def list(self, category: str | None = None) -> dict[str, Any]:
        """List all current config (optionally filtered by category)."""

    async def revert_key(self, key: str, version: int) -> dict:
        """Revert single key to specific version."""

    async def revert_to_timestamp(self, t: datetime) -> dict:
        """Revert entire system to config at timestamp T."""
```

---

## AlertSignalProcessor (Layer 8)

```python
class AlertSignalProcessor(BaseAgent):
    """Consume events, apply rules, emit alerts.

    Consumes:
    - topic_observable_events (metrics, logs, traces)
    - topic_signal_events (business signals)

    Emits:
    - topic_alert_requests (to AlertingAgent)
    """

    async def _setup(self):
        self._rule_engine = RuleEngine()
        self._config = ConfigService()  # Query alert enable/disable
        self._deduper = Deduplicator()    # Fingerprint-based dedup
        self._aggregator = Aggregator()  # Time-window aggregation
        self._correlator = Correlator()  # Related event grouping

    async def _run(self):
        async for topic, key, payload in self._consumer.messages():
            # 1. Check if alert enabled
            alert_key = f"alert.{payload['alert_type']}.enabled"
            if not await self._config.get(alert_key, False):
                continue

            # 2. Apply rules (dedupe, aggregate, correlate)
            processed = await self._rule_engine.process(payload)

            # 3. Emit to alert_requests topic
            if processed.should_fire():
                await self._producer.publish(topic_alert_requests(), processed.alert())
```

---

## Rule Engine (Moderate Sophistication)

```python
class RuleEngine:
    """Alert rule processing: dedupe, aggregate, correlate, prioritize."""

    def __init__(self):
        self.dedup_window = deque(maxlen=1000)  # Fingerprint → timestamp
        self.aggregate_window = {}  # key → [events]

    async def process(self, event: Event) -> ProcessedEvent:
        # 1. Deduplication (fingerprint hash)
        fingerprint = self._fingerprint(event)
        if fingerprint in self.dedup_window:
            return ProcessedEvent(duplicate=True)

        # 2. Aggregation (5 alerts in 1min = 1 grouped alert)
        agg_key = self._aggregate_key(event)
        self.aggregate_window[agg_key] = self.aggregate_window.get(agg_key, []) + [event]
        if len(self.aggregate_window[agg_key]) >= 5:
            return ProcessedEvent(aggregated=self.aggregate_window.pop(agg_key))

        # 3. Correlation (disk_full + db_slow = related incident)
        correlated = self._correlate(event)

        # 4. Priority queue (CRITICAL cuts line)
        priority = self._priority(event)

        return ProcessedEvent(
            should_fire=True,
            event=event,
            correlated=correlated,
            priority=priority
        )
```

---

## Complexity Decision: B (Moderate) with C-Ready Design

**Alerts are a Signal Processing Problem**, not "alerting tools." Renaissance treats all events (metrics, logs, traces) as time-series features with:
- Information content (entropy: how surprising is this?)
- Noise ratio (most alerts are noise)
- Risk/reward (cost of missing vs cost of false alarm)
- Regime awareness (what's normal changes over time)

### Three Sophistication Levels

| Level | Approach | What You'd Learn | When You Outgrow It |
|-------|----------|------------------|---------------------|
| A (Minimal) | Rule-based with simple thresholds | Rule syntax, basic Kafka flow | Day 1 — too simple |
| **B (Moderate)** | Static thresholds + dedupe + aggregation + correlation | Core patterns: fingerprinting, windows, correlation, priority queues | When you need statistical baselines (months later) |
| C (Full Renaissance) | Z-score anomaly, EWMA trending, regime-aware, learned baselines | Statistical detection, Kalman filters, regime adaptation | Never — endgame |

**Chosen: B (Moderate) with C-ready design.**

### Reuse Analysis

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Throw Away:           ~5%   (YAML rules → code)
Reuse:                 ~80%  (AlertingAgent, Kafka, configs, Prometheus)
New Build:             ~15%  (AlertSignalProcessor, rule engine, DB tables)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**KEEP (~80%):**
- AlertingAgent (Layer 9 dispatcher — Telegram/Discord logic done)
- topic_alert_requests
- BaseAgent._send_alert() API
- telegram_bot_token, discord_webhook_url config
- Prometheus (metrics storage, Grafana queries need it)
- OTel Collector

**ADD (~15%):**
- AlertSignalProcessor (agent)
- topic_observable_events (Kafka)
- RuleEngine interface (B→C evolution plug point)
- alert_config entries in config_state

**CHANGE (~5%):**
- YAML alertmanager rules → Python code (or keep both for flexibility)
- Prometheus→Alertmanager path simplification

### Evolution Path: B → C

The RuleEngine interface enables future statistical sophistication:

```python
class RuleEngine(ABC):
    """Plug point for sophistication evolution."""
    @abstractmethod
    async def process(self, event: Event) -> ProcessedEvent:
        pass

class SimpleRuleEngine(RuleEngine):
    """B (Moderate): dedupe, aggregate, correlate."""
    ...

class StatisticalRuleEngine(RuleEngine):
    """C (Full Renaissance): z-score, EWMA, regime detection."""
    def __init__(self):
        self.z_score_threshold = 3.0
        self.ewma = EWMA(alpha=0.1)
        self.regime_detector = RegimeDetector()

    async def process(self, event: Event) -> ProcessedEvent:
        # Statistical anomaly detection
        z_score = self._z_score(event.metric_value)
        if z_score > self.z_score_threshold:
            return ProcessedEvent(should_fire=True, reason="anomaly")
        # EWMA baseline drift detection
        # Regime change detection
        ...
```

**C techniques (future):**
- Z-score anomaly detection (how many sigma from baseline?)
- EWMA trending (exponentially weighted moving average for baseline drift)
- Regime change detection (what's "normal" just shifted)
- Kalman filters (state estimation for noisy metrics)

---

## Service Integration Pattern

All services subscribe to config updates and hot-reload:

```python
class BaseAgent:
    def __init__(self):
        self._config_cache: dict[str, Any] = {}

    async def _setup(self):
        # Seed config from DB on startup
        self._config_cache = await config_service.list()

        # Subscribe to config updates
        self._config_consumer = KafkaConsumerClient("topic_config_updates")
        asyncio.create_task(self._reload_config_loop())

    async def _reload_config_loop(self):
        async for _topic, _key, payload in self._config_consumer.messages():
            key = payload["config_key"]
            value = payload["config_value"]
            version = payload["version"]
            self._config_cache[key] = value
            self.logger.info("config_reloaded", key=key, version=version)

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get runtime config value (in-memory, hot path)."""
        return self._config_cache.get(key, default)
```

---

## Simple Config API (FastAPI)

```python
# src/api/config.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/config", tags=["config"])

class ConfigSet(BaseModel):
    key: str
    value: Any
    changed_by: str = "admin"

class ConfigRevert(BaseModel):
    key: str
    version: int

@router.post("/")
async def set_config(req: ConfigSet):
    """Set config value with validation."""
    try:
        result = await config_service.set(req.key, req.value, req.changed_by)
        return result
    except ConfigValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/")
async def get_config(key: str | None = None):
    """Get config value(s)."""
    if key:
        return await config_service.get(key)
    return await config_service.list()

@router.post("/revert")
async def revert_config(req: ConfigRevert):
    """Revert config to specific version."""
    return await config_service.revert_key(req.key, req.version)

@router.get("/history")
async def get_config_history(key: str, limit: int = 100):
    """Get config change history."""
    return await config_service.history(key, limit)
```

---

## Migration: What Moves Where

| From | To | Examples | Count |
|------|-----|----------|-------|
| **settings.py runtime params** | `config_state` DB | `REGIME_PROB_MIN`, `SWARM_MIN_CONFIDENCE`, `roll_monitor_*`, regime gates, swarm params | ~15 |
| **Hardcoded `shadow_only`** | Query `shadow_registry` | AI agent shadow mode class attributes | ~8 |
| **Hardcoded `_LAG_THRESHOLDS`** | `config_state` DB | Service lag thresholds in service_auditor_agent.py | ~25 |
| **Alert enable flags** | `config_state` DB | All alert `.enabled` flags | ~20 |
| **ENV vars** | Stay in ENV | `DATABASE_URL`, secrets, IBKR config | ~30 |
| **`shadow_registry` DB** | Keep as-is | Already correct pattern | - |
| **`TIER_I*` plugin lists** | Stay in code | Changes with plugins — correct location | ~130 plugins |
| **`SIGNAL_SCHEMA_VERSION`** | `config_state` DB | Signal format version | 1 |

---

## Default State (Everything OFF)

```sql
-- All alerts OFF by default
UPDATE config_state SET config_value = 'false'
WHERE config_key LIKE 'alert.%.enabled';

-- Runtime params start at current settings.py values
-- Migrated via script that reads defaults and INSERTs
```

---

## What This Enables

| Capability | Foundation Component |
|------------|----------------------|
| Enable/disable alerts without restart | ConfigService + hot-reload |
| Tune regime gates at runtime | ConfigService + Kafka propagation |
| Rollback bad config change | config_history time-series |
| Audit who changed what when | config_history.changed_by |
| Validate config before apply | ConfigSchemaRegistry |
| Add new config keys safely | INSERT into config_schema |
| Time-travel queries | `get_config_at(t)` |
| Correlate related alerts | AlertSignalProcessor aggregation |
| Future: A/B testing | ConfigService + schema versioning |
| Future: Canary deployments | ConfigService + per-service overrides |

---

## Implementation Phases

1. **Phase 1:** Config foundation (DB tables, ConfigService, Kafka propagation)
2. **Phase 2:** Migration of runtime params from settings.py
3. **Phase 3:** AlertSignalProcessor (rule engine, dedupe, aggregate)
4. **Phase 4:** Config API (FastAPI endpoints)
5. **Phase 5:** Dashboard integration (optional)

---

## References

- Renaissance principles: mathematical rigor, time-series state, provable correctness
- Current alerting: `services/alerting_agent.py` (Layer 9 dispatcher)
- Current config: `src/config/settings.py` (~40 tunable params)
- Shadow registry: `shadow_registry` table (already correct pattern)
