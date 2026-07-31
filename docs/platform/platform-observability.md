# Platform Observability

**Version:** 2.9
**Last Updated:** 2026-07-31
**Status:** current

---

## Purpose

This document explains why observability is structured the way it is, and serves as the authoritative reference for engineers adding new metrics, spans, or diagnosing telemetry gaps. It is the merge of the architectural patterns doc (`docs/architecture/observability.md`, now deleted) and the design rationale. For operational runbooks (dashboard navigation, Grafana queries, troubleshooting steps), see `docs/operations/operations-observability.md`.

**Readers:** Engineers adding new services or metrics; anyone diagnosing why metrics stop appearing; anyone writing new spans; on-call engineers investigating SLO alerts.

---

## Design Principles

### Why OTel SDK directly — not prometheus_client

`prometheus_client` was fully removed in Phase 83. All metric creation now goes through `src/observability/metrics.py`, which wraps the OpenTelemetry Python SDK. This decision was deliberate:

- **Single pipeline:** OTel SDK exports metrics, traces, and logs through one collector. `prometheus_client` only covers metrics, requiring separate instrumentation for traces.
- **Environment tagging at the collector:** `INDICAGENT_ENV` is injected by the OTel Collector's resource processor — not per-service. This is impossible with `prometheus_client`.
- **No HTTP `/metrics` endpoint per service:** Services push via OTLP gRPC. No scrape endpoint to configure, no port to allocate, no firewall rule needed per new service.
- **Graceful degradation:** `init_otel_providers()` catches all errors. If the Collector is unreachable, services fall back to no-op providers and continue running without panicking.

**Never import `prometheus_client`.** If you see it in a file, it is a bug.

### Push vs. pull model

IndicAgent uses a **push-only** model. Each service pushes OTLP gRPC batches to the Collector every 15s (metrics) or on flush (traces/logs). Prometheus scrapes only the Collector's `:8889` Prometheus exporter — a single target. This means:

- Adding a new service requires zero Prometheus config changes
- The Collector is the single point of aggregation (and the single point of failure — it runs `restart: unless-stopped`)

### Why each instrument type exists

| Type | OTel Name | Use case | Call pattern |
|------|-----------|----------|--------------|
| Counter | `Counter` | Monotonically increasing events (bars processed, errors, signals fired) | `.add(1, {"label": val})` |
| Histogram | `Histogram` | Latency distributions, byte sizes | `.record(val, {"label": val})` |
| Up-down gauge | `UpDownCounter` via `create_up_down_counter` | Delta-tracked values (queue depth, active connections, consumer lag) | `.add(delta, {"label": val})` |
| Point gauge | `Gauge` via `create_gauge` | Absolute point-in-time values (health flags, state indicators) | `.set(value, {"label": val})` |

### Why span instrumentation matters

Spans let you trace a single bar from arrival through all I1-I7 plugin stages to signal emission. Without spans, you can measure aggregate latency but cannot identify which plugin in which tier is causing a latency spike for a specific symbol. `observed_span` makes spans zero-boilerplate: it auto-records `ERROR` status and the exception on raise.

### Circuit breaker pattern

The `CircuitBreaker` (`src/observability/circuit_breaker.py`) prevents a repeatedly-failing plugin from burning CPU on every bar. States: `CLOSED` (normal), `OPEN` (failing, requests rejected), `HALF_OPEN` (probing recovery).

Key subtlety: `OPEN → HALF_OPEN` recovery only fires inside `call()`. For manual tracking (outside `call()`), use:
- `allow_request()` — time-based `OPEN → HALF_OPEN` check
- `record_success()` — resets failures, closes from `HALF_OPEN`

Both methods were added in Phase 086.

---

## Architecture

### Pipeline

```
Services (all)
  │
  ├── metrics (OTLP push, every 15s)  ─┐
  ├── traces  (OTLP push, batched)    ─┼─→  OTel Collector :4317
  └── logs    (OTLP push, every 5s)   ─┘         │
                                            ┌─────┼──────┐
                                            ▼     ▼      ▼
                                        Prometheus Tempo  Loki
                                        exporter  traces  logs
                                        :8889
                                            │
                                      Prometheus :9090
                                      (scrapes :8889 every 15s)
                                            │
                                       Grafana :3001
                                   (Prometheus + Tempo + Loki)
```

### Metrics registry — `src/observability/metrics.py`

All instruments are created via factory functions in this module. Create instruments at **module level** (not inside functions) to avoid duplicate registration warnings.

