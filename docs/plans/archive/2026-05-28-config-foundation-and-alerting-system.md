# Config Foundation and Self-Healing Engine Design

**Date:** 2026-05-28
**Status:** Design Approved (Renaissance Review)
**Principles:** Renaissance-style — mathematical rigor, provable correctness, time-series thinking, control theory

## Executive Summary

Unified config system + self-healing engine. All state is time-series data, validated at write time, propagated via Kafka, zero-downtime tuning. Self-healing as control system (sensor → setpoint → actuator → feedback).

**Core insight:** Alerts are control system outputs. Events (metrics) have information content. Process signals with feedback loops to extract meaning. Don't just alert — remediate.

**Everything OFF by default.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 1: Config Foundation                                 │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  ConfigService (FastAPI + Python)                                            │   │
│  │  set(key, value) → validate → write DB + outbox → return                    │   │
│  │  get(key) → cache → DB fallback                                              │   │
│  │  revert(key, version) → time-travel query → apply                           │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼ (DB + outbox)                            │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  TimescaleDB                                                                 │   │
│  │  config_state (current), config_history (time-series),                       │   │
│  │  config_schema (registry), config_outbox (pending publishes)                 │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼ (OutboxDispatcher)                      │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Kafka: topic_config_updates (compacted)                                    │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼ (services subscribe)
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                      ALL SERVICES (BaseAgent pattern)                               │
│  • On startup: load config_state snapshot                                          │
│  • On Kafka message: hot-reload affected keys                                     │
│  • get_config(key): read from in-memory cache                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           LAYER 2: Self-Healing Engine                               │
│                                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Webhook Receiver (FastAPI)                                                 │   │
│  │  POST /webhook/alertmanager → authenticate → validate → 200 OK             │   │
│  │  (immediate return, processing async)                                       │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  Remediation Engine (async worker)                                           │   │
│  │  • Dequeue pending remediations                                             │   │
│  │  • Lookup strategy (static mapping: alert → action)                         │   │
│  │  • Execute action (delete logs, restart, flush)                             │   │
│  │  • Measure post-state (did it work?)                                        │   │
│  │  • Update ledger (success/failure)                                          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐   │
│  │  TimescaleDB: remediation_ledger (hypertable)                               │   │
│  │  timestamp, alert_id, state_variable, pre_value, post_value,                │   │
│  │  action, outcome, duration_ms, success_rate tracking                        │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
┌───────────────────────────────────────┐     ┌──────────────────────────────────────┐
│  Success (Fixed)                      │     │  Failure (Escalate)                  │
│  • Log outcome                        │     │  • Publish to topic_alert_requests    │
│  • Emit metrics (success_total)      │     │  • AlertingAgent → Signal/Telegram   │
│  • Update success_rate                │     │  • Human intervention needed          │
└───────────────────────────────────────┘     └──────────────────────────────────────┘
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

## Config As Time-Series State (Renaissance Principle)

**"Everything changes over time. State is time-series."**

- Market data = time-series (price, volume)
- Positions = time-series (entry, exit, PnL)
- Signals = time-series (signal_ledger)
- **Config = time-series** (thresholds, flags, enable/disable)

**Why store config differently than signals?**

You don't. Same database (TimescaleDB), same query patterns, same audit trail.

**Example:** Did a config change cause a signal quality drop?

```sql
-- Correlate config changes with signal quality
SELECT h.timestamp, h.config_key, h.config_value, h.changed_by
FROM config_history h
WHERE h.timestamp >= '2026-05-27' AND h.timestamp < '2026-05-28'
  AND h.config_key LIKE 'regime.%'
ORDER BY h.timestamp;

-- Compare with intelligence_features timestamps
-- "Ah, regime.prob_min changed from 0.30 to 0.50 at 14:30.
--  Quality dropped at 15:00. Correlation!"
```

---

## Database Schema

### Config Tables

```sql
-- config_schema: Registry of valid keys
CREATE TABLE config_schema (
  config_key TEXT PRIMARY KEY,
  value_type TEXT NOT NULL,              -- 'string', 'int', 'float', 'bool', 'json'
  default_value TEXT,
  min_value FLOAT,
  max_value FLOAT,
  allowed_values TEXT[],                  -- for enum-like types
  depends_on TEXT,                       -- other keys this depends on
  category TEXT NOT NULL,                 -- 'INFRA', 'STRUCT', 'OPS'
  is_secret BOOLEAN DEFAULT FALSE,
  version INT DEFAULT 1,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- config_state: Current values (fast lookup)
CREATE TABLE config_state (
  config_key TEXT PRIMARY KEY,
  config_value TEXT NOT NULL,
  version INT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- config_history: Time-series audit trail
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

-- Indexes for time-travel queries
CREATE INDEX idx_config_history_key_time ON config_history (config_key, timestamp DESC);
CREATE INDEX idx_config_history_user ON config_history (changed_by, timestamp DESC);

-- Retention and compression policies
SELECT add_retention_policy('config_history', INTERVAL '1 year');
SELECT add_compression_policy('config_history', INTERVAL '7 days');

-- config_outbox: Transactional outbox for Kafka
CREATE TABLE config_outbox (
  id BIGSERIAL PRIMARY KEY,
  config_key TEXT NOT NULL,
  config_value TEXT NOT NULL,
  version INT NOT NULL,
  changed_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT DEFAULT 'pending',  -- 'pending', 'published', 'failed'
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_outbox_pending ON config_outbox (status) WHERE status = 'pending';
```

