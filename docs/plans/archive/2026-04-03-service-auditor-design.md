# Service Auditor — Design Doc

**Date:** 2026-04-03
**Status:** Approved
**Author:** Brandon

---

## Problem

18 systemd services run the IndicAgent pipeline. The current recovery model is:

- `Restart=always` + `StartLimitBurst=5` in every unit — after 5 crashes in 300s, systemd stops retrying and the service stays dead until manual `systemctl reset-failed && start`
- One service (bar aggregator) has a broken self-heal: its consumer reset calls `stop()`/`start()` from a background health checker while the main loop holds the consumer open, causing a "Did you call start twice?" race condition
- Prometheus is running but scraping only 3 of 11 active services; 8 services expose `/metrics` that nobody reads
- Nothing monitors the pipeline as a whole — a dead `bar-aggregator` silently starves `intelligence-pipeline` without any cross-service awareness

Jim Simons' demand: **no manual intervention in steady state, every failure is a labeled data sample**.

---

## Design Overview

Three layers, each doing what it does best:

| Layer | Responsibility | Implementation |
|-------|---------------|----------------|
| **systemd** | Process liveness — kill hung processes | `WatchdogSec` + `sd_notify` in `BaseAgent` |
| **Prometheus** | Metrics/lag — is the service producing output? | Fix scrape config; all 11 services already expose `/metrics` |
| **`ServiceAuditorAgent`** | Intelligence — graduated response, DAG ordering, audit trail | New agent + service |

---

## Component 1: Fix Prometheus Scrape Config

The Prometheus config points at 3 dead service names (`indicagent-indicator`, `indicagent-market-analysis`, `indicagent-signal-generator`) and omits 8 running services.

**New scrape targets** (all via `host.docker.internal`):

| Service | Port |
|---------|------|
| indicagent-ibkr-provider | 9129 |
| indicagent-provider-merger | 9130 |
| indicagent-bar-aggregator-compute | 9120 |
| indicagent-bar-writer | 9121 |
| indicagent-bar-auditor | 9123 |
| indicagent-intelligence-pipeline | 9125 |
| indicagent-signal-tracker | 9115 |
| indicagent-ai-narrative | 9113 |
| indicagent-feature-writer | 9116 |
| indicagent-llm-writer | 9117 |
| indicagent-cross-asset | 9118 |

Remove dead jobs. Prometheus config lives at `production/monitoring/prometheus.yml` (or wherever Docker Compose mounts it).

---

## Component 2: systemd WatchdogSec

Each service gets a hardware watchdog: if the process goes silent (hung event loop, deadlock), systemd kills and restarts it automatically.

**`BaseAgent.start()`** gains a background task:
```python
async def _watchdog_notify(self) -> None:
    """Notify systemd watchdog every WATCHDOG_USEC/2 microseconds."""
    import os
    interval_s = int(os.getenv("WATCHDOG_USEC", "0")) / 2_000_000
    if interval_s <= 0:
        return
    import sdnotify
    n = sdnotify.SystemdNotifier()
    while self.running:
        n.notify("WATCHDOG=1")
        await asyncio.sleep(interval_s)
```

**All unit files** gain two lines in `[Service]`:
```ini
WatchdogSec=60
NotifyAccess=main
```

If `WATCHDOG_USEC` is not set (e.g. in tests, direct run), the watchdog task is a no-op.

**Dependency:** `sdnotify` added to `requirements.txt`.

---

## Component 3: ServiceAuditorAgent

### Naming
| Layer | Value |
|-------|-------|
| File | `services/service_auditor_agent.py` |
| Class | `ServiceAuditorAgent` |
| Unit | `indicagent-service-auditor.service` |
| Port | `:9131` |
| Log | `logs/service_auditor_agent.log` |
| Consumer group | `service_auditor_consumer` |
| Kafka output | `system.health.events` |
| DLQ | `intelligence.service_auditor.journal.dlq` |

### Check Loop (every 15s)

**Prometheus check** — query `/api/v1/query` for:
- `indicagent_service_health{service="<name>"}` — 0 = unhealthy (service reports it)
- `persistence_consumer_lag{agent_id="<name>"}` > threshold
- `rate(bar_to_intelligence_latency_seconds_count[2m]) == 0` while market is open

**systemd check** (every 30s) — query D-Bus (via `dbus-python` or subprocess `systemctl show`) for all `indicagent-*` units:
- `ActiveState`: `failed`, `inactive` (when it should be active)
- `SubState`: `start-limit-hit`

systemd check is the critical one — a dead process emits no Prometheus metrics, so Prometheus alone has a blind spot.

