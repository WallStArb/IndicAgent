# Service Auditor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `ServiceAuditorAgent` that monitors all 11 pipeline services, self-heals dead/laggy services with DAG-ordered restarts, and records every event to TimescaleDB as a labeled audit trail.

**Architecture:** Hybrid three-layer model — systemd handles process liveness (WatchdogSec), Prometheus supplies metrics/lag (fixed scrape config), `ServiceAuditorAgent` provides intelligence: polling both, applying graduated response (warn→restart→escalate), persisting every state transition to `service_health_events`. Service states live in memory; Kafka `system.health.events` is the real-time event bus.

**Tech Stack:** Python asyncio, `aiohttp` (Prometheus API), asyncpg (TimescaleDB), asyncio subprocess (systemctl queries), `sdnotify` (watchdog notify), `aiokafka` via existing `KafkaProducerClient`.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `services/bar_aggregator_agent.py` | Fix consumer reset race condition |
| Modify | `src/core/agent/base.py` | Add `_watchdog_notify` background task |
| Modify | `requirements.txt` | Add `sdnotify` |
| Modify | `production/prometheus.yml` | Fix scrape config — 11 active services, remove 3 dead |
| Modify | `/etc/systemd/system/indicagent-*.service` (15 files) | Add `WatchdogSec=60`, `NotifyAccess=main` |
| Modify | `src/core/stream_keys.py` | Add `topic_health_events()` and `topic_health_events_dlq()` |
| Create | `production/migrations/054_service_health_events.sql` | New hypertable |
| Create | `services/service_auditor_agent.py` | Core agent — registry, check loops, graduated response |
| Create | `/etc/systemd/system/indicagent-service-auditor.service` | Systemd unit |
| Create | `tests/unit/service_tests/test_service_auditor_agent.py` | Unit tests |

---

## Task 1: Fix Bar Aggregator Consumer Reset Race Condition

**Files:**
- Modify: `services/bar_aggregator_agent.py`
- Modify: `tests/unit/service_tests/test_bar_aggregator_agent.py`

The current `_handle_unhealthy_state` calls `stop()`/`start()` on the Kafka consumer from a background
task while the main loop's `async for` still holds it open — causing "Did you call start twice?".
The outer `while self.running:` loop must own stop/start; the health checker only sets the flag.

- [ ] **Step 1: Write failing test**

Add to `tests/unit/service_tests/test_bar_aggregator_agent.py`:

```python
@pytest.mark.asyncio
async def test_handle_unhealthy_state_only_sets_flag():
    """_handle_unhealthy_state must NOT call stop/start — only set the flag."""
    agent = _make_agent()
    agent._kafka_consumer = AsyncMock()
    agent._consumer_restart_needed = False

    await agent._handle_unhealthy_state("no_bars_1000s")

    assert agent._consumer_restart_needed is True
    agent._kafka_consumer.stop.assert_not_called()
    agent._kafka_consumer.start.assert_not_called()
```

- [ ] **Step 2: Run to confirm failure**

```bash
.venv/bin/pytest tests/unit/service_tests/test_bar_aggregator_agent.py::test_handle_unhealthy_state_only_sets_flag -v
```

Expected: `FAILED` — `stop` is called in current implementation.

- [ ] **Step 3: Fix `_handle_unhealthy_state` — remove stop/start**

In `services/bar_aggregator_agent.py`, replace the entire `_handle_unhealthy_state` method:

```python
async def _handle_unhealthy_state(self, reason: str):
    """Signal main loop to restart consumer. Stop/start is the outer loop's job."""
    if "no_bars" in reason or "consuming_not_emitting" in reason:
        self.logger.warning("bar_aggregator.attempting_consumer_reset")
        self._consumer_restart_needed = True
```

- [ ] **Step 4: Move stop/start to the outer `while self.running:` loop**

In `services/bar_aggregator_agent.py`, after the `async for` block exits, add the reconnect:

```python
# Outer loop: re-enter on consumer restart
while self.running:
    self._consumer_restart_needed = False
    async for _topic, _key, payload in self._kafka_consumer.messages():
        if not self.running or self._consumer_restart_needed:
            break
        # ... existing bar processing code unchanged ...

    # Consumer restart — safe to stop/start here, async-for has exited cleanly
    if self._consumer_restart_needed and self.running:
        try:
            await self._kafka_consumer.stop()
            await asyncio.sleep(1)
            await self._kafka_consumer.start()
            self._health_metrics._consecutive_errors = 0
            self._health_metrics._bars_last_minute = 0
            self._health_metrics._htf_bars_last_minute = 0
            self.logger.info("bar_aggregator.consumer_reset_complete")
        except Exception as exc:
            self.logger.error("bar_aggregator.consumer_reset_failed", error=str(exc))
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_bar_aggregator_agent.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add services/bar_aggregator_agent.py tests/unit/service_tests/test_bar_aggregator_agent.py
git commit -m "fix(bar-aggregator): move consumer stop/start to outer loop, fix start-twice race"
```

---

## Task 2: Fix Prometheus Scrape Config

**Files:**
- Modify: `production/prometheus.yml`

- [ ] **Step 1: Replace the entire file content**

