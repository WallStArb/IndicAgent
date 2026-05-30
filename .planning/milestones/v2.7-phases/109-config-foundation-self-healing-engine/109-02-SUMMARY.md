---
phase: 109-config-foundation-self-healing-engine
plan: "02"
subsystem: config
tags: [config, kafka, outbox-pattern, fastapi, otel-metrics, service-registry]
dependency_graph:
  requires:
    - config_foundation_db_schema  # 109-01: config_outbox table used by OutboxDispatcher
    - ConfigService                # 109-01: ConfigService used by HTTP API
  provides:
    - OutboxDispatcherAgent
    - config_service_http_api
    - topic_config_updates
    - config_and_selfhealing_metrics
    - phase109_service_registry
  affects:
    - 109-03  # systemd units (Plan 03 Task 4)
    - 109-05  # self-healing agent uses WEBHOOK_* and REMEDIATION_* metrics
tech_stack:
  added:
    - FastAPI (config_service_agent.py)
    - uvicorn (port 9001)
  patterns:
    - Transactional outbox (poll + claim + publish + confirm)
    - Adaptive exponential backoff (100ms -> 2000ms)
    - FOR UPDATE SKIP LOCKED (horizontal scaling)
    - Bearer token auth via dependency injection (FastAPI Depends)
    - Three-layer invariant enforcement (INFRA/STRUCT/OPS)
key_files:
  created:
    - src/config/outbox_dispatcher.py
    - services/outbox_dispatcher_agent.py
    - services/config_service_agent.py
  modified:
    - src/observability/metrics.py
    - src/core/stream_keys.py
    - services/service_auditor_agent.py
decisions:
  - "OutboxDispatcherAgent._config_layer=INFRA avoids circular dep on topic it publishes"
  - "Adaptive poll backoff: 100ms reset on work, double to 2000ms max on idle (reduces DB load)"
  - "CONFIG_API_TOKEN not set = dev mode open (no auth); set = mandatory Bearer"
  - "Token rotation deferred to Phase 110 (restart required for now)"
  - "_LAG_THRESHOLDS intentionally untouched in Task 5 (Plan 05 will load from config DB)"
  - "Phase 109 services at priority 9 in _DAG_ORDER (same layer as auditors, alerting)"
metrics:
  duration_minutes: 10
  completed_date: "2026-05-29"
  tasks_completed: 5
  files_created: 3
  files_modified: 3
---

# Phase 109 Plan 02: OutboxDispatcher, ConfigService HTTP API, Metrics Summary

**One-liner:** Kafka outbox dispatcher with adaptive polling, FastAPI config HTTP API on port 9001 with mandatory Bearer auth, OTel metrics for config/self-healing, and service auditor DAG registration.

## What Was Built

### Task 1: Config and Self-Healing OTel Metrics (de6a13a3)

Added to `src/observability/metrics.py`:

**Config metrics (8 total):**
| Metric | Type | Purpose |
|--------|------|---------|
| `CONFIG_SET_TOTAL` | counter | Set operations by key + outcome |
| `CONFIG_VALIDATION_FAILED_TOTAL` | counter | Validation failures by key + reason |
| `CONFIG_REVERT_TOTAL` | counter | Revert operations by key |
| `CONFIG_OUTBOX_PENDING` | up_down_counter | Pending outbox entries awaiting Kafka publish |
| `CONFIG_OUTBOX_PUBLISH_LATENCY_SECONDS` | histogram | Outbox to Kafka publish latency |
| `CONFIG_RELOAD_TOTAL` | counter | Hot-reload events by agent + key |
| `CONFIG_RELOAD_LATENCY_SECONDS` | histogram | Kafka receive to in-memory cache update lag |
| `CONFIG_AUTH_FAILED_TOTAL` | counter | API auth failures by reason |

**Self-healing / webhook metrics (8 total):**
| Metric | Type | Purpose |
|--------|------|---------|
| `REMEDIATION_ATTEMPT_TOTAL` | counter | Remediation attempts by state_variable + action |
| `REMEDIATION_SUCCESS_TOTAL` | counter | Successful outcomes |
| `REMEDIATION_DURATION_SECONDS` | histogram | Execution latency |
| `REMEDIATION_SUCCESS_RATE` | gauge | 30-day rolling success rate per action |
| `REMEDIATION_MEASURE_FAILED_TOTAL` | counter | Prometheus query failures (fail-closed) |
| `WEBHOOK_RECEIVED_TOTAL` | counter | Alertmanager webhook requests received |
| `WEBHOOK_AUTH_FAILED_TOTAL` | counter | Webhook auth failures |
| `WEBHOOK_VALIDATION_FAILED_TOTAL` | counter | Webhook payload validation failures |

Import verification:
```
from src.observability.metrics import CONFIG_SET_TOTAL, CONFIG_RELOAD_TOTAL,
  CONFIG_RELOAD_LATENCY_SECONDS, CONFIG_AUTH_FAILED_TOTAL, REMEDIATION_ATTEMPT_TOTAL,
  REMEDIATION_MEASURE_FAILED_TOTAL, WEBHOOK_AUTH_FAILED_TOTAL, WEBHOOK_VALIDATION_FAILED_TOTAL
=> Metrics import successful
```

### Task 2: topic_config_updates Stream Key (65ce8f0f)

Added to `src/core/stream_keys.py` after `topic_alert_requests`:

