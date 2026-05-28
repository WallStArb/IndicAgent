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

**Note on layers:** IndicAgent has 7-tier plugin pipeline (I1–I8) for intelligence computation. AlertSignalProcessor (Layer 8) and AlertingAgent (Layer 9) are service layers, not plugin tiers. Different taxonomy.

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
│  │  AlertingAgent (Layer 9, EXISTS — services/alerting_agent.py)                │   │
│  │  Dispatcher: CRITICAL → Telegram, HIGH/MEDIUM → Discord                      │   │
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
config_key (PK) | value_type | default_value | min_value | max_value | allowed_values |
depends_on | category | json_schema | unit | is_secret | risk_level | owner | version
```

**Enhanced fields:**
- `json_schema` — Structured validation for complex types
- `unit` — Unit for numeric values (percent, seconds, gb, etc.)
- `is_secret` — Never log/trace actual value
- `risk_level` — (low/medium/critical) controls approval requirements
- `owner` — Team responsible for this config

### config_state (Current)
```
config_key (PK) | config_value | version | updated_at
```
Fast lookup for runtime queries. Optimistic concurrency via `version`.

### config_history (Time-Series)
```
timestamp (PK) | config_key (PK) | version (PK) | config_value | changed_by | reason
```
Audit trail, rollback, time-travel queries. Hypertable on `timestamp`.

### config_outbox (Outbox Pattern)
```
id (PK) | config_key | config_value | version | changed_at | status | created_at
```
Transactional outbox for safe Kafka propagation. Status: pending/published/failed.

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
    async def set(
        key, value, changed_by="system", expected_version=None, reason=None
    ) -> ConfigChange:
        """Set config with validation, version check, transactional outbox.

        1. Validate against config_schema (type, range, constraints)
        2. Optimistic concurrency check (expected_version if provided)
        3. Write transaction: config_history + config_state + config_outbox
        4. Kafka dispatcher publishes outbox rows (separate process)
        5. Return ConfigChange with new version

        On validation error: raise ConfigValidationError
        On version conflict: raise ConfigVersionConflict
        On DB error: rollback, no Kafka emit
        """

    async def get(key, default=None) -> Any:
        # In-memory cache (hot), else DB (cold)

    async def get_at(key, t: datetime) -> Any:
        # Time-travel query

    async def list(category: str | None = None) -> dict[str, Any]:
        # All current config

    async def revert_key(key, version, changed_by="system", reason=None) -> dict:
        # Rollback single key with validation

    async def preview_revert_to_timestamp(t: datetime) -> dict:
        # Show what would change without applying

    async def revert_keys(keys, t: datetime, changed_by="system", reason=None) -> dict:
        # Rollback specific keys with dependency validation
```

---

## Transactional Outbox Pattern

Config updates use outbox pattern for safe DB→Kafka propagation:

```
ConfigService.set() transaction:
  1. INSERT config_history
  2. UPSERT config_state
  3. INSERT config_outbox (id, config_key, config_value, version, changed_at, status=pending)
  COMMIT

OutboxDispatcher (separate process):
  SELECT config_outbox WHERE status=pending
  Publish to topic_config_updates
  UPDATE config_outbox SET status=published ON SUCCESS
  UPDATE config_outbox SET status=failed ON FAILURE
```

Guarantees:
- DB commit before Kafka publish (no lost updates)
- Kafka publish failure visible in outbox table
- Can retry failed publishes
- Ordering per config_key maintained

---

## Optimistic Concurrency

Prevent silent overwrites from concurrent writes:

```python
# Client A and B both read regime.prob_min = 0.30 (version 5)
# Client A: set("regime.prob_min", 0.35, expected_version=5) → SUCCESS (version 6)
# Client B: set("regime.prob_min", 0.40, expected_version=5) → CONFLICT (now version 6)

# Client B must re-read and try again with expected_version=6
```

`set()` without `expected_version` still works (last write wins), but API requires explicit opt-in.

---

## Security Model