```yaml
# Prometheus config for IndicAgent pipeline metrics
# Scrapes services running on the host (use host.docker.internal from Docker)

global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "indicagent-ibkr-provider"
    static_configs:
      - targets: ["host.docker.internal:9129"]

  - job_name: "indicagent-provider-merger"
    static_configs:
      - targets: ["host.docker.internal:9130"]

  - job_name: "indicagent-bar-aggregator-compute"
    static_configs:
      - targets: ["host.docker.internal:9120"]

  - job_name: "indicagent-bar-writer"
    static_configs:
      - targets: ["host.docker.internal:9121"]

  - job_name: "indicagent-bar-auditor"
    static_configs:
      - targets: ["host.docker.internal:9123"]

  - job_name: "indicagent-intelligence-pipeline"
    static_configs:
      - targets: ["host.docker.internal:9125"]

  - job_name: "indicagent-signal-tracker"
    static_configs:
      - targets: ["host.docker.internal:9115"]

  - job_name: "indicagent-signal-writer"
    static_configs:
      - targets: ["host.docker.internal:9119"]

  - job_name: "indicagent-ai-narrative"
    static_configs:
      - targets: ["host.docker.internal:9113"]

  - job_name: "indicagent-feature-writer"
    static_configs:
      - targets: ["host.docker.internal:9116"]

  - job_name: "indicagent-llm-writer"
    static_configs:
      - targets: ["host.docker.internal:9117"]

  - job_name: "indicagent-cross-asset"
    static_configs:
      - targets: ["host.docker.internal:9118"]

  - job_name: "indicagent-service-auditor"
    static_configs:
      - targets: ["host.docker.internal:9131"]
```

- [ ] **Step 2: Reload Prometheus (no container restart)**

```bash
curl -s -X POST http://localhost:9090/-/reload && echo "reloaded"
```

- [ ] **Step 3: Verify targets**

```bash
sleep 5 && curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data['data']['activeTargets']:
    print(t['labels'].get('job','?'), '|', t['health'])
"
```

Expected: 13 targets listed, 12 `up` (service-auditor will be `down` until Task 7).

- [ ] **Step 4: Commit**

```bash
git add production/prometheus.yml
git commit -m "fix(prometheus): update scrape config to all 11 active services + auditor, remove 3 dead jobs"
```

---

## Task 3: Add WatchdogSec to BaseAgent and Unit Files

**Files:**
- Modify: `requirements.txt`
- Modify: `src/core/agent/base.py`
- Modify: all 15 pipeline service unit files

- [ ] **Step 1: Add sdnotify to requirements.txt**

Add the line:

```
sdnotify>=0.3.2
```

Install:

```bash
.venv/bin/pip install "sdnotify>=0.3.2"
```

- [ ] **Step 2: Write failing test for watchdog notify**

Create `tests/unit/test_base_agent.py`:

```python
"""Unit tests for BaseAgent watchdog notify."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.agent.base import BaseAgent


class _ConcreteAgent(BaseAgent):
    async def _run(self) -> None:
        self._stop_event.set()


@pytest.mark.asyncio
async def test_watchdog_notify_noop_when_no_socket():
    """_watchdog_notify exits immediately when NOTIFY_SOCKET is not set."""
    agent = _ConcreteAgent("test_agent")
    with patch.dict(os.environ, {}, clear=True):
        task = asyncio.create_task(agent._watchdog_notify())
        await asyncio.sleep(0.05)
        assert task.done()


@pytest.mark.asyncio
async def test_watchdog_notify_sends_when_socket_set():
    """_watchdog_notify calls sdnotify.notify('WATCHDOG=1') when socket is set."""
    agent = _ConcreteAgent("test_agent")
    agent._stop_event = asyncio.Event()

    with patch.dict(os.environ, {"NOTIFY_SOCKET": "/run/test.sock", "WATCHDOG_USEC": "2000000"}):
        with patch("sdnotify.SystemdNotifier") as mock_cls:
            mock_notifier = MagicMock()
            mock_cls.return_value = mock_notifier

            task = asyncio.create_task(agent._watchdog_notify())
            await asyncio.sleep(0.15)
            agent._stop_event.set()
            await asyncio.sleep(0.05)
            task.cancel()

            assert mock_notifier.notify.call_count >= 1
            mock_notifier.notify.assert_called_with("WATCHDOG=1")
```

Run:

```bash
.venv/bin/pytest tests/unit/test_base_agent.py -v
```

Expected: `FAILED` — `_watchdog_notify` not defined yet.

- [ ] **Step 3: Add `_watchdog_notify` to `src/core/agent/base.py`**

Add `import os` to the imports at top.

Add the method after `_report_consumer_lag`:

```python
async def _watchdog_notify(self) -> None:
    """Notify systemd watchdog so it doesn't kill a healthy process.

    No-op when NOTIFY_SOCKET or WATCHDOG_USEC is not set (direct run / tests).
    Notifies at half WatchdogSec interval to stay well within the deadline.
    """
    socket_path = os.getenv("NOTIFY_SOCKET", "")
    usec = int(os.getenv("WATCHDOG_USEC", "0"))
    if not socket_path or usec <= 0:
        return
    import sdnotify
    notifier = sdnotify.SystemdNotifier()
    interval_s = usec / 2_000_000
    while self.running:
        notifier.notify("WATCHDOG=1")
        await asyncio.sleep(interval_s)
```

