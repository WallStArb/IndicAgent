# Observability — Metrics, Traces, Logs & Dashboards

**Version:** 2.8
**Last Updated:** 2026-05-28
**Status:** current

---

## Purpose

Unified OTel-based observability: metrics, traces, and logs flow through a central Collector to Prometheus, Tempo, and Loki. Single pane of glass via Grafana dashboards.

---

## Architecture

IndicAgent uses a unified OTel Collector pipeline — services push all telemetry (metrics, traces, logs) via OTLP gRPC to the Collector, which fans out to the appropriate backend. There are no per-service HTTP scrape endpoints.

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

**Key design decisions:**
- **Push-only** — `otel.py` initializes a `MeterProvider` with `PeriodicExportingMetricReader` (15s interval) and a `TracerProvider` with `BatchSpanProcessor`, both exporting via OTLP gRPC to `localhost:4317`. Services never open HTTP `/metrics` endpoints.
- **Single Prometheus scrape target** — Prometheus only scrapes the Collector's `:8889` Prometheus exporter. All service metrics flow through one path.
- **Graceful degradation** — `init_otel_providers()` wraps all setup in try/except. If the Collector is unreachable, services fall back to no-op providers and continue running.
- **`deployment.environment` tagged at Collector** — the Collector's `resource` processor injects `INDICAGENT_ENV`, so dev/prod metrics are tagged centrally.

## Component Stack

| Component | Port | Purpose |
|-----------|------|---------|
| OTel Collector | `:4317` (gRPC), `:4318` (HTTP), `:8889` (Prometheus) | Central telemetry hub |
| Prometheus | `:9090` | Scrapes Collector `:8889` only; evaluates alert rules |
| Grafana | `:3001` | Dashboards — datasources: Prometheus, Tempo, Loki |
| Loki | `:3100` | Log aggregation (receives from OTel Collector) |
| Tempo | `:3200` (HTTP), `:4317` (OTLP) | Distributed traces (receives from OTel Collector) |
| Alertmanager | `:9093` | Alert routing — receives from Prometheus |

---

## Initialization

```python
from src.observability.otel import init_otel_providers
from src.observability.log_bridge import setup_otlp_logging

# Called automatically by BaseAgent.start() — manual call only needed in non-agent entry points
init_otel_providers(service_name="my-service")   # metrics + traces
setup_otlp_logging(service_name="my-service")    # OTLP log bridge (additive to file logging)
```

`setup_otlp_logging` is additive — structlog still writes to `logs/<service>.log` first; the OTLP bridge forwards to Loki on a best-effort basis.

---

## Metrics

### Creating Metrics

```python
from src.observability.metrics import counter, gauge

# Create instruments (module-level, avoid duplicate registration)
my_counter = counter("my_metric", "Documentation")
my_counter.add(1, {"label_key": "value"})

my_gauge = gauge("my_gauge", "Documentation")
my_gauge.add(delta, {"label_key": "value"})
```

Services do not start a `/metrics` HTTP server. All metrics are pushed via OTLP gRPC to the OTel Collector (`:4317`).

Most instruments are declared in `src/observability/metrics.py`; `src/core/agent/base_writer.py`
adds per-writer ones, and a few services declare their own. Every metric an alert rule, a
dashboard or a Prometheus query in code asks for must be declared in src/, services/ or
scripts/ under the series name the exporter publishes (a counter's `_total`, a histogram's
`_bucket`/`_sum`/`_count`): `tests/unit/observability/test_alert_and_dashboard_metric_refs.py`
enforces it.

### Persistence Agent Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `persistence_batch_latency_seconds` | Histogram | **agent_id** | Time to persist batch |
| `persistence_consumer_lag_records` | Gauge | **agent_id** | Current consumer lag |

**Important:** The `agent_id` label (not `agent` or `name`) is the canonical label for persistence metrics.

---

## Traces (Tempo)

Spans flow: service → OTel Collector → Tempo. Query in Grafana via the Tempo datasource.

```python
from src.observability.otel import get_tracer

tracer = get_tracer("my-service")
with tracer.start_as_current_span("compute_i7"):
    result = self._run_i7_plugins(bar)
```

`BaseAgent.__init__` sets `self.tracer` automatically — no manual setup needed inside agents.

### Using Spans

```python
from src.observability.spans import observed_span, ATTR_PLUGIN_NAME

with observed_span("plugin_compute", attributes={ATTR_PLUGIN_NAME: plugin.name}):
    result = plugin.compute(bar, features)
```

`observed_span()` auto-records ERROR status + exception on raise.

---

## Logs (Loki)

Three layers, in order of reliability:

1. **File** (`logs/<service>.log`) — always on, primary source for debugging
2. **Loki** (via `log_bridge.py`) — best-effort OTLP push, queryable in Grafana
3. **journald** — only captures `print()` output, not structlog

### Viewing Logs

```bash
# Structured logs (primary)
tail -f logs/<service>.log

# journald (print() only)
journalctl -u indicant-<service> -f

# Loki (via Grafana)
# Open Grafana :3001, switch to Loki datasource
```

---

## Grafana Dashboards