```python
def topic_config_updates(env_name: str) -> str:
    # cleanup.policy=compact, partitions=1, partition key=config_key
    return f"{env_prefix(env_name)}config.updates"
```

Event contract (schema_version=1):
```json
{
  "schema_version": 1,
  "config_key": "regime.prob_min",
  "config_value": "0.35",
  "value_type": "float",
  "version": 7,
  "changed_at": "2026-05-29T12:00:00Z",
  "changed_by": "operator@example.com",
  "operation": "set",
  "reason": null,
  "redacted": false,
  "correlation_id": "uuid4"
}
```

Behavior verified:
- `topic_config_updates('')` == `'config.updates'`
- `topic_config_updates('dev')` == `'dev.config.updates'`

### Task 3: OutboxDispatcherAgent (8f6ac260)

**`src/config/outbox_dispatcher.py`:**

- `OutboxDispatcherAgent(BaseAgent)` - polls DB, no Kafka consumption
- `_config_layer = "INFRA"` - skips self-subscription to config topic (circular dep prevention)
- `topics_consumed = []` - poll-only agent
- Adaptive poll loop: 100ms reset on non-empty batch, doubles to 2000ms max on idle
- Transactional claim: `UPDATE config_outbox SET status='publishing' WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 100)`
- Publishes schema_version=1 event with all required fields (value_type from config_schema JOIN, redacted from is_secret, uuid4 correlation_id)
- On success: `status='published'`, `CONFIG_OUTBOX_PENDING.add(-1)`, latency recorded
- On failure: `retry_count++`, `next_attempt_at = NOW() + 2^min(retry_count,6)s` (max 64s)
- Uses `msg=` kwarg for `KafkaProducerClient.publish` (not `value=`)

**`services/outbox_dispatcher_agent.py`** - systemd `__main__` entry point.

Source assertions all pass:
- `grep -q "msg="` - FOUND
- `grep -q "FOR UPDATE SKIP LOCKED"` - FOUND
- `grep -q "_config_layer.*INFRA"` - FOUND
- Adaptive backoff: `min(current_backoff_ms * 2, _POLL_MAX_MS)` where `_POLL_MAX_MS = 2000`

### Task 4: ConfigService HTTP API (ee0db425)

**`services/config_service_agent.py`** - FastAPI on port 9001:

**Port convention (explicit comment in file):**
- `9001 = Config HTTP API (uvicorn)`
- `9005 = Config Service OTel metrics scrape endpoint (METRICS_PORT env var)`

**Auth verification:**
```
CONFIG_API_TOKEN not set:   POST /api/config/set -> 200 (dev mode)
CONFIG_API_TOKEN=secret:
  No Authorization header    -> 401 (CONFIG_AUTH_FAILED_TOTAL{reason=missing_header})
  Wrong Bearer token         -> 401 (CONFIG_AUTH_FAILED_TOTAL{reason=invalid_token})
  Correct Bearer token       -> 200
  key="DATABASE_URL"         -> 422 (INFRA key rejected)
  stale expected_version     -> 409 (ConfigVersionConflict)
```

**Endpoints:**
- `POST /api/config/set` - set OPS config value
- `GET /api/config/get/{key}` - get parsed value
- `GET /api/config/list` - all current OPS config
- `POST /api/config/revert` - revert to historical version

Exception handlers: `ConfigValidationError -> 422`, `ConfigVersionConflict -> 409`.

Three-layer invariant: `ConfigService._validate_key_domain()` rejects INFRA/STRUCT keys with detailed error message including `.env` and `code deployment` guidance.

### Task 5: Service Auditor DAG Registration (8442cf10)

Added to `services/service_auditor_agent.py`:

**`_DAG_ORDER`** - three new units at priority 9:
```python
"indicagent-config-service": 9,
"indicagent-outbox-dispatcher": 9,
"indicagent-self-healing-agent": 9,
```

**`_AGENT_ID_TO_UNIT`** - three new mappings:
```python
"config-service": "indicagent-config-service",
"outbox-dispatcher": "indicagent-outbox-dispatcher",
"self-healing-agent": "indicagent-self-healing-agent",
```

`_LAG_THRESHOLDS` intentionally untouched - Plan 05 Task 3 will load from config DB.

Assertion verification:
```
assert 'indicagent-config-service' in _DAG_ORDER  # PASS
assert _AGENT_ID_TO_UNIT['config-service'] == 'indicagent-config-service'  # PASS
# ... all 6 assertions pass
```

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

Files verified:
- `src/observability/metrics.py` - FOUND (8 CONFIG_* + 8 REMEDIATION_*/WEBHOOK_*)
- `src/core/stream_keys.py` - FOUND (topic_config_updates with schema_version=1 contract)
- `src/config/outbox_dispatcher.py` - FOUND
- `services/outbox_dispatcher_agent.py` - FOUND
- `services/config_service_agent.py` - FOUND
- `services/service_auditor_agent.py` - FOUND (3 units in DAG_ORDER + AGENT_ID_TO_UNIT)

Commits verified:
- de6a13a3 (metrics) - FOUND
- 65ce8f0f (stream key) - FOUND
- 8f6ac260 (outbox dispatcher) - FOUND
- ee0db425 (config service API) - FOUND
- 8442cf10 (service auditor) - FOUND

Unit tests: 4052 passed, 31 skipped, 0 failures.
