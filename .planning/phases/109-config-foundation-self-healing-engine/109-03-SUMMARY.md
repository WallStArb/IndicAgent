---
phase: 109-config-foundation-self-healing-engine
plan: "03"
subsystem: config
tags: [config, base-agent, hot-reload, kafka, systemd, otel-metrics]
dependency_graph:
  requires:
    - config_foundation_db_schema   # 109-01: ConfigService.list() used in pre-load
    - ConfigService                 # 109-01
    - topic_config_updates          # 109-02
    - config_and_selfhealing_metrics  # 109-02: CONFIG_RELOAD_TOTAL, CONFIG_RELOAD_LATENCY_SECONDS
  provides:
    - ConfigConsumerMixin
    - BaseAgent_config_integration
    - config_systemd_units
  affects:
    - all BaseAgent subclasses (config available in _setup())
    - 109-05  # ServiceAuditorAgent overrides _on_config_message_received
tech_stack:
  added: []
  patterns:
    - Two-phase config integration (snapshot before _setup, Kafka after _setup)
    - ConfigConsumerMixin for composable config behavior
    - _config_prefixes allowlist for reload storm prevention
    - __getattr__ fallback pattern for test __new__ bypass compatibility
key_files:
  created:
    - src/config/config_consumer.py
    - production/systemd/indicagent-config-service.service
    - production/systemd/indicagent-outbox-dispatcher.service
  modified:
    - src/observability/metrics.py
    - src/core/agent/base.py
decisions:
  - "Two-phase config: snapshot (Phase A) before _setup(); Kafka subscription (Phase B) after _setup() - addresses Codex HIGH finding on lifecycle ordering"
  - "_config_prefixes empty tuple = accept all OPS keys (permissive default); non-empty = only matching prefixes (storm prevention)"
  - "_on_config_message_received no-op hook: enables subclass post-reload reactions without overriding the loop (Plan 05 pattern)"
  - "__getattr__ fallback for config attrs: tests using __new__ bypass get safe defaults without changing test code"
  - "_config_layer = INFRA skips Kafka subscription (OutboxDispatcher circular dep prevention)"
metrics:
  duration_minutes: 7
  completed_date: "2026-05-29"
  tasks_completed: 4
  files_created: 3
  files_modified: 2
---

# Phase 109 Plan 03: BaseAgent Config Integration Summary

**One-liner:** Two-phase non-fatal config integration in BaseAgent with snapshot-before-setup ordering, Kafka hot-reload, prefix-filtered storm prevention, and no-op subclass hook for post-reload reactions.

## What Was Built

### Task 1: Config Stale + Last-Reload Metrics (8052d48e)

Added to `src/observability/metrics.py` after `CONFIG_AUTH_FAILED_TOTAL`:

| Metric | Type | Purpose |
|--------|------|---------|
| `CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS` | gauge | Timestamp of last successful config reload per agent |
| `CONFIG_STALE_TOTAL` | counter | Config operations failed (DB/Kafka unavailable), service using cached/default config |

Verification:
```
.venv/bin/python -c "from src.observability.metrics import CONFIG_LAST_RELOAD_TIMESTAMP_SECONDS, CONFIG_STALE_TOTAL, CONFIG_RELOAD_LATENCY_SECONDS; print('OK')"
=> OK
```

### Task 2: ConfigConsumerMixin (7c83717f)

`src/config/config_consumer.py` implements:

**Class attributes with defaults:**
```python
_config_layer: str = "OPS"           # override to "INFRA" to skip Kafka subscription
_config_prefixes: tuple[str, ...] = ()  # empty = accept all OPS keys
```

**Phase A: `_pre_setup_config_load()`**
- Calls `ConfigService.list()` to get current OPS snapshot
- Filters by `_config_prefixes` if set; otherwise accepts all keys
- On failure: emits `CONFIG_STALE_TOTAL{agent_id, reason=ExceptionClassName}` and logs warning
- Does NOT re-raise (NON-FATAL)