**Grafana URL:** http://localhost:3001 (admin / admin)

Dashboards are provisioned from `production/grafana/dashboards/` and auto-loaded on Grafana startup.

### Dashboard Catalog

#### 1. Operations Dashboard

**File:** `operations.json`
**Purpose:** Fleet-wide health monitoring

**Panels:** service health and restart rate, data completeness, IBKR bars produced, time since
the aggregator's last bar, DLQ messages by topic, gap-fill DLQ growth, writer consumer lag and
output buffer depth, completeness by symbol and timeframe, open gap windows, bar reconciliation
findings, and the D7 bar completeness and vendor disagreement panels.

**Use for:**
- Quick health check of the fleet and the bar path
- Identifying stalled services and data gaps

#### 2. Pipeline Health Dashboard

**File:** `pipeline-health.json`
**Purpose:** Streaming-path latency, throughput and consumer lag

**Panels:** p95 latency (feature writer DB writes, merger bars), bars per minute, HTF bars
emitted, plugin fallback rate, and consumer lag by agent and over time.

**Use for:**
- Performance regression detection on the streaming path
- Consumer lag and DLQ monitoring

The plugin-latency, signals-I8 and shadow-validation dashboards were deleted in todo 509
(2026-10-26): every metric they read went with the v2.x signal path and the I8 AI stack.

### Common Query Patterns

#### Rate Calculations

```promql
# Per-second rate
rate(metric_total[5m])

# Per-minute rate
rate(metric_total[1m]) * 60

# Absolute increase
increase(metric_total[1h])
```

#### Percentiles

```promql
# p50
histogram_quantile(0.50, rate(metric_duration_seconds_bucket[5m]))

# p95
histogram_quantile(0.95, rate(metric_duration_seconds_bucket[5m]))

# p99
histogram_quantile(0.99, rate(metric_duration_seconds_bucket[5m]))
```

#### Filtering

```promql
# By label value
metric{label="value"}

# By label regex
metric{label=~"value.*"}

# Excluding label
metric{label!="value"}

# Multiple labels
metric{label1="value1", label2=~"value2.*"}
```

### Dashboard Provisioning

Dashboards are auto-provisioned via `production/grafana/provisioning/dashboards/dashboards.yml`:

```yaml
apiVersion: 1

providers:
  - name: 'IndicAgent'
    orgId: 1
    folder: ''
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

---

## SLO Alerts

All alerts fire from Prometheus and display in Grafana Alert panel.

| Alert | Metric | Condition | Severity | Dashboard |
|-------|--------|-----------|----------|------------|
| Service Stall | `agent_last_message_timestamp_seconds` | stale > 120s | critical | Operations |
| Watchdog Suppression | `watchdog_notify_suppressed_total` | rate > 0 | warning | Operations |
| DLQ Quarantine | `dlq_quarantine_total` | rate > 0 | warning | Operations |
| API Health Down | `api_health` | < 1 | critical | Operations |
| Oneshot Failure | `job_completed_total{status="failure"}` | increment > 0 | warning | Operations |
| BPS Degradation | `rate(bars_processed_total[5m])` | drops > 50% | warning | Pipeline Health |
| High Consumer Lag | `persistence_consumer_lag_records` | > 1000 | warning | Operations |
| Circuit Breaker Open | `intelligence_pipeline_plugin_cb_state` | > 0 | warning | Pipeline Health |

---

## Troubleshooting

### Dashboard Not Loading

```bash
# Check Grafana logs
docker logs indicant-grafana --tail 50

# Check provisioning file syntax
cat production/grafana/provisioning/dashboards/dashboards.yml

# Verify dashboard JSON is valid
jq . production/grafana/dashboards/pipeline-health.json

# Check dashboard is mounted
docker exec indicant-grafana ls /etc/grafana/provisioning/dashboards/
```

### Queries Return No Data

```bash
# Check Prometheus is scraping
curl -s http://localhost:9090/api/v1/targets | jq

# Verify metric exists
curl -s 'http://localhost:9090/api/v1/query?query=up' | jq

# Check metric name and labels
curl -s 'http://localhost:9090/api/v1/label/__name__/values' | jq | grep <metric>

# Test query in Prometheus UI
# Open http://localhost:9090 and run query
```

### Dashboard Shows Stale Data

```bash
# Check Prometheus is receiving OTel data
docker logs indicant-otel-collector --tail 20

# Check service is emitting
curl -s 'http://localhost:9090/api/v1/query?query=agent_last_message_timestamp_seconds' | jq

# Verify OTel flush is happening
grep flush logs/<service>_agent.log
```

---

## See Also

- **[platform-observability.md](../platform/platform-observability.md)** — Design principles, OTel SDK patterns, metric contracts, circuit breaker, D-27 SLO alert table
- **Infrastructure:** `docs/operations/operations-infrastructure.md` — Docker, systemd
- **Database:** `docs/operations/operations-database.md` — TimescaleDB operations
- **Self-healing:** `docs/platform/platform-self-healing.md` — Watchdog, stall detection
- **Prometheus queries:** https://promql.io/
- **Grafana docs:** https://grafana.com/docs/