Config changes can alter thresholds, feature flags, alert routing. Minimum controls:

**Authentication:**
- FastAPI endpoints require auth (Bearer token or mTLS)
- CLI/API calls identify caller (changed_by)

**Authorization:**
- Read-only vs write permission
- Per-category write permission (regime, swarm, alert, roll)
- High-risk keys require approval (risk_level=critical)

**Audit:**
- All changes logged with changed_by, timestamp, reason, old_value, new_value
- Sensitive values redacted (is_secret=true keys)

**Secret Redaction:**
```python
REDACTED = "**REDACTED**"  # Placeholder in logs/traces

# config_schema is_secret=true keys never logged/metric'd with actual value
# Examples: telegram_bot_token, discord_webhook_url, API keys
```

---

## Alert Rule Configuration

**Split between code and config:**

| Component | Location | Examples |
|-----------|----------|----------|
| Rule code | Versioned Python modules | Deduplicator, Aggregator, Correlator classes |
| Rule parameters | config_state DB | thresholds, windows, severities, targets |
| Rule metadata | config_schema DB | rule_type, risk_level, owner |

Rule code changes require deployment. Rule parameter changes are hot-reload.

**Example:**
```python
# Rule code (versioned): services/alert_rules/disk_space_rules.py
class DiskSpaceRule:
    severity = "CRITICAL"
    check_fn = lambda df_free_gb: df_free_gb < threshold

# Rule config (hot-reload): config_state
alert.disk_space.threshold_gb = 10.0
alert.disk_space.enabled = true
```

---

## Safer Revert Operations

**Dangerous:** `revert_to_timestamp(t)` — rolls back entire system, can violate dependencies.

**Safer operations:**
```python
# Preview first (no write)
config_service.preview_revert_to_timestamp(t)
# → Returns: {keys: [...], affected_services: [...], risks: [...]}

# Scoped revert with validation
config_service.revert_keys(["regime.prob_min", "swarm.min_confidence"], t)
# → Validates dependencies, only rolls back specified keys

# Category-scoped revert
config_service.revert_category("regime", t)
# → Rolls back all config with category='regime'
```

Revert requires:
- Dependency validation (config_schema.depends_on)
- Approval for high-risk keys (risk_level=critical)
- Dry-run by default (preview_required=true)

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

### Components: KEEP / REMOVE

**KEEP:** AlertingAgent, topic_alert_requests, BaseAgent._send_alert(), telegram/discord config, Prometheus, OTel Collector.

**REMOVE:** application-level alertmanager-rules.yml (migrate to AlertSignalProcessor).
**KEEP:** infra-level alertmanager-rules.yml (disk, service down, memory — stay in Prometheus/Alertmanager).

**Scope split:**
- Prometheus/Alertmanager → Infrastructure alerts (service health, resources)
- AlertSignalProcessor → Intelligence/Application alerts (regime, signals, pipeline)

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

## Kafka Message Schemas

### topic_config_updates (Compacted)

```json
{
  "config_key": "regime.prob_min",
  "config_value": "0.35",
  "version": 6,
  "changed_by": "brandon",
  "changed_at": "2026-05-28T20:00:00Z",
  "reason": "reduce false positives",
  "redacted": false,
  "correlation_id": "uuid-xxx"
}
```

**Partition key:** `config_key` (ensures ordering per key)
**Retention:** compacted (only latest value per key needed)
**Schema version:** header `X-Schema-Version: 1`

### topic_alert_requests

```json
{
  "alert_id": "disk-space-critical-001",
  "alert_type": "disk_space_critical",
  "severity": "CRITICAL",
  "timestamp": "2026-05-28T20:00:00Z",
  "payload": {
    "disk_free_gb": 2.5,
    "threshold_gb": 10.0
  },
  "correlated_events": ["db_slow_001"],
  "rule_applied": "disk_space_threshold",
  "targets": ["telegram"]
}
```

---

## Failure Modes