**Phase B: `_setup_config_consumer()`**
- Skips if `_config_layer != "OPS"` (INFRA/STRUCT services don't hot-reload)
- Constructs `KafkaConsumerClient(topic_config_updates(env_name), bootstrap_servers=settings.kafka_bootstrap_servers, group_id=f"{name}_config_consumer")`
- NO `.subscribe()` call — topic bound at construction (KafkaConsumerClient API)
- On failure: emits `CONFIG_STALE_TOTAL{reason=kafka_subscribe_failed}` and logs warning
- Does NOT re-raise (NON-FATAL)

**`_reload_config_loop()` key behaviors:**
- Prefix filter: `if self._config_prefixes and not config_key.startswith(self._config_prefixes): continue`
- Latency tracking: `(datetime.now(UTC) - changed_at).total_seconds()` → `CONFIG_RELOAD_LATENCY_SECONDS.record()`
- Hook: `await self._on_config_message_received(config_key, parsed)` after each accepted key
- Three distinct `CONFIG_STALE_TOTAL` reasons: `ExceptionClassName` (Phase A), `kafka_subscribe_failed` (Phase B), `parse_failed` (message loop)

**Acceptance criteria verification:**
```
grep -q "_pre_setup_config_load" src/config/config_consumer.py      → FOUND
grep -q "_config_prefixes" src/config/config_consumer.py            → FOUND
grep -q "CONFIG_RELOAD_LATENCY_SECONDS" src/config/config_consumer.py → FOUND
grep -q "kafka_bootstrap_servers" src/config/config_consumer.py    → FOUND
grep -q "kafka_brokers" src/config/config_consumer.py              → NOT FOUND (correct)
grep -q "\.subscribe(" src/config/config_consumer.py               → NOT FOUND (correct)
grep -q "_on_config_message_received" src/config/config_consumer.py → FOUND
```

### Task 3: BaseAgent Integration (4bb7d839 + 62fdeffd)

**`src/core/agent/base.py` changes:**

1. Added `from typing import Any` import
2. Added `from src.config.config_consumer import ConfigConsumerMixin` import
3. Changed class declaration: `class BaseAgent(abc.ABC, ConfigConsumerMixin)`
4. Added config instance attrs in `__init__` (after `_cb_open`):
   ```python
   self._config_cache: dict[str, Any] = {}
   self._config_consumer = None
   self._config_reload_task = None
   self._config_loaded = False
   ```
5. Updated `start()` with two-phase config integration:
   ```
   await self._pre_setup_config_load()   # NEW - Phase A (snapshot, NON-FATAL)
   await self._setup()                   # EXISTING - _setup() CAN now read OPS config
   await self._setup_config_consumer()   # NEW - Phase B (Kafka subscription, NON-FATAL)
   ```
6. Added `await self._teardown_config_consumer()` in `finally` block (before `await self.stop()`)
7. Added explicit `get_config()` method for IDE/typing visibility

**Startup ordering proof (line numbers):**
```
Line _pre_setup_config_load (await): 256
Line await self._setup():            268
Line _setup_config_consumer (await): 272
ORDERING: pre < setup < post — CORRECT
```

**Class declaration verification:**
```
grep -q "class BaseAgent.*ConfigConsumerMixin" src/core/agent/base.py → FOUND
```

**Method availability:**
```python
from src.core.agent.base import BaseAgent
assert hasattr(BaseAgent, 'get_config')               # PASS
assert hasattr(BaseAgent, '_pre_setup_config_load')   # PASS
assert hasattr(BaseAgent, '_setup_config_consumer')   # PASS
```

**Unit tests after integration:** 4052 passed, 31 skipped (zero failures)

### Task 4: Systemd Unit Files (2d92d5d0)

**`production/systemd/indicagent-config-service.service`:**
- `Description=IndicAgent Config Service (HTTP API port 9001, OTel metrics port 9005)`
- `METRICS_PORT=9005`
- Comment: `# Port 9005 = OTel metrics scrape (config HTTP API is hardcoded to 9001 in uvicorn.run)`

**`production/systemd/indicagent-outbox-dispatcher.service`:**
- `Description=IndicAgent Outbox Dispatcher (publishes config updates to Kafka, OTel metrics port 9006)`
- `METRICS_PORT=9006`

**Validation:**
```
systemd-analyze verify indicagent-config-service.service indicagent-outbox-dispatcher.service
=> exit code 0 (both valid)
sudo systemctl daemon-reload => exit code 0
```

**Port labels in descriptions:**
```
grep -q "9001" indicagent-config-service.service   → FOUND
grep -q "9005" indicagent-config-service.service   → FOUND
grep -q "9006" indicagent-outbox-dispatcher.service → FOUND
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tests using __new__ bypass pattern failed on missing config attrs**
- **Found during:** Post-Task-3 unit test run
- **Issue:** `test_cross_asset_emits_*` and `test_llm_writer_emits_setup_success_metric` use `ServiceClass.__new__()` to bypass `__init__`, so `_config_cache`, `_config_reload_task`, `_config_consumer`, `_config_loaded` were not set. When `_teardown_config_consumer()` ran in `start()` finally block, `__getattr__` raised `AttributeError` instead of returning a safe default.
- **Fix:** Added config mixin attrs to `__getattr__` fallback: `_config_cache -> {}`, `_config_consumer -> None`, `_config_reload_task -> None`, `_config_loaded -> False`
- **Files modified:** `src/core/agent/base.py` (commit 62fdeffd)
- **Tests after fix:** 4052 passed (all previously failing tests now pass)

## Self-Check: PASSED

Files verified:
- `src/observability/metrics.py` - FOUND
- `src/config/config_consumer.py` - FOUND
- `src/core/agent/base.py` - FOUND
- `production/systemd/indicagent-config-service.service` - FOUND
- `production/systemd/indicagent-outbox-dispatcher.service` - FOUND

Commits verified:
- `8052d48e` (metrics) - FOUND
- `7c83717f` (config consumer mixin) - FOUND
- `4bb7d839` (base agent integration) - FOUND
- `2d92d5d0` (systemd units) - FOUND
- `62fdeffd` (getattr fix) - FOUND