```python
from src.observability.metrics import counter, histogram, gauge

# Counter
bars_processed = counter("bars_processed_total", "Total bars processed")
bars_processed.add(1, {"symbol": symbol, "tf": tf})

# Histogram
batch_latency = histogram("persistence_batch_latency_seconds", "Batch write time")
batch_latency.record(elapsed, {"agent_id": "feature_writer"})

# Up-down gauge (consumer lag, queue depth)
consumer_lag = gauge("persistence_consumer_lag_records", "Consumer lag")
consumer_lag.add(delta, {"agent_id": "feature_writer"})
```

### Spans module — `src/observability/spans.py`

```python
from src.observability.spans import observed_span, ATTR_PLUGIN_NAME, ATTR_SYMBOL

with observed_span("plugin_compute", attributes={
    ATTR_PLUGIN_NAME: plugin.name,
    ATTR_SYMBOL: symbol
}):
    result = plugin.compute(bar, features)
```

`observed_span` auto-records `ERROR` status + exception on raise. Use `ATTR_*` constants from this module — never raw strings.

### Initialization

`BaseDaemon.start()` (renamed from `BaseAgent` during the v3.0 rebuild — see `docs/agents/agents-foundation.md`'s Naming note) calls `init_otel_providers()` and `setup_otlp_logging()` automatically. Manual call only needed in non-agent entry points (e.g., oneshot scripts):

```python
from src.observability.otel import init_otel_providers
from src.observability.log_bridge import setup_otlp_logging

init_otel_providers(service_name="my-script")
setup_otlp_logging(service_name="my-script")
```

Logging is additive: structlog still writes to `logs/<service>.log` first; OTLP bridge forwards to Loki best-effort.

---

## Data Contracts

### Instrument call patterns

```python
# Counter
counter_instrument.add(1, {"label_key": "value"})

# Histogram
histogram_instrument.record(elapsed_seconds, {"label_key": "value"})

# Up-down gauge (delta semantics)
gauge_instrument.add(+1, {"label_key": "value"})   # increment
gauge_instrument.add(-1, {"label_key": "value"})   # decrement
```

### Never

- `import prometheus_client` — removed in Phase 83, causes duplicate metric registration
- Inline `.isoformat().replace("+00:00", "Z")` in metric labels — use `format_iso_ts()` from `service_utils.py`
- Create instruments inside a function that is called per-message — instrument creation at module level only

### Mandatory OTel signals (Phase 108, D-04)

Every new daemon inheriting `BaseDaemon` automatically emits these five signals. No per-service code needed:

**Label correction 2026-07-31:** `agent_crash_total`'s label key is `agent`, not `agent_id` — see
`src/core/agent/base.py`'s `_crash_attrs = {"agent": self._agent_label}`. This also affects
CLAUDE.md's OTel Health Contract section (out of scope to fix here; flagged separately).

| Signal | Type | Label | When |
|--------|------|-------|------|
| `agent_last_message_timestamp_seconds` | Gauge | `agent_id` | Every processed message — stall detection |
| `agent_crash_total` | Counter | `agent` | Uncaught exception in `_run()` |
| `agent_dlq_total` | Counter | `agent_id` | DLQ routing events |
| `watchdog_notify_total` | Counter | `agent_id` | Successful `sd_notify WATCHDOG=1` pings |
| `watchdog_notify_suppressed_total` | Counter | `agent_id` | Suppressed pings: agent alive but idle/stalled |

**Non-compliance is a code review rejection (D-26).**

### Oneshot contract (D-06)

Timer-triggered scripts must emit `job_completed_total{job, status}` at exit:

```python
try:
    await run_job()
    JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "success"})
except Exception:
    JOB_COMPLETED_TOTAL.add(1, {"job": "roll-batch", "status": "failure"})
    raise
finally:
    flush_and_shutdown_metrics(timeout_millis=5000)
```

The `job` label must match the systemd unit `%n` suffix exactly (kebab-case). `flush_and_shutdown_metrics()` must be called in `finally` — oneshot processes exit before the 15s push interval fires.

### `agent_last_message_timestamp_seconds` label key

The label key is `agent_id` (not `agent` or `name`). When querying from Prometheus: `r["metric"].get("agent_id")`.

### `PERSISTENCE_BATCH_LATENCY` label key

The label key is `agent_id` (not `agent=`).

### Grafana SLO alerts (D-27)

| Alert | Metric | Condition | Severity |
|-------|--------|-----------|----------|
| Service Stall | `agent_last_message_timestamp_seconds` | stale > 120s | page (critical) |
| Watchdog Suppression | `watchdog_notify_suppressed_total` | rate > 0 | warning |
| DLQ Quarantine | `dlq_quarantine_total` | increment > 0 | warning |
| API Health Down | `api_health` | = 0 | page (critical) |
| BPS Degradation | `rate(bars_processed_total[5m])` | drops > 50% from baseline | warning |
| Consumer Stall | `consumer_stall_detected_total` | rate > 0 | warning |
| Oneshot Failure | `job_completed_total{status="failure"}` | increment > 0 | warning |
| Oneshot No Recent Success | `time_since_last_success{job=X}` | > 25h | page |

### Telemetry endpoints

| Backend | Port | Purpose |
|---------|------|---------|
| OTel Collector (gRPC) | `:4317` | Receives OTLP metrics/traces/logs from all services |
| OTel Collector (HTTP) | `:4318` | Alternative OTLP HTTP endpoint |
| OTel Collector (Prometheus) | `:8889` | Scraped by Prometheus (only scrape target) |
| Prometheus | `:9090` | Metrics storage + alerting |
| Grafana | `:3001` | Dashboards (Prometheus + Tempo + Loki) |
| Loki | `:3100` | Log aggregation |
| Tempo | `:3200` | Distributed traces |
| Alertmanager | `:9093` | Alert routing |

### OTel environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Collector gRPC endpoint |
| `APP_VERSION` | — | Sets `service.version` resource attribute |
| `INDICAGENT_ENV` | — | Sets `deployment.environment` (also injected by Collector) |

### Systemd watchdog requirements (Phase 108)

All daemon unit files must include:

```ini
[Service]
WatchdogSec=60
NotifyAccess=main
```

Without `NotifyAccess=main`, `sd_notify()` calls fail silently and `watchdog_notify_suppressed_total` increments. This is monitored via Grafana alert `Watchdog Suppression`.

---

## How To Extend

### Adding a new metric

1. Open `src/observability/metrics.py` (or define in the service module if service-specific).
2. Create the instrument at **module level**:
   ```python
   from src.observability.metrics import counter, histogram, gauge

   MY_COUNTER = counter("my_events_total", "Total my events")
   ```
3. Call the instrument in your handler:
   ```python
   MY_COUNTER.add(1, {"symbol": symbol, "agent_id": self.agent_id})
   ```
4. Add a Grafana panel or PromQL alert if it is a golden signal.

### Adding a new span

```python
from src.observability.spans import observed_span, ATTR_SYMBOL

async def _compute(self, bar):
    with observed_span("my_compute_step", attributes={ATTR_SYMBOL: bar.symbol}):
        return self._do_work(bar)
```

Use `ATTR_*` constants. Add new constants to `src/observability/spans.py` if none exists for your label.

---

## Failure Modes & Operations

### Metrics stop appearing in Grafana

1. Check OTel Collector is running: `docker ps | grep otel-collector`
2. Check Collector logs: `docker logs indicagent-otel-collector --tail 20`
3. Check Prometheus is scraping: `curl -s http://localhost:9090/api/v1/targets | jq`
4. Verify the metric exists: `curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq | grep <metric>`
5. Check service is emitting: `grep otel logs/<service>_agent.log | tail -5`

### Grafana alert descriptions

| Alert | What it means | First action |
|-------|--------------|--------------|
| Service Stall | A service stopped processing messages for 120s | `systemctl status indicagent-<service>` + check logs |
| Watchdog Suppression | `sd_notify()` failing — unit file missing `NotifyAccess=main` | Add `NotifyAccess=main` to unit file, reload, restart |
| DLQ Quarantine | A poison-pill message has been quarantined (4th occurrence in 24h) | Check `dlq_events` table for `quarantined=TRUE` rows |
| API Health Down | FastAPI cannot reach TimescaleDB | `systemctl status timescaledb` + `docker ps` |
| BPS Degradation | Pipeline throughput dropped >50% | Check `bar-aggregator`, `provider-merger`, IBKR connection |
| Oneshot Failure | Timer job exited with failure status | `journalctl -u indicagent-<job>` |

### Circuit breaker recovery

The `CircuitBreaker` (`src/observability/circuit_breaker.py`) has three states:

| State | Meaning | Transition |
|-------|---------|------------|
| `CLOSED` | Normal — requests pass through | → `OPEN` after N failures |
| `OPEN` | Failing — requests rejected immediately | → `HALF_OPEN` after timeout (via `allow_request()`) |
| `HALF_OPEN` | Probing — one request allowed through | → `CLOSED` via `record_success()`, or back to `OPEN` on failure |

For manual tracking outside `call()`, use `allow_request()` (time-based `OPEN → HALF_OPEN`) and `record_success()` (resets failures, closes from `HALF_OPEN`).

---

## See Also

- **[agents-foundation.md](../agents/agents-foundation.md)** — Mandatory OTel signals, agent lifecycle
- **[platform-foundation.md](platform-foundation.md)** — Infrastructure model, Docker containers, systemd
- **[platform-api.md](platform-api.md)** — FastAPI service, SSE streaming, health endpoints
- **[operations/observability.md](../operations/observability.md)** — Operational runbook: Grafana dashboards, dashboard catalog, PromQL patterns, troubleshooting