**ConfigService unavailable:**
- Services use last-known-good cached config
- Emit `config_service_unreachable_total` metric
- Retry with exponential backoff
- After N failures, enter degraded mode (log warnings)

**Kafka unavailable:**
- ConfigService writes succeed, outbox status=pending
- OutboxDispatcher retries with backoff
- Services won't receive updates until Kafka recovers
- Emit `kafka_publish_failed_total{key}` metric

**Stale config detection:**
- Services track `config_last_reload_timestamp_seconds`
- ConfigConsumer emits `config_consumer_lag_seconds` (offset lag)
- If lag > threshold OR reload > 10min, emit warning
- Manual intervention: restart service to force DB snapshot reload

**Fail-closed vs fail-open:**
- Critical safety keys (regime gates, position limits): fail-closed (disable feature if config stale)
- Tunable parameters (thresholds): fail-open (use last-known-good)

---

## Config Consumer Resilience

BaseAgent config reload pattern:

```python
class BaseAgent:
    async def _setup(self):
        # 1. Load DB snapshot on startup (authoritative seed)
        self._config_cache = await config_service.list()
        self._config_version = {}  # Track per-key version

        # 2. Subscribe to compacted topic
        self._config_consumer = KafkaConsumerClient(
            "topic_config_updates",
            group_id=f"{agent_name}-config",
            enable_auto_commit=False,  # Manual commit after processing
        )

        asyncio.create_task(self._reload_config_loop())

    async def _reload_config_loop(self):
        async for _topic, _key, payload in self._config_consumer.messages():
            key = payload["config_key"]
            new_version = payload["version"]
            current_version = self._config_version.get(key, 0)

            # Ignore stale messages (compacting can send older)
            if new_version <= current_version:
                continue

            # Update cache
            self._config_cache[key] = payload["config_value"]
            self._config_version[key] = new_version

            # Emit metric
            config_reload_total.labels(agent=self.name, success="true").inc()

            # Commit after processing
            await self._config_consumer.commit()

        # Periodic reconciliation (catch missed messages)
        asyncio.create_task(self._reconcile_config_loop())

    async def _reconcile_config_loop(self):
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            current = await config_service.list()
            stale_keys = [
                k for k, v in current.items()
                if self._config_cache.get(k) != v
            ]
            if stale_keys:
                logger.warning("config_stale", keys=stale_keys)
                # Reload from DB if drift detected
```

---

## Service Integration Pattern

**Note:** `_setup()` composition: services that already override `_setup()` must call `await super()._setup()` OR use the config mixin pattern:

```python
# Option 1: Call super()
class MyAgent(BaseAgent):
    async def _setup(self):
        await super()._setup()  # Gets config integration
        # Custom setup here...

# Option 2: Mixin (if _setup override is complex)
class ConfigMixin:
    async def _setup_config(self):
        self._config_cache = await config_service.list()
        # ... config setup

class MyAgent(ConfigMixin, BaseAgent):
    async def _setup(self):
        await self._setup_config()  # Explicit call
        # Custom setup...
```

---

## AlertSignalProcessor Scaling

**Bottleneck risk:** Single processor consuming all events.

**Mitigations:**

1. **Topic partitioning:** Partition `topic_observable_events` by event_type or source
2. **Multiple instances:** Run N instances of AlertSignalProcessor, each consumes partition subset
3. **State externalization:** Dedupe window, aggregate state in Redis or TimescaleDB (not in-memory)
4. **Filtering:** Don't route all metrics through processor — only alert-relevant events
5. **Backpressure:** If processing lag > threshold, emit metric, scale up or drop low-priority

**Target:** < 100ms end-to-end latency (event receipt → alert emit)

---

## Alerting Scope Split

**Infrastructure alerts** (keep Prometheus/Alertmanager):
- Service down, disk full, memory high, Kafka unavailable
- Scrape failures, DB connection issues
- Simple thresholds on infra metrics

**Intelligence/Application alerts** (AlertSignalProcessor):
- Regime shifts, signal quality drops, pipeline stalls
- Correlated incidents (disk full + DB slow)
- Domain-aware events (trading signals, ML model drift)