Update `start()` to launch and cancel the watchdog task alongside `lag_task`:

```python
lag_task = asyncio.create_task(self._report_consumer_lag())
watchdog_task = asyncio.create_task(self._watchdog_notify())
try:
    await self._run()
except Exception:
    self.logger.exception("agent.run_failed", agent=self.name)
    raise
finally:
    lag_task.cancel()
    watchdog_task.cancel()
    for t in (lag_task, watchdog_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    await self._teardown()
    await self.stop()
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_base_agent.py -v
```

Expected: all pass.

- [ ] **Step 5: Add WatchdogSec to 15 pipeline unit files**

For each of these units, add `WatchdogSec=60` and `NotifyAccess=main` after `Restart=always`:

```
indicagent-ai-narrative  indicagent-bar-aggregator-compute  indicagent-bar-auditor
indicagent-bar-writer  indicagent-cross-asset  indicagent-feature-snapshot-writer
indicagent-feature-writer  indicagent-ibkr-provider  indicagent-intelligence-pipeline@
indicagent-llm-writer  indicagent-provider-merger  indicagent-roll-compute
indicagent-signal-tracker  indicagent-signal-writer  indicagent-api
```

Run:

```bash
for unit in indicagent-ai-narrative indicagent-bar-aggregator-compute indicagent-bar-auditor indicagent-bar-writer indicagent-cross-asset indicagent-feature-snapshot-writer indicagent-feature-writer indicagent-ibkr-provider "indicagent-intelligence-pipeline@" indicagent-llm-writer indicagent-provider-merger indicagent-roll-compute indicagent-signal-tracker indicagent-signal-writer indicagent-api; do
  f="/etc/systemd/system/${unit}.service"
  echo '!123Angelina' | /usr/bin/sudo.ws -S sed -i '/^Restart=always/a WatchdogSec=60\nNotifyAccess=main' "$f" && echo "Updated $f"
done
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl daemon-reload
```

- [ ] **Step 6: Copy updated files to production/systemd/ reference dir**

```bash
for unit in indicagent-ai-narrative indicagent-bar-aggregator-compute indicagent-bar-auditor indicagent-bar-writer indicagent-cross-asset indicagent-feature-snapshot-writer indicagent-feature-writer indicagent-ibkr-provider "indicagent-intelligence-pipeline@" indicagent-llm-writer indicagent-provider-merger indicagent-roll-compute indicagent-signal-tracker indicagent-signal-writer indicagent-api; do
  f="/etc/systemd/system/${unit}.service"
  dest="production/systemd/${unit}.service"
  cp "$f" "$dest" 2>/dev/null && echo "Copied $dest"
done
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt src/core/agent/base.py tests/unit/test_base_agent.py production/systemd/
git commit -m "feat(base-agent): add systemd watchdog notify; WatchdogSec=60 on all pipeline units"
```

---

## Task 4: Add `topic_health_events` to stream_keys.py

**Files:**
- Modify: `src/core/stream_keys.py`

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_stream_keys.py` (create if missing, otherwise append):

```python
from src.core.stream_keys import topic_health_events, topic_health_events_dlq


def test_topic_health_events_format():
    assert topic_health_events("dev") == "dev.system.health.events"
    assert topic_health_events("") == "system.health.events"


def test_topic_health_events_dlq_format():
    assert topic_health_events_dlq("") == "intelligence.service_auditor.journal.dlq"
```

Run:

```bash
.venv/bin/pytest tests/unit/test_stream_keys.py::test_topic_health_events_format -v
```

Expected: `FAILED`.

- [ ] **Step 2: Add functions to `src/core/stream_keys.py`**

Append after the last `topic_` function:

```python
def topic_health_events(env_name: str) -> str:
    """Service health state transitions published by ServiceAuditorAgent."""
    prefix = f"{env_name}." if env_name else ""
    return f"{prefix}system.health.events"


def topic_health_events_dlq(env_name: str) -> str:
    """DLQ for services that exceed the escalation restart threshold."""
    prefix = f"{env_name}." if env_name else ""
    return f"{prefix}intelligence.service_auditor.journal.dlq"
```

- [ ] **Step 3: Create the Kafka topic**

```bash
docker exec redpanda rpk topic create system.health.events --partitions 1 --replicas 1 -X brokers=localhost:9092
docker exec redpanda rpk topic alter-config system.health.events --set retention.ms=604800000
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/test_stream_keys.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/core/stream_keys.py tests/unit/test_stream_keys.py
git commit -m "feat(stream-keys): add topic_health_events and topic_health_events_dlq"
```

---

## Task 5: Create `service_health_events` Migration

**Files:**
- Create: `production/migrations/054_service_health_events.sql`

- [ ] **Step 1: Create migration file**

```sql
-- 054_service_health_events.sql
-- Applied: 2026-04-03
-- Purpose: Audit trail for ServiceAuditorAgent.
-- Every state transition is a labeled data sample for MTTR, failure pattern detection.

