# Phase 109: Config Foundation & Self-Healing Engine - Context

**Gathered:** 2026-05-28
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-05-28-config-foundation-and-alerting-system.md)

## Phase Boundary

Phase 109 implements a unified config system with time-series state management and a control-theory-based self-healing engine. The phase delivers:

1. **Config Foundation** - DB-backed config with time-series audit trail, transactional outbox for Kafka propagation, and hot-reload pattern for all services
2. **Self-Healing Engine** - Control-theory-based remediation system with Alertmanager webhook integration, success rate tracking, and automated escalation
3. **Config Migration** - Migration of runtime params from settings.py to the new config system

## Implementation Decisions

### Architecture
- **Three semantic layers** - INFRASTRUCTURE (DB URLs, secrets - restart required), STRUCTURE (plugin tiers, DAG order - deploy required), OPERATIONAL (feature flags, thresholds - hot-reload)
- **Config as time-series** - Same database (TimescaleDB), same query patterns, same audit trail as signals
- **Kafka as sink not pipe** - ConfigService writes DB + outbox, OutboxDispatcher publishes to Kafka, services subscribe for hot-reload
- **Zero-downtime tuning** - All config changes are hot-reloadable for OPERATIONAL layer

### Database Schema
- **config_schema** - Registry of valid keys with type, range, allowed values, dependencies, category (INFRA/STRUCT/OPS), is_secret flag
- **config_state** - Current values (fast lookup)
- **config_history** - Time-series audit trail (hypertable with retention/compression)
- **config_outbox** - Transactional outbox for Kafka (status: pending/published/failed)
- **remediation_ledger** - All remediation attempts (hypertable with pre/post values, outcome, duration_ms)
- **remediation_success_rates** - Materialized view (30-day rolling window)

### ConfigService API
- `set(key, value, changed_by, expected_version, reason)` - Validation, version check, transactional write
- `get(key, default)` - In-memory cache (hot), else DB (cold)
- `get_at(key, t)` - Time-travel query
- `list(category)` - All current config
- `revert_key(key, version)` - Rollback with validation
- `preview_revert_to_timestamp(t)` - Show what would change
- `revert_keys(keys, t)` - Rollback specific keys

### Transactional Outbox Pattern
- DB transaction writes: config_history + config_state + config_outbox
- OutboxDispatcher (separate process) publishes to Kafka
- Guarantees: DB commit before Kafka publish, retry on failure, ordering per key

### Optimistic Concurrency
- Prevents silent overwrites from concurrent writes
- `set(expected_version=N)` fails if current version != N
- Last-write-wins without expected_version (requires explicit opt-in)

### Security Model
- **Authentication** - Bearer token for API, shared secret for webhook
- **Audit** - All changes logged with changed_by, timestamp, reason
- **Secret redaction** - is_secret keys log "**REDACTED**" instead of actual value

### Self-Healing Engine (Control Theory)
- **Control loop** - Sensor → Setpoint → Error → Actuator → Process → Feedback
- **Every remediation must** - Measure pre-state, compare to setpoint, execute action, measure post-state, record outcome, track success rate
- **Webhook contract** - Alertmanager sends alert_id, severity, state_variable, current_value, threshold, labels; engine returns remediation_id, status, estimated_duration_ms
- **Idempotency** - alert_id prevents double-execution
- **Circuit breaker** - Pause if >50% failures in 5min
- **Auto-disable** - Strategies with <80% success rate disabled

### Remediation Strategies (Phase 1: Conservative)
- Static mapping only, low-risk actions
- disk_usage_high → delete_old_logs (threshold 80%, max 3/hour)
- consumer_lag_high → restart_consumer (threshold 1000, max 2/hour)
- db_pool_exhausted → flush_connection_pool (threshold 90%, max 5/hour)

### Kafka Integration
- **topic_config_updates** (compacted) - Config change propagation
- Partition key: config_key (ensures ordering per key)
- Schema: config_key, config_value, version, changed_by, changed_at, reason, redacted, correlation_id

### Config Consumer Pattern (BaseAgent)
- On startup: load DB snapshot
- Subscribe to topic_config_updates
- Hot-reload: update in-memory cache on message
- Emit config_reload_total metric

### Failure Modes
- **ConfigService down** - Services use last-known-good cached config
- **Kafka down** - Outbox status=pending, OutboxDispatcher retries
- **Stale detection** - Services emit config_last_reload_timestamp_seconds
- **Fail-closed vs fail-open** - Safety gates fail-closed, tunable params fail-open