---

### Remediation Ledger

```sql
-- remediation_ledger: All remediation attempts (time-series)
CREATE TABLE remediation_ledger (
  timestamp TIMESTAMPTZ NOT NULL,
  remediation_id TEXT NOT NULL,
  alert_id TEXT NOT NULL,                  -- from Alertmanager
  state_variable TEXT NOT NULL,           -- 'disk_usage', 'consumer_lag', etc.
  pre_value FLOAT,                         -- state before action
  post_value FLOAT,                        -- state after action (NULL if failed)
  target_value FLOAT,                      -- setpoint we're aiming for
  action TEXT NOT NULL,                    -- 'delete_old_logs', 'restart_consumer', etc.
  outcome TEXT NOT NULL,                   -- 'success', 'failed', 'timeout'
  duration_ms INT,
  error_message TEXT,
  changed_by TEXT NOT NULL,                -- 'system' or 'admin'
  reason TEXT,
  PRIMARY KEY (timestamp, remediation_id)
);
SELECT create_hypertable('remediation_ledger', 'timestamp');

-- Index for alert correlation
CREATE INDEX idx_remediation_alert ON remediation_ledger (alert_id, timestamp);

-- Retention and compression policies
SELECT add_retention_policy('remediation_ledger', INTERVAL '90 days');
SELECT add_compression_policy('remediation_ledger', INTERVAL '7 days');

-- Success rate materialized view (refresh periodically)
CREATE MATERIALIZED VIEW remediation_success_rates AS
SELECT
  action,
  COUNT(*) AS attempt_count,
  SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count,
  SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END)::FLOAT / COUNT(*) AS success_rate
FROM remediation_ledger
WHERE timestamp > NOW() - INTERVAL '30 days'
GROUP BY action;
```

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
        4. Return ConfigChange with new version

        On validation error: raise ConfigValidationError
        On version conflict: raise ConfigVersionConflict
        On DB error: rollback, no Kafka emit (outbox not yet published)
        """

    async def get(key, default=None) -> Any:
        # In-memory cache (hot), else DB (cold)

    async def get_at(key, t: datetime) -> Any:
        # Time-travel query: SELECT ... WHERE config_key = $1 AND timestamp < $2

    async def list(category: str | None = None) -> dict[str, Any]:
        # All current config (from cache or DB)

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

**Minimum viable controls:**

**Authentication:**
- FastAPI endpoints require Bearer token
- CLI/API calls identify caller (changed_by)
- Webhook requires shared secret (X-Alertmanager-Signature)

**Audit:**
- All changes logged with changed_by, timestamp, reason
- Sensitive values redacted (is_secret=true keys)

**Secret Redaction:**
```python
REDACTED = "**REDACTED**"

# is_secret keys never logged with actual value
# Examples: telegram_bot_token, discord_webhook_url
```

**Future:** Per-category permissions, approval flows for high-risk keys.

---

## Self-Healing Engine (Control Theory Approach)

Renaissance principle: **Self-healing is a control system, not rule execution.**

```
┌─────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Sensor  │ →  │ Setpoint │ →  │ Error    │ →  │ Actuator │ →  │ Process  │
│ (measure)│   │ (target) │    │ (diff)   │    │ (action) │    │ (system) │
└─────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                                                                    │
     └────────────────────────────────────────────────────────────────────┘
                           FEEDBACK (measure again)
```

**Every remediation must:**
1. Measure current state (pre_value)
2. Compare to setpoint (threshold)
3. Execute action
4. Measure post-state (confirmation)
5. Record outcome (success/failure)
6. Track success rate (auto-disable if < 80%)

---

## Webhook Contract (Alertmanager Integration)

**Request (from Alertmanager):**
```json
{
  "alert_id": "uuid-v4",
  "fired_at": "2026-05-28T...Z",
  "severity": "CRITICAL",
  "state_variable": "disk_usage",
  "current_value": 85.2,
  "threshold": 80.0,
  "labels": {
    "hostname": "prod-1",
    "mountpoint": "/var/log"
  }
}
```

**Response (to Alertmanager):**
```json
{
  "remediation_id": "uuid-v4",
  "status": "ACCEPTED",
  "estimated_duration_ms": 5000
}
```

**Webhook guarantees:**
- Idempotency: `alert_id` prevents double-execution
- Async processing: Accept request → queue → process
- Persistence first: Write to ledger before acting
- Timeout protection: Max 30s per remediation
- Circuit breaker: Pause if >50% failures in 5min
- Authentication: Shared secret in header

---

## Remediation Strategies (Phase 1: Conservative)

Static mapping, low-risk actions only:

```python
REMEDIATION_STRATEGIES = {
    "disk_usage_high": {
        "action": "delete_old_logs",
        "threshold": 80.0,
        "execute": delete_logs_older_than(days=7),
        "max_attempts_per_hour": 3,
        "timeout_seconds": 30,
    },
    "consumer_lag_high": {
        "action": "restart_consumer",
        "threshold": 1000,
        "execute": systemctl_restart(service),
        "max_attempts_per_hour": 2,
        "timeout_seconds": 60,
    },
    "db_pool_exhausted": {
        "action": "flush_connection_pool",
        "threshold": 90.0,
        "execute": flush_pool_connections(),
        "max_attempts_per_hour": 5,
        "timeout_seconds": 10,
    },
}
```

**Evolution path:** Start simple, measure success rates, add sophistication only when data proves it's needed.

---

## Self-Healing API

```python
router = APIRouter(prefix="/self-heal", tags=["self-healing"])

# Alertmanager webhook
POST /self-heal/webhook/alertmanager
  Headers: X-Alertmanager-Signature (authentication)
  Body: { alert_id, fired_at, severity, state_variable, current_value, labels }
  Response: { remediation_id, status, estimated_duration_ms }

# Manual remediation trigger
POST /self-heal/remediate
  Body: { state_variable, action, changed_by }
  Response: { remediation_id, status }

# Get remediation history
GET /self-heal/history?state_variable=disk_usage
  Response: [{ timestamp, action, outcome, duration_ms }]

# Get success rates
GET /self-heal/success-rates
  Response: [{ action, success_rate, attempt_count }]
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

---

## Alerting Scope Split

**Infrastructure alerts** (Prometheus/Alertmanager → SelfHealingEngine):
- Service down, disk full, memory high, Kafka unavailable
- SelfHealingEngine attempts remediation first
- If remediation fails → escalate to AlertingAgent

**Intelligence/Application alerts** (direct to AlertingAgent):
- Regime shifts, signal quality drops, pipeline stalls
- No remediation (these are business events, not system health)

**Coexistence:** Both paths exist. SelfHealingEngine handles infra remediation. AlertingAgent handles escalation and app alerts.

---

## Failure Modes

**ConfigService down:** Services use last-known-good cached config.

**Kafka down:** Config writes succeed, outbox status=pending. OutboxDispatcher retries when Kafka recovers.

**Stale detection:** Services emit `config_last_reload_timestamp_seconds`. If > 10min, emit warning.

**Fail-closed vs fail-open:**
- Safety keys (regime gates): fail-closed (disable if config stale)
- Tunable parameters (thresholds): fail-open (use last-known-good)

---

## Config Consumer Pattern

```python
class BaseAgent:
    async def _setup(self):
        # Load DB snapshot on startup
        self._config_cache = await config_service.list()

        # Subscribe to config updates
        self._config_consumer = KafkaConsumerClient("topic_config_updates")
        asyncio.create_task(self._reload_config_loop())

    async def _reload_config_loop(self):
        async for _topic, _key, payload in self._config_consumer.messages():
            key = payload["config_key"]
            value = payload["config_value"]
            self._config_cache[key] = value
            config_reload_total.labels(agent=self.name).inc()

    def get_config(self, key, default=None):
        return self._config_cache.get(key, default)
```

**Future:** Periodic reconciliation, lag metrics, stale detection.

---

## Config Migration

**What moves from `settings.py` to `config_state`:**

| From | To | Example | Count |
|------|-----|----------|-------|
| `REGIME_PROB_MIN = 0.30` | `regime.prob_min` | Runtime params | ~15 |
| `SWARM_MIN_CONFIDENCE = 0.70` | `swarm.min_confidence` | Thresholds | ~8 |
| `_LAG_THRESHOLDS = {...}` | `alert.lag.*` | Service thresholds | ~25 |
| Hardcoded `shadow_only = True` | `ai.agent.shadow_mode` | Feature flags | ~8 |
| ENV vars (`DATABASE_URL`) | Stay in ENV | Infra (never runtime) | ~30 |

---

## Alertmanager Configuration

```yaml
# /etc/alertmanager/alertmanager.yml
receivers:
  - name: 'indicagent-webhook'
    webhook_configs:
      - url: 'http://localhost:8000/self-heal/webhook/alertmanager'
        send_resolved: true
        http_config:
          bearer_token: {SHARED_SECRET}

route:
  receiver: 'indicagent-webhook'
  group_by: ['alertname', 'state_variable']
  group_wait: 10s
  repeat_interval: 1h
```

---

## Observability Requirements

Renaissance principle: **"If you can't measure it, you don't have it."**

### Config Observability

**Metrics:**
```python
config_set_total{key, changed_by, outcome}           # every set() attempt
config_validation_failed_total{key, reason}         # rejected writes
config_revert_total{key, changed_by, outcome}       # revert operations
config_outbox_pending                               # gauge: pending outbox rows
config_outbox_publish_latency_seconds                # histogram: outbox → Kafka time
config_reload_total{agent, success}                 # every hot-reload event
```

**Traces:**
- Span on ConfigService.set() (key, old_value, new_value, changed_by, validation_result)
- Span on BaseAgent.config_reload (agent, keys_reloaded, version)

**Logging:**
- ConfigService.set() → structlog with key, value, changed_by, validation_result
- BaseAgent reload → log which keys changed, version bump
- **Redaction:** is_secret keys log "**REDACTED**" instead of actual value

---

### Self-Healing Observability

**Metrics:**
```python
remediation_attempt_total{state_variable, action}                    # every attempt
remediation_success_total{state_variable, action, outcome}           # success/fail/timeout
remediation_duration_seconds{state_variable, action}                # histogram
remediation_success_rate{action}                                     # gauge (from materialized view)
webhook_received_total{severity}                                    # Alertmanager webhooks
webhook_validation_failed_total{reason}                             # auth failures
```

**Traces:**
- Span on Remediation.execute (remediation_id, state_variable, action, pre_value, post_value, outcome, duration_ms)

**Logging:**
- remediation.started: remediation_id=xxx action=delete_old_logs pre_value=85.2
- remediation.completed: remediation_id=xxx action=delete_old_logs post_value=42.1 outcome=success duration_ms=5230
- remediation.failed: remediation_id=xxx action=delete_old_logs error=permission_denied escalating=true

---

## Implementation Phases

1. **Phase 109.1** — Config foundation (DB tables, ConfigService, OutboxDispatcher, Kafka propagation, observability)
2. **Phase 109.2** — BaseAgent config reload pattern integration
3. **Phase 109.3** — SelfHealingEngine (webhook, remediation engine, ledger)
4. **Phase 109.4** — Alertmanager webhook configuration
5. **Phase 109.5** — Migration of runtime params from settings.py

---

## Technical Debt Cleanup

After new system is in place, remove old patterns:

**Config & Feature Flags:**
- `src/config/settings.py` — Delete ~15 runtime params (REGIME_PROB_MIN, SWARM_MIN_CONFIDENCE, regime gates, swarm params, etc.)
- `services/service_auditor_agent.py` — Delete `_LAG_THRESHOLDS` dict (~25 entries)
- `src/intelligence/ai/*_agent.py` — Delete hardcoded `shadow_only = True` class attrs (~8 agents)

---

## Default State

All alerts OFF by default. Runtime params seeded from current settings.py values.

---

## Renaissance Design Rationale

**Mathematical rigor:** Control theory approach to self-healing (sensor → setpoint → actuator → feedback). Prove it worked (measure pre/post state).

**Time-series thinking:** Config as time-series state. Same database, same query patterns as signals. Complete audit trail.

**Separation of concerns:** Config (DB) → Propagation (Kafka) → Consumption (services). Detection (Prometheus) → Remediation (IndicAgent) → Escalation (AlertingAgent).

**Conservative by default:** Low-risk remediation actions only. Success rate tracking with auto-disable for failing strategies. Human escalation on critical failures.

**Don't overengineer:** Static strategies first (not complex rule engine). Simple webhook integration (not custom AlertSignalProcessor). Reuse existing infrastructure.

**Audit everything:** Every config change (who, when, why). Every remediation (pre, post, outcome, duration). Redacted secrets.

**Compute efficiency:** Compression policies on hypertables. Retention policies (don't keep data forever). In-memory cache for config reads.

---

## References

- Current alerting: `services/alerting_agent.py` (Layer 9 dispatcher)
- Current config: `src/config/settings.py` (~40 tunable params)
- Shadow registry: `shadow_registry` table (correct pattern already)
- Phase 108 self-healing hardening: `.planning/phases/108-self-healing-hardening/`