### Service Registry

A static registry in the agent maps each service to its metadata:

```python
@dataclass
class ServiceSpec:
    unit: str                         # systemd unit name
    metrics_port: int
    lag_threshold_messages: int       # 0 = not a Kafka consumer
    dag_order: int                    # restart priority (lower = restart first)
    market_hours_only: bool           # suppress alerts outside RTH/ETH
```

DAG order derived from pipeline topology:
1. `ibkr-provider` (source)
2. `provider-merger`
3. `bar-aggregator-compute`, `bar-auditor`
4. `bar-writer`
5. `intelligence-pipeline`
6. `feature-writer`, `signal-tracker`, `signal-writer`
7. `ai-narrative`, `llm-writer`, `cross-asset`

### Graduated Response Policy

```
HEALTHY   → no action
DEGRADED  → lag > threshold for 2 consecutive checks
              → log warning, emit health event, update Prometheus gauge
RESTART   → service dead/failed/StartLimitHit
              → systemctl reset-failed <unit> && systemctl start <unit>
              → emit health event with restart_count
              → DAG-ordered: restart dependencies before dependents
ESCALATE  → 3 restarts within 10 minutes
              → publish to DLQ, stop retrying, emit escalation event
RECOVERED → service returns to healthy after DEGRADED or RESTART
              → emit recovery event with duration_degraded_s
```

Restarts use `reset-failed` before `start` to clear the `StartLimitBurst` counter — this is the critical step that the current model misses entirely.

### Kafka Output Schema

Every state transition emits to `system.health.events`:

```json
{
  "ts": "2026-04-03T14:00:00Z",
  "service": "indicagent-bar-aggregator-compute",
  "event_type": "restart",
  "previous_state": "failed",
  "reason": "StartLimitHit",
  "lag_messages": null,
  "restart_count": 1,
  "duration_degraded_s": 45.2
}
```

`event_type` values: `degraded`, `restart`, `recovered`, `escalated`

### Self-Monitoring

The auditor unit has:
```ini
Restart=always
RestartSec=10
# No StartLimitBurst — auditor must always come back
StartLimitIntervalSec=0
```

The auditor publishes its own heartbeat to `system.health.events` every 60s (`event_type: heartbeat`). If heartbeats stop, that's detectable by any consumer downstream.

---

## Component 4: `service_health_events` TimescaleDB Hypertable

```sql
CREATE TABLE service_health_events (
    ts              TIMESTAMPTZ NOT NULL,
    service         TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- degraded|restart|recovered|escalated|heartbeat
    previous_state  TEXT,
    reason          TEXT,
    lag_messages    BIGINT,
    restart_count   INT,
    duration_degraded_s DOUBLE PRECISION
);

SELECT create_hypertable('service_health_events', 'ts');
CREATE INDEX ON service_health_events (service, ts DESC);
```

Every row is a labeled training sample. Future queries:
- MTTR per service
- Failure rate by time-of-day
- Correlated failures (does bar-aggregator death predict intelligence-pipeline death within 60s?)
- Flapping detection (restart_count > 3 in a rolling window)

Retention: keep forever (storage is cheap, failure patterns are signal).

---

## Component 5: Fix Bar Aggregator Consumer Reset Race

The existing `_handle_unhealthy_state` calls `stop()`/`start()` from the health checker background task while the main loop's `async for` holds the consumer open. This causes `"Did you call start twice?"`.

**Fix:** `_handle_unhealthy_state` only sets `_consumer_restart_needed = True`. The outer `while self.running:` loop performs the actual `stop()`/`start()` after `async for` has exited cleanly.

This is a prerequisite for the auditor — otherwise the auditor restarts a service that immediately re-enters a broken recovery loop.

---

## Out of Scope

- Alertmanager / PagerDuty — separate operational concern
- Per-service custom health logic — auditor reads published metrics only
- Kubernetes / HPA — systemd process management per architecture principles
- Watching the watcher recursively — accepted single point of failure; systemd handles auditor liveness

---

## Implementation Order

1. Fix bar aggregator consumer reset (bug, prerequisite)
2. Add `sdnotify` dependency + `WatchdogSec` to BaseAgent and all unit files
3. Fix Prometheus scrape config (Docker Compose / prometheus.yml)
4. Create `service_health_events` migration
5. Create `system.health.events` Kafka topic
6. Implement `ServiceAuditorAgent` (registry → check loop → graduated response → persistence)
7. Install + enable `indicagent-service-auditor.service`
8. Update Grafana dashboard with service health panel
