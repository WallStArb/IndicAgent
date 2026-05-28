# Config Foundation and Alerting System Design

**Date:** 2026-05-28
**Status:** Design Draft
**Principles:** Renaissance-style — mathematical rigor, provable correctness, time-series thinking

## Executive Summary

Unified config system + alerting infrastructure. All state is time-series data, validated at write time, propagated via Kafka, zero-downtime tuning.

**Core insight:** Alerts are signal processing. Events (metrics, logs, traces) have information content, noise ratio, risk/reward, regime awareness. Process signals to extract meaning, don't just fire on static thresholds.

**Everything OFF by default.**

---

## Architecture

```
ALL EVENTS → KAFKA (unified bus)
          ↓
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         CONFIG FOUNDATION                                            │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  ConfigSchemaRegistry — what keys exist, types, constraints                   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  ConfigService — set/get/revert with validation                              │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Storage: config_state (current), config_history (time-series), config_schema  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Propagation: topic_config_updates → services hot-reload                      │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
          ↓
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         ALERT FOUNDATION                                             │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  AlertSignalProcessor (Layer 8, NEW)                                        │   │
│  │  Consume events → apply rules → emit alerts                                  │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  AlertingAgent (Layer 9, EXISTS)                                             │   │
│  │  CRITICAL → Telegram, HIGH/MEDIUM → Discord                                   │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Three Semantic Config Layers

| Layer | What | Examples | Change Cost | Location |
|-------|------|----------|--------------|----------|
| **INFRASTRUCTURE** | "Where is the system?" | DB URLs, Kafka brokers, secrets | Restart | .env file |
| **STRUCTURE** | "What exists?" | Plugin tiers, DAG order, service definitions | Deploy | Code/YAML |
| **OPERATIONAL** | "How does it behave?" | Feature flags, thresholds, windows | Hot-reload | DB + Kafka |

These layers are orthogonal. Never mix them.

---

## Database Schema

### config_schema (Registry)
```
config_key (PK) | value_type | default_value | min_value | max_value | allowed_values | depends_on | category | version
```
What keys exist, types, constraints, dependencies. Example: `regime.prob_min` (float, 0.0-1.0, category='regime').

### config_state (Current)
```
config_key (PK) | config_value | version | updated_at
```
Fast lookup for runtime queries.

### config_history (Time-Series)
```
timestamp (PK) | config_key (PK) | version (PK) | config_value | changed_by
```
Audit trail, rollback, time-travel queries. Hypertable on `timestamp`.

---

## ConfigService API

```python
class ConfigService:
    async def set(key, value, changed_by="system") -> dict:
        # Validate → write DB → emit Kafka

    async def get(key, default=None) -> Any:
        # In-memory cache, else DB

    async def get_at(key, t: datetime) -> Any:
        # Time-travel query

    async def list(category: str | None = None) -> dict[str, Any]:
        # All current config

    async def revert_key(key, version) -> dict:
        # Rollback single key

    async def revert_to_timestamp(t: datetime) -> dict:
        # Rollback entire system
```

---

## AlertSignalProcessor (Layer 8)

```python
class AlertSignalProcessor(BaseAgent):
    """Consume events, apply rules, emit alerts."""

    async def _setup(self):
        self._rule_engine = RuleEngine()
        self._config = ConfigService()
        self._deduper = Deduplicator()
        self._aggregator = Aggregator()
        self._correlator = Correlator()

    async def _run(self):
        async for topic, key, payload in self._consumer.messages():
            alert_key = f"alert.{payload['alert_type']}.enabled"
            if not await self._config.get(alert_key, False):
                continue

            processed = await self._rule_engine.process(payload)
            if processed.should_fire():
                await self._producer.publish(topic_alert_requests(), processed.alert())
```

---

## Rule Engine (Moderate Sophistication)

```python
class RuleEngine:
    """Dedupe, aggregate, correlate, prioritize."""

    async def process(self, event: Event) -> ProcessedEvent:
        # 1. Fingerprint deduplication
        # 2. Time-window aggregation (5 in 1min = 1 grouped)
        # 3. Correlation (disk_full + db_slow = related incident)
        # 4. Priority queue (CRITICAL cuts line)