**Coexistence:** Both systems run. Prometheus handles infra, AlertSignalProcessor handles app.

---

## Implementation Phases

1. Config foundation (DB tables including outbox, ConfigService with outbox dispatcher, Kafka propagation, observability)
2. Migration CLI (minimal admin interface for seed + validate before full API)
3. Migration of runtime params from settings.py
4. AlertSignalProcessor (rule engine, dedupe, aggregate, observability)
5. Config API (FastAPI endpoints with auth)

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

## Observability Requirements

Renaissance principle: if you build a signal processor, measure its output. Config changes and alerts are signals — observe them.

### Config Observability (ConfigService + BaseAgent)

**Metrics:**
- `config_reload_total{agent, success}` — every hot-reload event
- `config_validation_failed_total{key, reason}` — rejected changes
- `config_set_total{key, changed_by}` — config change requests (API)

**Tracing:**
- Span on every ConfigService.set() call (key, old_value, new_value, changed_by)
- Span on BaseAgent config reload (agent, keys_reloaded)

**Logging:**
- ConfigService.set() → structlog with key, value, changed_by, validation_result
- BaseAgent reload → log which keys changed, version bump
- **Redaction:** is_secret keys log "**REDACTED**" instead of actual value

**Redaction Policy:**
- Never emit secret values in logs, traces, or metrics
- config_schema.is_secret=true keys redacted everywhere
- Traces: old_value/new_value replaced with "**REDACTED**" for secrets
- Metrics: don't tag with secret values (no cardinality blowout)

### Alert Observability (AlertSignalProcessor + AlertingAgent)

**Metrics:**
- `alert_emitted_total{severity, alert_type, target}` — firing rate per severity/type
- `alert_suppressed_total{reason}` — dedupe, aggregation, correlation working
- `alert_processing_latency_seconds{alert_type}` — event → alert latency histogram
- `rule_engine_evaluation_duration_seconds{rule_type}` — per-rule timing

**Tracing:**
- Span on AlertSignalProcessor._run() (event_type, rule_applied, should_fire)
- Span on AlertingAgent dispatch (severity, target, success)

**Logging:**
- AlertSignalProcessor → event processed, rule result, fire/suppress with reason
- AlertingAgent → dispatch result, target response

### BaseAgent Updates

Update BaseAgent._reload_config_loop():
- Emit `config_reload_total` metric on every message
- Log config change event
- Update `agent_last_message_timestamp_seconds` (already exists)

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

## Technical Debt Cleanup

After new system is in place, remove old patterns:

**Config & Feature Flags:**
- `src/config/settings.py` — Delete ~15 runtime params (REGIME_PROB_MIN, SWARM_MIN_CONFIDENCE, regime gates, swarm params, etc.)
- `services/service_auditor_agent.py` — Delete `_LAG_THRESHOLDS` dict (~25 entries)
- `src/intelligence/ai/*_agent.py` — Delete hardcoded `shadow_only = True` class attrs (~8 agents)

**Alerting:**
- `production/alertmanager-rules.yml` — Delete or simplify to metrics-only
- Any Prometheus Alertmanager integration — Simplify to metrics scrape only

**Observability:**
- Review hardcoded thresholds in services (grep for `THRESHOLD`, `LIMIT`, `MAX_`) — migrate to config_state if runtime-tunable

---

## Default State

All alerts OFF by default. Runtime params seeded from current settings.py values.

---

## Implementation Phases

1. Config foundation (DB tables, ConfigService, Kafka propagation, observability)
2. Migration of runtime params from settings.py
3. AlertSignalProcessor (rule engine, dedupe, aggregate, observability)
4. Config API (FastAPI endpoints)

---

## References

- Current alerting: `services/alerting_agent.py` (Layer 9 dispatcher)
- Current config: `src/config/settings.py` (~40 tunable params)
- Shadow registry: `shadow_registry` table (correct pattern already)
