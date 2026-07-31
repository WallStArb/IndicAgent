# Self-Healing Architecture

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-07-31
**Tags:** self-healing, otel, watchdog, circuit-breaker, alerting, phase-108
**Phase:** 108 — Self-Healing Hardening (complete)

---

## Overview

IndicAgent implements a comprehensive self-healing architecture that automatically detects and recovers from service failures, consumer stalls, DLQ poison pills, and database connectivity issues. All health signals flow through OpenTelemetry (OTel) to Prometheus and Grafana, enabling automated recovery and alerting.

**Core principle:** OTel is the single health measurement layer. Every service emits OTel → OTel Collector → Prometheus → Grafana. No parallel health event publishing to Kafka for monitoring purposes.

---

## OTel Health Contract

Every daemon service inheriting from `BaseDaemon` (renamed from `BaseAgent` during the v3.0
rebuild — see `docs/agents/agents-foundation.md`'s Naming note) MUST emit these five signals.
This is code-review enforced — new agents that don't inherit `BaseDaemon` are rejected.

### Mandatory Signals (inherited from BaseDaemon)

**Label correction 2026-07-31:** `agent_crash_total`'s label key is `agent`, not `agent_id` —
verified against `src/core/agent/base.py`'s `_crash_attrs = {"agent": self._agent_label}`. This
also affects CLAUDE.md's OTel Health Contract section, which states all five signals use
`agent_id`; that is out of scope to fix here (CLAUDE.md is not under `docs/`) but is a real
discrepancy worth correcting separately.

| Signal | Type | Labels | Purpose |
|--------|------|--------|---------|
| `agent_last_message_timestamp_seconds` | Gauge | `agent_id` | Liveness; Unix timestamp of last processed message. Stale > 120s → stall detection |
| `agent_crash_total` | Counter | `agent` | Uncaught exceptions in `_run()` |
| `agent_dlq_total` | Counter | `agent_id` | DLQ routing events |
| `watchdog_notify_total` | Counter | `agent_id` | Successful sd_notify WATCHDOG=1 pings |
| `watchdog_notify_suppressed_total` | Counter | `agent_id` | Suppressed pings (agent alive but idle/stalled) |

### Oneshot Contract (timer-triggered scripts)

Timer-triggered services (ml-training, roll-batch, shadow-auditor) MUST emit at script exit:

```python
JOB_COMPLETED_TOTAL.add(1, {"job": "ml-training", "status": "success"})  # or "failure"
flush_and_shutdown_metrics(timeout_millis=5000)
```

- `job` label MUST match systemd unit `%n` suffix exactly (kebab-case)
- `status` is `"success"` or `"failure"`
- OTel flush MUST be called in finally block before exit

**Source:** `src/observability/metrics.py` — `JOB_COMPLETED_TOTAL` counter definition

---

## Systemd Watchdog Integration

All 27 daemon services run with `WatchdogSec=60` and `NotifyAccess=main` in their systemd unit files.

### Unit File Pattern

```ini
[Service]
WatchdogSec=60
NotifyAccess=main
```

When a service stalls (no message processed for 60s), systemd auto-restarts it.

### Watchdog Implementation

`BaseDaemon._watchdog_notify()` (renamed from `BaseAgent`) implements sd_notify correctly:

**Corrected 2026-07-31:** the suppress threshold below was previously `interval_s * 2`. That
formula had a real bug, fixed in the current code: for a service with `max_idle_seconds=300`,
`interval_s * 2` (~120s at a typical `WatchdogSec=60`) is *less* than `max_idle_seconds`, so
systemd's `WatchdogSec` killed the process after only 120s of idle — before `_stall_watchdog()`
(which waits the full 300s) ever got to fire its own, more graceful `sys.exit(1)`. The fix clamps
the suppress threshold to be at least `max_idle_seconds`:

```python
async def _watchdog_notify(self) -> None:
    socket_path = os.getenv("NOTIFY_SOCKET", "")
    usec = int(os.getenv("WATCHDOG_USEC", "0"))
    if not socket_path or usec <= 0:
        return
    import sdnotify
    notifier = sdnotify.SystemdNotifier()
    interval_s = usec / 2_000_000  # Ping at half watchdog interval
    # Suppress threshold must be >= max_idle_seconds so _stall_watchdog fires first.
    stale_threshold = max(self.max_idle_seconds, interval_s * 2)
    while self.running:
        should_notify = True
        if self.max_idle_seconds > 0 and self._last_message_ts is not None:
            should_notify = (time.monotonic() - self._last_message_ts) < stale_threshold
        if should_notify:
            notifier.notify("WATCHDOG=1")
            WATCHDOG_NOTIFY_TOTAL.add(1, self._last_msg_ts_attrs)
        else:
            WATCHDOG_NOTIFY_SUPPRESSED_TOTAL.add(1, self._last_msg_ts_attrs)
        await asyncio.sleep(interval_s)
```

**Source:** `src/core/agent/base.py`

### Excluded Services

- `indicagent-dashboard` — Next.js has no sd_notify; `Restart=always` is sufficient
- All oneshot units (Type=oneshot) — WatchdogSec does not apply

---

## Consumer Stall Detection

`ServiceAuditor` monitors all services for stalled consumers and triggers restarts.

### Detection Logic

```python
# In ServiceAuditor
_STALL_THRESHOLD_SECONDS = 120  # Lowered from 360 in Phase 108

async def _fetch_stalled_agents(self) -> list[str]:
    """Query Prometheus for services with stale agent_last_message_timestamp_seconds"""
    stale_services = []
    for service in self._monitored_services:
        last_msg_ts = self._prometheus.query(
            f'agent_last_message_timestamp_seconds{{agent_id="{service}"}}'
        )
        if time.time() - last_msg_ts > self._STALL_THRESHOLD_SECONDS:
            stale_services.append(service)
            CONSUMER_STALL_DETECTED_TOTAL.add(1, {"unit": service})
    return stale_services
```

### Recovery Flow

1. ServiceAuditor detects stale `agent_last_message_timestamp_seconds`
2. Increments `consumer_stall_detected_total{unit="service-name"}`
3. Calls `systemctl restart service-name`
4. Systemd watchdog would also restart at 60s mark (dual protection)

---

## DLQ Quarantine

Poison pill detection prevents infinite retry loops from hiding behind silence.

### Quarantine Logic

`DLQDrainAgent` tracks occurrence count per `(agent, source_topic, error_type)` in `dlq_events` table:

```python
DLQ_MAX_RETRIES = 3

async def _drain_message(self, msg: DLQPayload) -> None:
    key = (msg.agent, msg.source_topic, msg.error_type)
    count_24h = await self._count_recent_errors(key, hours=24)

    if count_24h >= DLQ_MAX_RETRIES:
        # Mark quarantined in DB
        await self._mark_quarantined(msg)
        DLQ_QUARANTINE_TOTAL.add(1, {
            "agent": msg.agent,
            "source_topic": msg.source_topic,
            "error_type": msg.error_type
        })
        return  # Don't retry

    # Attempt retry...
```

### DB Schema

`dlq_events` table has `quarantined BOOLEAN DEFAULT FALSE` column (added in migration 099).

Quarantined messages:
- Have `quarantined=TRUE`
- Are excluded from retry processing
- Persist for audit trail

---

## FastAPI Health Instrumentation

The `indicagent-api` service emits OTel signals for DB connectivity.

### Auto-Instrumentation

```python
# src/api/main.py
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

FastAPIInstrumentor.instrument_app(app)
```

### Custom Health Gauge

```python
# src/api/routes/health.py
@router.get("/database")
async def check_database():
    try:
        await db_pool.fetchval("SELECT 1")
        API_HEALTH.set(1, {"service": "indicagent-api"})
        return {"status": "healthy"}
    except Exception:
        API_HEALTH.set(0, {"service": "indicagent-api"})
        raise HTTPException(status_code=503, detail="Database unreachable")
```

---

## Circuit Breaker Alerting

Plugin-level circuit breakers prevent cascading failures.

### CB State Gauge

```python
# src/observability/circuit_breaker.py
intelligence_pipeline_plugin_cb_state = gauge(
    "intelligence_pipeline_plugin_cb_state",
    "Plugin circuit breaker state: 0=closed, 1=open, 2=half-open"
)
```

Labels: `{"plugin": plugin_name}`

### CB Transition Logging

When a CB transitions to OPEN, `IntelligencePipelineAgent` emits a structured log:

```python
if cb.state == CircuitBreakerState.OPEN:
    if plugin_id not in self._cb_open_reported:
        logger.info(
            "intelligence_pipeline.cb_open",
            plugin_id=plugin_id,
            failure_count=cb.failure_count
        )
        self._cb_open_reported.add(plugin_id)
```

No Kafka publish — OTel gauge is the signal, Grafana alert fires when gauge > 0.

---

## End-to-End Latency Tracking

`IntelligencePipeline` tracks bar arrival → signal enqueue latency.

### Histogram

```python
BAR_E2E_LATENCY_MS = histogram(
    "bar_e2e_latency_ms",
    "End-to-end latency from bar arrival to signal enqueue"
)

# In pipeline loop
bar_start = time.time()
# ... process bar ...
latency_ms = (time.time() - bar_start) * 1000
BAR_E2E_LATENCY_MS.record(latency_ms, {"symbol": bar.symbol, "tf": bar.timeframe})
```

---

## Grafana SLO Alerts

All alerts fire from Grafana on Prometheus metrics.

| Alert | Metric | Condition | Severity | Action |
|-------|--------|-----------|----------|--------|
| Service Stall | `agent_last_message_timestamp_seconds` | stale > 120s | critical | Systemd auto-restart |
| Watchdog Suppression | `watchdog_notify_suppressed_total` | rate > 0 | warning | Fix NotifyAccess=main |
| DLQ Quarantine | `dlq_quarantine_total` | rate > 0 | warning | Investigate poison pill |
| API Health Down | `api_health{service="indicagent-api"}` | < 1 | critical | Investigate DB |
| Oneshot Failure | `job_completed_total{status="failure"}` | increment > 0 | warning | Manual intervention |
| BPS Degradation | `rate(bars_processed_total[5m])` | drops > 50% | warning | Investigate pipeline |

**Source:** `docs/operations/operations-observability.md` — full alert catalog

---

## Self-Healing Mechanisms Summary

| Failure Mode | Detection | Recovery | OTel Signal |
|--------------|-----------|----------|-------------|
| Service crash | BaseDaemon exception handler | Systemd restart | `agent_crash_total` |
| Consumer stall | ServiceAuditor Prometheus query | Systemd restart | `consumer_stall_detected_total` |
| Watchdog timeout | systemd WatchdogSec | systemd restart | `watchdog_notify_suppressed_total` |
| DB disconnect | FastAPI health check | Alert + manual | `api_health` |
| Plugin failure | Circuit breaker state | Skip plugin | `intelligence_pipeline_plugin_cb_state` |
| DLQ poison pill | `dlq_events` occurrence count | Quarantine | `dlq_quarantine_total` |
| Oneshot failure | Script exit status | Alert | `job_completed_total{status="failure"}` |

---

## Phase 108 Artifacts

Full implementation details in `.planning/phases/108-self-healing-hardening/`:

| File | Content |
|------|---------|
| `108-CONTEXT.md` | Phase boundary, decisions, canonical refs |
| `108-RESEARCH.md` | Standard stack, architecture patterns |
| `108-PATTERNS.md` | File-by-file implementation map |
| `108-01-PLAN.md` through `108-07-PLAN.md` | Individual workstream plans |
| `108-VERIFICATION.md` | Post-implementation verification |

---

## See Also

- **OTel patterns:** `docs/platform/platform-observability.md`
- **Grafana dashboards:** `docs/operations/operations-observability.md`
- **Alerting runbook:** `docs/development/alerting.md`
- **Systemd supervision:** `docs/operations/operations-infrastructure.md`
- **CLAUDE.md:** "OTel Health Contract (Phase 108 SOP)" section