```

---

## Complexity Decision: B (Moderate) with C-Ready

| Level | Approach | Learn | Outgrow |
|-------|----------|-------|---------|
| A (Minimal) | Simple thresholds | Rule syntax | Day 1 |
| **B (Moderate)** | Dedupe, aggregate, correlate | Core patterns | Months |
| C (Full Renaissance) | Z-score, EWMA, regime | Statistical detection | Never |

**Chosen: B with C-ready RuleEngine interface.**

### Reuse Analysis

```
Throw Away:   ~5%  (YAML → code)
Reuse:        ~80% (AlertingAgent, Kafka, configs, Prometheus)
New Build:    ~15% (AlertSignalProcessor, rule engine, DB tables)
```

### Components: KEEP / ADD / CHANGE

**KEEP (~80%):**
| Component | Why |
|-----------|-----|
| AlertingAgent | Dispatcher (Layer 9) — Telegram/Discord logic done |
| topic_alert_requests | Final alert bus |
| BaseAgent._send_alert() | API for agents to publish alerts |
| telegram_bot_token, discord_webhook_url | Config already works |
| Prometheus | Metrics storage, Grafana queries need it |
| OTel Collector | Telemetry collection |

**ADD (~15%):**
| Component | Purpose |
|-----------|---------|
| AlertSignalProcessor (agent) | Consumes events, applies rules, dedupes, aggregates |
| topic_observable_events (Kafka) | Raw metrics/logs/traces feed |
| RuleEngine interface | Plug point for B→C evolution |
| config_state alert entries | Feature flags (which alerts ON/OFF, targets) |

**CHANGE (~5%):**
| Current | Change Path |
|---------|-------------|
| alertmanager-rules.yml | Migrate to Python OR keep both for flexibility |
| Prometheus → Alertmanager | Simplify — Prometheus metrics-only, alerting is our pipeline |

### Refactoring & Cleanup

| File | Change | Why |
|------|--------|-----|
| src/config/settings.py | Remove ~15 runtime params (move to DB) | Don't mix config layers |
| services/service_auditor_agent.py | Remove hardcoded _LAG_THRESHOLDS (~25) | Query config_state instead |
| src/intelligence/ai/*_agent.py | Remove hardcoded shadow_only class attrs | Query shadow_registry instead |
| production/alertmanager-rules.yml | Delete or simplify | Alerting moves to AlertSignalProcessor |
| services/alerting_agent.py | **No change** | Layer 9 dispatcher is correct |

### Evolution Path: B → C

```python
class RuleEngine(ABC):
    @abstractmethod
    async def process(self, event: Event) -> ProcessedEvent:
        pass

class SimpleRuleEngine(RuleEngine):
    """B: dedupe, aggregate, correlate."""

class StatisticalRuleEngine(RuleEngine):
    """C: z-score, EWMA, regime detection, Kalman filters."""
```

---

## Service Integration Pattern

All services subscribe to config updates:

```python
class BaseAgent:
    async def _setup(self):
        self._config_cache = await config_service.list()
        self._config_consumer = KafkaConsumerClient("topic_config_updates")
        asyncio.create_task(self._reload_config_loop())

    async def _reload_config_loop(self):
        async for _topic, _key, payload in self._config_consumer.messages():
            self._config_cache[payload["config_key"]] = payload["config_value"]

    def get_config(self, key, default=None):
        return self._config_cache.get(key, default)
```

---

## Config API (FastAPI)

```python
router = APIRouter(prefix="/config", tags=["config"])

@router.post("/")  # Set config value
@router.get("/")   # Get config value(s)
@router.post("/revert")  # Revert to version
@router.get("/history")  # Change history
```

---

## Migration: What Moves Where

| From | To | Examples | Count |
|------|-----|----------|-------|
| settings.py runtime params | config_state DB | REGIME_PROB_MIN, SWARM_MIN_CONFIDENCE, regime gates, swarm params | ~15 |
| Hardcoded shadow_only | Query shadow_registry | AI agent shadow mode | ~8 |
| Hardcoded _LAG_THRESHOLDS | config_state DB | Service lag thresholds | ~25 |
| Alert enable flags | config_state DB | All alert .enabled flags | ~20 |
| ENV vars | Stay in ENV | DATABASE_URL, secrets | ~30 |
| shadow_registry DB | Keep as-is | Already correct | - |
| TIER_I* plugin lists | Stay in code | Changes with plugins | ~130 |

---

## Default State

All alerts OFF by default. Runtime params seeded from current settings.py values.

---

## Implementation Phases

1. Config foundation (DB tables, ConfigService, Kafka propagation)
2. Migration of runtime params from settings.py
3. AlertSignalProcessor (rule engine, dedupe, aggregate)
4. Config API (FastAPI endpoints)
5. Dashboard integration (optional)

---

## References

- Current alerting: `services/alerting_agent.py` (Layer 9 dispatcher)
- Current config: `src/config/settings.py` (~40 tunable params)
- Shadow registry: `shadow_registry` table (correct pattern already)