### Observability Requirements
- **Config metrics**: config_set_total, config_validation_failed_total, config_revert_total, config_outbox_pending, config_outbox_publish_latency_seconds, config_reload_total
- **Self-healing metrics**: remediation_attempt_total, remediation_success_total, remediation_duration_seconds, remediation_success_rate, webhook_received_total, webhook_validation_failed_total
- **Traces**: Span on ConfigService.set(), BaseAgent.config_reload, Remediation.execute()
- **Logging**: Structlog with key, value, changed_by, validation_result (redacted for secrets)

### Implementation Phases
- **109.1** - Config foundation (DB tables, ConfigService, OutboxDispatcher, Kafka propagation, observability)
- **109.2** - BaseAgent config reload pattern integration
- **109.3** - SelfHealingEngine (webhook, remediation engine, ledger)
- **109.4** - Alertmanager webhook configuration
- **109.5** - Migration of runtime params from settings.py

### Technical Debt Cleanup
After new system is in place, remove old patterns:
- Delete ~15 runtime params from settings.py (REGIME_PROB_MIN, SWARM_MIN_CONFIDENCE, etc.)
- Delete _LAG_THRESHOLDS dict from service_auditor_agent.py (~25 entries)
- Delete hardcoded shadow_only=True from 8 AI agents

### Default State
- All alerts OFF by default
- Runtime params seeded from current settings.py values
- Everything OFF by default (Renaissance principle)

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Document
- `docs/plans/2026-05-28-config-foundation-and-alerting-system.md` — Complete design specification

### Existing Code
- `src/config/settings.py` — Current config system (~40 tunable params, source of truth for migration values)
- `services/service_auditor_agent.py` — Current _LAG_THRESHOLDS dict (~25 entries to migrate)
- `services/alerting_agent.py` — Current alerting dispatcher (Layer 9, coexistence target)
- `src/core/agent/base.py` — BaseAgent class (needs config reload pattern integration)

### Related
- `services/service_auditor_agent.py` — _DAG_ORDER registry (new service registration point)
- `src/core/stream_keys.py` — Stream/topic key construction (add topic_config_updates)

## Specific Ideas

### Config Tables (SQL)
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

### Remediation Ledger (SQL)
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

### ConfigService Class Signature
```python
class ConfigService:
    async def set(key, value, changed_by="system", expected_version=None, reason=None) -> ConfigChange
    async def get(key, default=None) -> Any
    async def get_at(key, t: datetime) -> Any
    async def list(category: str | None = None) -> dict[str, Any]
    async def revert_key(key, version, changed_by="system", reason=None) -> dict
    async def preview_revert_to_timestamp(t: datetime) -> dict
    async def revert_keys(keys, t: datetime, changed_by="system", reason=None) -> dict
```

### Alertmanager Webhook Request
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

### Kafka Message Schema
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

### Config Migration Table
| From | To | Example | Count |
|------|-----|----------|-------|
| REGIME_PROB_MIN = 0.30 | regime.prob_min | Runtime params | ~15 |
| SWARM_MIN_CONFIDENCE = 0.70 | swarm.min_confidence | Thresholds | ~8 |
| _LAG_THRESHOLDS = {...} | alert.lag.* | Service thresholds | ~25 |
| Hardcoded shadow_only=True | ai.agent.shadow_mode | Feature flags | ~8 |
| ENV vars (DATABASE_URL) | Stay in ENV | Infra (never runtime) | ~30 |

## Deferred Ideas

### Future Enhancements (Not in Phase 109)
- Per-category permissions (who can change INFRA vs STRUCT vs OPS)
- Approval workflows for high-risk keys
- Complex rule engine for remediation (current: static mapping)
- Rich dashboard for config history visualization
- A/B testing framework for config values
- Automated config optimization based on signal quality
- Multi-region config replication
- Config validation dry-run mode

### Scope Fence - What Phase 109 Does NOT Include
- Full Prometheus Alertmanager rule set (only webhook integration)
- Complete settings.py cleanup (technical debt section, not execution)
- Production tuning of thresholds (baseline only)
- Advanced remediation strategies beyond conservative set
- Config versioning UI (API only)
- Real-time config diff visualization

---
*Phase: 109-config-foundation-self-healing-engine*
*Context gathered: 2026-05-28 via PRD Express Path*