CREATE TABLE IF NOT EXISTS service_health_events (
    ts                   TIMESTAMPTZ      NOT NULL,
    service              TEXT             NOT NULL,
    event_type           TEXT             NOT NULL,  -- degraded|restart|recovered|escalated|heartbeat
    previous_state       TEXT,
    reason               TEXT,
    lag_messages         BIGINT,
    restart_count        INT,
    duration_degraded_s  DOUBLE PRECISION
);

SELECT create_hypertable('service_health_events', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_she_service_ts ON service_health_events (service, ts DESC);
CREATE INDEX IF NOT EXISTS idx_she_type_ts    ON service_health_events (event_type, ts DESC);

-- Verification:
-- SELECT ts, service, event_type, reason FROM service_health_events ORDER BY ts DESC LIMIT 5;
```

- [ ] **Step 2: Apply migration**

```bash
docker exec timescaledb psql -U postgres -d indicagent -f /dev/stdin < production/migrations/054_service_health_events.sql
```

Expected output includes `create_hypertable` success row.

- [ ] **Step 3: Verify**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c "\d service_health_events"
```

- [ ] **Step 4: Commit**

```bash
git add production/migrations/054_service_health_events.sql
git commit -m "feat(db): add service_health_events hypertable for auditor trail"
```

---

## Task 6: Implement ServiceAuditorAgent

**Files:**
- Create: `services/service_auditor_agent.py`
- Create: `tests/unit/service_tests/test_service_auditor_agent.py`

### Step 6a: Tests First

- [ ] **Step 1: Create `tests/unit/service_tests/test_service_auditor_agent.py`**

```python
"""Unit tests for ServiceAuditorAgent — TDD.

Uses __new__ pattern (service test convention) to bypass __init__.
Tests: registry completeness, DAG ordering, systemctl output parsing,
graduated response state machine, DB event schema.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_agent():
    from services.service_auditor_agent import ServiceAuditorAgent
    agent = ServiceAuditorAgent.__new__(ServiceAuditorAgent)
    agent.name = "service_auditor_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._env_name = ""
    agent._db_pool = AsyncMock()
    agent._kafka_producer = AsyncMock()
    agent._service_states = {}
    return agent


# ── Registry ──────────────────────────────────────────────────────────────────

def test_registry_covers_all_active_services():
    from services.service_auditor_agent import SERVICE_REGISTRY
    units = {s.unit for s in SERVICE_REGISTRY}
    required = {
        "indicagent-ibkr-provider", "indicagent-provider-merger",
        "indicagent-bar-aggregator-compute", "indicagent-bar-writer",
        "indicagent-bar-auditor", "indicagent-intelligence-pipeline@1",
        "indicagent-signal-tracker", "indicagent-signal-writer",
        "indicagent-ai-narrative", "indicagent-feature-writer",
        "indicagent-llm-writer", "indicagent-cross-asset",
    }
    assert not required - units, f"Missing: {required - units}"


def test_registry_dag_order_sources_before_sinks():
    from services.service_auditor_agent import SERVICE_REGISTRY
    by_unit = {s.unit: s.dag_order for s in SERVICE_REGISTRY}
    assert by_unit["indicagent-ibkr-provider"] < by_unit["indicagent-provider-merger"]
    assert by_unit["indicagent-provider-merger"] < by_unit["indicagent-bar-aggregator-compute"]
    assert by_unit["indicagent-bar-aggregator-compute"] < by_unit["indicagent-intelligence-pipeline@1"]
    assert by_unit["indicagent-intelligence-pipeline@1"] < by_unit["indicagent-feature-writer"]


# ── systemctl parsing ─────────────────────────────────────────────────────────

def test_parse_systemctl_show_active():
    from services.service_auditor_agent import _parse_systemctl_show
    active, sub = _parse_systemctl_show("ActiveState=active\nSubState=running\n")
    assert active == "active" and sub == "running"


def test_parse_systemctl_show_start_limit_hit():
    from services.service_auditor_agent import _parse_systemctl_show
    active, sub = _parse_systemctl_show("ActiveState=failed\nSubState=start-limit-hit\n")
    assert active == "failed" and sub == "start-limit-hit"


def test_parse_systemctl_show_empty():
    from services.service_auditor_agent import _parse_systemctl_show
    assert _parse_systemctl_show("") == ("unknown", "unknown")


# ── Graduated response ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_healthy_service_no_action():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()

    with MagicMock() as _:
        agent._emit_health_event = AsyncMock()
        agent._restart_service = AsyncMock()
        await agent._evaluate_service(spec, "active", "running", 0, True)
        agent._emit_health_event.assert_not_called()
        agent._restart_service.assert_not_called()


@pytest.mark.asyncio
async def test_dead_service_triggers_restart():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    await agent._evaluate_service(spec, "failed", "start-limit-hit", 0, False)
    agent._restart_service.assert_called_once_with(spec)


@pytest.mark.asyncio
async def test_high_lag_degrades_after_two_checks():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    agent._service_states["indicagent-bar-writer"] = ServiceState()
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    # First check — no emit yet, just increments counter
    await agent._evaluate_service(spec, "active", "running", 2000, True)
    agent._restart_service.assert_not_called()
    assert agent._service_states["indicagent-bar-writer"].degraded_check_count == 1

    # Second consecutive check — emits degraded event
    await agent._evaluate_service(spec, "active", "running", 2000, True)
    agent._restart_service.assert_not_called()
    assert agent._emit_health_event.call_count == 1
    assert agent._emit_health_event.call_args[1]["event_type"] == "degraded"


@pytest.mark.asyncio
async def test_escalates_after_three_restarts_in_window():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    now = datetime.now(UTC)
    state = ServiceState()
    state.restart_times = [
        now - timedelta(minutes=8),
        now - timedelta(minutes=5),
        now - timedelta(minutes=2),
    ]
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()
    agent._send_to_dlq = AsyncMock()

    await agent._evaluate_service(spec, "failed", "start-limit-hit", 0, False)

    agent._restart_service.assert_not_called()
    event_types = [c[1]["event_type"] for c in agent._emit_health_event.call_args_list]
    assert "escalated" in event_types


@pytest.mark.asyncio
async def test_recovery_emits_recovered_event_with_duration():
    from services.service_auditor_agent import ServiceSpec, ServiceState
    agent = _make_agent()
    spec = ServiceSpec("indicagent-bar-writer", 9121, 1000, 4, True)
    state = ServiceState()
    state.last_known_state = "degraded"
    state.degraded_since = datetime.now(UTC) - timedelta(seconds=120)
    agent._service_states["indicagent-bar-writer"] = state
    agent._emit_health_event = AsyncMock()
    agent._restart_service = AsyncMock()

    await agent._evaluate_service(spec, "active", "running", 0, True)

    agent._emit_health_event.assert_called_once()
    kwargs = agent._emit_health_event.call_args[1]
    assert kwargs["event_type"] == "recovered"
    assert kwargs["duration_degraded_s"] is not None
    assert kwargs["duration_degraded_s"] >= 100


# ── DB persistence ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_health_event_inserts_correct_schema():
    from services.service_auditor_agent import ServiceAuditorAgent
    agent = _make_agent()
    mock_conn = AsyncMock()
    agent._db_pool.acquire = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_conn),
        __aexit__=AsyncMock(return_value=False),
    ))
    agent._kafka_producer = AsyncMock()

    await agent._emit_health_event(
        service="indicagent-bar-writer",
        event_type="restart",
        previous_state="failed",
        reason="StartLimitHit",
        lag_messages=None,
        restart_count=1,
        duration_degraded_s=None,
    )

    mock_conn.execute.assert_called_once()
    sql_and_args = mock_conn.execute.call_args[0]
    assert "service_health_events" in sql_and_args[0]
    assert "indicagent-bar-writer" in sql_and_args
    assert "restart" in sql_and_args
```

- [ ] **Step 2: Run to confirm all fail**

```bash
.venv/bin/pytest tests/unit/service_tests/test_service_auditor_agent.py -v
```

Expected: all `FAILED` — module doesn't exist.

### Step 6b: Implementation

- [ ] **Step 3: Create `services/service_auditor_agent.py`**

Note: this file uses `asyncio.create_subprocess_exec` which is the safe, shell-injection-free
subprocess API (equivalent to Node.js `execFile`). Each command is passed as a separate argument,
never interpolated into a shell string.

```python
"""ServiceAuditorAgent — pipeline health monitor and self-healer.

Hybrid three-layer design:
  systemd  → process liveness (WatchdogSec kills hung processes)
  Prometheus → metrics/lag (15s check cycle via /api/v1/query)
  This agent → intelligence: graduated response, DAG-ordered restarts, audit trail

Graduated response policy:
  HEALTHY   no action
  DEGRADED  lag > threshold, 2 consecutive checks → emit degraded event
  RESTART   dead/failed/StartLimitHit → reset-failed + start → emit restart event
  ESCALATE  3 restarts in 10 min → DLQ + stop retrying → emit escalated event
  RECOVERED returns healthy → emit recovered event with duration_degraded_s

Every state transition is persisted to service_health_events (TimescaleDB) and
published to system.health.events (Kafka) — both are permanent audit trails.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiohttp
import asyncpg

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaProducerClient
from src.core.stream_keys import topic_health_events, topic_health_events_dlq

_ESCALATION_WINDOW = timedelta(minutes=10)
_ESCALATION_THRESHOLD = 3
_PROMETHEUS_URL = "http://localhost:9090/api/v1/query"


# ---------------------------------------------------------------------------
# Service registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ServiceSpec:
    unit: str
    metrics_port: int | None
    lag_threshold_messages: int   # 0 = not a Kafka consumer
    dag_order: int                # lower = restart first
    market_hours_only: bool


SERVICE_REGISTRY: list[ServiceSpec] = [
    ServiceSpec("indicagent-ibkr-provider",          9129,  0,    1, False),
    ServiceSpec("indicagent-provider-merger",         9130,  500,  2, True),
    ServiceSpec("indicagent-bar-aggregator-compute",  9120,  500,  3, True),
    ServiceSpec("indicagent-bar-auditor",             9123,  200,  3, True),
    ServiceSpec("indicagent-bar-writer",              9121,  1000, 4, True),
    ServiceSpec("indicagent-intelligence-pipeline@1", 9125,  500,  5, True),
    ServiceSpec("indicagent-feature-writer",          9116,  1000, 6, True),
    ServiceSpec("indicagent-signal-tracker",          9115,  500,  6, True),
    ServiceSpec("indicagent-signal-writer",           9119,  500,  6, True),
    ServiceSpec("indicagent-ai-narrative",            9113,  200,  7, True),
    ServiceSpec("indicagent-llm-writer",              9117,  500,  7, True),
    ServiceSpec("indicagent-cross-asset",             9118,  200,  7, True),
]

# Maps persistence_consumer_lag agent_id label → systemd unit name
_AGENT_ID_TO_UNIT: dict[str, str] = {
    "bar_writer_agent":             "indicagent-bar-writer",
    "bar_aggregator_agent":         "indicagent-bar-aggregator-compute",
    "intelligence_pipeline_agent":  "indicagent-intelligence-pipeline@1",
    "feature_writer_agent":         "indicagent-feature-writer",
    "signal_tracker_agent":         "indicagent-signal-tracker",
    "signal_writer_agent":          "indicagent-signal-writer",
    "ai_narrative_service":         "indicagent-ai-narrative",
    "llm_writer_service":           "indicagent-llm-writer",
    "cross_asset_service":          "indicagent-cross-asset",
    "bar_auditor_agent":            "indicagent-bar-auditor",
    "provider_merger_agent":        "indicagent-provider-merger",
}


# ---------------------------------------------------------------------------
# Per-service runtime state
# ---------------------------------------------------------------------------

@dataclass
class ServiceState:
    degraded_since: datetime | None = None
    degraded_check_count: int = 0
    restart_times: list[datetime] = field(default_factory=list)
    escalated: bool = False
    last_known_state: str = "healthy"


# ---------------------------------------------------------------------------
# Pure helpers (no I/O — easily unit-testable)
# ---------------------------------------------------------------------------

def _parse_systemctl_show(output: str) -> tuple[str, str]:
    """Parse 'systemctl show --property=ActiveState,SubState' stdout."""
    props: dict[str, str] = {}
    for line in output.strip().splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props.get("ActiveState", "unknown"), props.get("SubState", "unknown")


def _agent_id_to_unit(agent_id: str) -> str | None:
    return _AGENT_ID_TO_UNIT.get(agent_id)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ServiceAuditorAgent(BaseAgent):
    """Monitors all pipeline services, self-heals, and audits every event."""

    def __init__(self) -> None:
        settings = Settings()
        super().__init__(name="service_auditor_agent", metrics_port=9131)
        self._settings = settings
        self._env_name: str = getattr(settings, "env_prefix", "") or ""
        self._db_pool: asyncpg.Pool | None = None
        self._kafka_producer: KafkaProducerClient | None = None
        self._service_states: dict[str, ServiceState] = {
            s.unit: ServiceState() for s in SERVICE_REGISTRY
        }
        self._prometheus_check_interval = 15
        self._systemd_check_interval = 30
        self._heartbeat_interval = 60

    @property
    def topics_produced(self) -> list[str]:
        return [
            topic_health_events(self._env_name),
            topic_health_events_dlq(self._env_name),
        ]

    async def _setup(self) -> None:
        self._db_pool = await asyncpg.create_pool(
            self._settings.database_url, min_size=1, max_size=3
        )
        self._kafka_producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            topics_produced=self.topics_produced,
        )
        await self._kafka_producer.start()
        self.logger.info(
            "service_auditor_agent.setup_complete",
            services=len(SERVICE_REGISTRY),
            env=self._env_name,
        )

    async def _teardown(self) -> None:
        if self._kafka_producer:
            await self._kafka_producer.stop()
        if self._db_pool:
            await self._db_pool.close()

    async def _run(self) -> None:
        prom_task = asyncio.create_task(self._prometheus_check_loop())
        sysd_task = asyncio.create_task(self._systemd_check_loop())
        hb_task   = asyncio.create_task(self._heartbeat_loop())
        await self._stop_event.wait()
        for t in (prom_task, sysd_task, hb_task):
            t.cancel()
        for t in (prom_task, sysd_task, hb_task):
            try:
                await t
            except asyncio.CancelledError:
                pass

    # ── Check loops ──────────────────────────────────────────────────────────

    async def _prometheus_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._prometheus_check_interval)
            try:
                health_set = await self._fetch_prometheus_health()
                lag_map    = await self._fetch_prometheus_lag()
                for spec in sorted(SERVICE_REGISTRY, key=lambda s: s.dag_order):
                    has_metrics = spec.unit in health_set
                    lag = lag_map.get(spec.unit, 0)
                    active = "active" if has_metrics else "unknown"
                    sub    = "running" if has_metrics else "no_metrics"
                    await self._evaluate_service(spec, active, sub, lag, has_metrics)
            except Exception as exc:
                self.logger.error("service_auditor.prometheus_check_failed", error=str(exc))

    async def _systemd_check_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._systemd_check_interval)
            try:
                for spec in sorted(SERVICE_REGISTRY, key=lambda s: s.dag_order):
                    active, sub = await self._check_systemd_state(spec.unit)
                    if active in ("failed", "inactive") or sub == "start-limit-hit":
                        await self._evaluate_service(spec, active, sub, 0, False)
            except Exception as exc:
                self.logger.error("service_auditor.systemd_check_failed", error=str(exc))

    async def _heartbeat_loop(self) -> None:
        while self.running:
            await asyncio.sleep(self._heartbeat_interval)
            try:
                await self._emit_health_event(
                    service="service_auditor_agent",
                    event_type="heartbeat",
                    previous_state="healthy",
                    reason=None,
                    lag_messages=None,
                    restart_count=None,
                    duration_degraded_s=None,
                )
            except Exception as exc:
                self.logger.error("service_auditor.heartbeat_failed", error=str(exc))

    # ── Graduated response ────────────────────────────────────────────────────

    async def _evaluate_service(
        self,
        spec: ServiceSpec,
        active_state: str,
        sub_state: str,
        lag_messages: int,
        has_metrics: bool,
    ) -> None:
        state = self._service_states[spec.unit]
        if state.escalated:
            return

        is_dead  = active_state in ("failed", "inactive") or sub_state == "start-limit-hit"
        is_laggy = spec.lag_threshold_messages > 0 and lag_messages > spec.lag_threshold_messages

        # ── RESTART ────────────────────────────────────────────────────────
        if is_dead:
            now = datetime.now(UTC)
            state.restart_times = [t for t in state.restart_times if now - t < _ESCALATION_WINDOW]

            if len(state.restart_times) >= _ESCALATION_THRESHOLD:
                state.escalated = True
                duration = (
                    (now - state.degraded_since).total_seconds()
                    if state.degraded_since else None
                )
                await self._emit_health_event(
                    service=spec.unit, event_type="escalated",
                    previous_state=state.last_known_state,
                    reason=f"{active_state}/{sub_state}",
                    lag_messages=None, restart_count=len(state.restart_times),
                    duration_degraded_s=duration,
                )
                await self._send_to_dlq(
                    {"service": spec.unit, "restart_count": len(state.restart_times)},
                    Exception("escalation threshold reached"),
                )
                self.logger.error("service_auditor.escalated", service=spec.unit)
                return

            if not state.degraded_since:
                state.degraded_since = now
            state.restart_times.append(now)
            await self._emit_health_event(
                service=spec.unit, event_type="restart",
                previous_state=state.last_known_state,
                reason=f"{active_state}/{sub_state}",
                lag_messages=None, restart_count=len(state.restart_times),
                duration_degraded_s=None,
            )
            state.last_known_state = "restarting"
            await self._restart_service(spec)
            return

        # ── DEGRADED ───────────────────────────────────────────────────────
        if is_laggy:
            if not state.degraded_since:
                state.degraded_since = datetime.now(UTC)
            state.degraded_check_count += 1
            if state.degraded_check_count >= 2:
                await self._emit_health_event(
                    service=spec.unit, event_type="degraded",
                    previous_state=state.last_known_state,
                    reason=f"lag={lag_messages}>{spec.lag_threshold_messages}",
                    lag_messages=lag_messages, restart_count=len(state.restart_times),
                    duration_degraded_s=None,
                )
                state.last_known_state = "degraded"
            return

        # ── RECOVERED ──────────────────────────────────────────────────────
        if state.last_known_state in ("degraded", "restarting"):
            duration = (
                (datetime.now(UTC) - state.degraded_since).total_seconds()
                if state.degraded_since else None
            )
            await self._emit_health_event(
                service=spec.unit, event_type="recovered",
                previous_state=state.last_known_state,
                reason=None,
                lag_messages=lag_messages, restart_count=len(state.restart_times),
                duration_degraded_s=duration,
            )

        state.degraded_since = None
        state.degraded_check_count = 0
        state.last_known_state = "healthy"

    # ── systemd interface ─────────────────────────────────────────────────────

    async def _check_systemd_state(self, unit: str) -> tuple[str, str]:
        """Query systemd unit state. Uses subprocess list args (no shell injection)."""
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "show", unit,
            "--property=ActiveState,SubState",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        return _parse_systemctl_show(stdout.decode())

    async def _restart_service(self, spec: ServiceSpec) -> None:
        """reset-failed clears StartLimitBurst; start re-launches the unit."""
        self.logger.warning("service_auditor.restarting", service=spec.unit)
        for args in (
            ["systemctl", "reset-failed", spec.unit],
            ["systemctl", "start",        spec.unit],
        ):
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                self.logger.error(
                    "service_auditor.restart_cmd_failed",
                    args=args, stderr=stderr.decode().strip(),
                )

    # ── Prometheus interface ───────────────────────────────────────────────────

    async def _fetch_prometheus_health(self) -> set[str]:
        results = await self._query_prometheus("indicagent_service_health > 0")
        return {r["metric"].get("service", "") for r in results}

    async def _fetch_prometheus_lag(self) -> dict[str, int]:
        results = await self._query_prometheus("persistence_consumer_lag")
        out: dict[str, int] = {}
        for r in results:
            unit = _agent_id_to_unit(r["metric"].get("agent_id", ""))
            if unit:
                out[unit] = int(float(r["value"][1]))
        return out

    async def _query_prometheus(self, query: str) -> list[dict]:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _PROMETHEUS_URL,
                params={"query": query},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
        return data.get("data", {}).get("result", [])

    # ── Persistence ────────────────────────────────────────────────────────────

    async def _emit_health_event(
        self,
        service: str,
        event_type: str,
        previous_state: str | None,
        reason: str | None,
        lag_messages: int | None,
        restart_count: int | None,
        duration_degraded_s: float | None,
    ) -> None:
        now = datetime.now(UTC)
        self.logger.info(
            "service_auditor.event",
            service=service, event_type=event_type, reason=reason,
        )
        async with self._db_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO service_health_events
                  (ts, service, event_type, previous_state, reason,
                   lag_messages, restart_count, duration_degraded_s)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                now, service, event_type, previous_state, reason,
                lag_messages, restart_count, duration_degraded_s,
            )
        await self._kafka_producer.publish(
            topic_health_events(self._env_name),
            key=service,
            value={
                "ts": now.isoformat(),
                "service": service,
                "event_type": event_type,
                "previous_state": previous_state,
                "reason": reason,
                "lag_messages": lag_messages,
                "restart_count": restart_count,
                "duration_degraded_s": duration_degraded_s,
            },
        )

    async def _send_to_dlq(self, payload: dict, error: Exception) -> None:
        self.logger.error(
            "service_auditor.dlq",
            service=payload.get("service"), error=str(error),
        )
        await self._kafka_producer.publish(
            topic_health_events_dlq(self._env_name),
            key=payload.get("service", "unknown"),
            value=payload,
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio
    from src.core.service_utils import setup_service_logging
    setup_service_logging("logs/service_auditor_agent.log")
    asyncio.run(ServiceAuditorAgent().start())
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/service_tests/test_service_auditor_agent.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/service_auditor_agent.py tests/unit/service_tests/test_service_auditor_agent.py
git commit -m "feat(service-auditor): ServiceAuditorAgent — graduated response, DAG restarts, audit trail"
```

---

## Task 7: Install Systemd Unit

**Files:**
- Create: `/etc/systemd/system/indicagent-service-auditor.service`

- [ ] **Step 1: Write and install unit file**

```bash
cat > /tmp/indicagent-service-auditor.service << 'EOF'
[Unit]
Description=IndicAgent Service Auditor — pipeline health monitor and self-healer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=METRICS_PORT=9131
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/service_auditor_agent.py
Restart=always
RestartSec=10
WatchdogSec=120
NotifyAccess=main
StartLimitIntervalSec=0
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-service-auditor
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF

echo '!123Angelina' | /usr/bin/sudo.ws -S cp /tmp/indicagent-service-auditor.service /etc/systemd/system/
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl daemon-reload
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl enable indicagent-service-auditor
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl start indicagent-service-auditor
```

- [ ] **Step 2: Verify running**

```bash
echo '!123Angelina' | /usr/bin/sudo.ws -S systemctl status indicagent-service-auditor --no-pager
```

Expected: `active (running)`.

```bash
sleep 5 && tail -20 /home/bg/dev/indicagent/logs/service_auditor_agent.log
```

Expected: `service_auditor_agent.setup_complete` with `services=12`.

- [ ] **Step 3: Verify Prometheus scraping**

```bash
sleep 20 && curl -s http://localhost:9090/api/v1/targets | python3 -c "
import json, sys
[print(t['labels']['job'], t['health'])
 for t in json.load(sys.stdin)['data']['activeTargets']
 if 'auditor' in t['labels'].get('job','')]
"
```

Expected: `indicagent-service-auditor up`.

- [ ] **Step 4: Copy to reference dir and commit**

```bash
cp /etc/systemd/system/indicagent-service-auditor.service production/systemd/
git add production/systemd/indicagent-service-auditor.service
git commit -m "feat(systemd): install and enable indicagent-service-auditor.service"
```

---

## Task 8: End-to-End Verification

- [ ] **Step 1: Full unit test suite — no regressions**

```bash
.venv/bin/pytest tests/unit/ -v --tb=short 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 2: Confirm heartbeats flowing on Kafka**

```bash
sleep 65 && docker exec redpanda rpk topic consume system.health.events --offset start -n 3 2>/dev/null
```

Expected: JSON records with `event_type: "heartbeat"`.

- [ ] **Step 3: Confirm DB recording events**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT ts, service, event_type FROM service_health_events ORDER BY ts DESC LIMIT 10;"
```

- [ ] **Step 4: Lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

- [ ] **Step 5: Final commit**

```bash
git add -u && git commit -m "chore: lint fixes post service-auditor"
```

---

## Self-Review

**Spec coverage:**
- ✅ Bar aggregator consumer reset fix (Task 1)
- ✅ Prometheus scrape config fixed, all 11 services (Task 2)
- ✅ WatchdogSec + sdnotify in BaseAgent + all 15 unit files (Task 3)
- ✅ topic_health_events + DLQ topic in stream_keys (Task 4)
- ✅ service_health_events hypertable (Task 5)
- ✅ ServiceAuditorAgent: registry, graduated response, DAG ordering, Kafka/DB persistence (Task 6)
- ✅ system.health.events Kafka topic created (Task 4 Step 3)
- ✅ Systemd unit with StartLimitIntervalSec=0 (Task 7)
- ✅ DLQ path for escalated services (Task 6 _send_to_dlq)
- ✅ Auditor heartbeat for self-monitoring (Task 6 _heartbeat_loop)

**Grafana dashboard panel** is intentionally deferred — new Prometheus targets auto-appear;
a dedicated `service_health_events` SQL panel is low-priority and can be added in a future session.
