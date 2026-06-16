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

### Golden Signals

| Signal | Metric | Type | Labels |
|--------|--------|------|--------|
| **Traffic** | `stream_messages_read_total` | Counter | stream, group |
| **Latency** | `stream_read_seconds` | Histogram | stream, group |
| **Errors** | `plugin_fallbacks_total` | Counter | plugin_name, reason |
| **Saturation** | `plugin_state_size_bytes` | Gauge | plugin_name, symbol, timeframe |

### Core Engine Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `stream_messages_read_total` | Counter | stream, group | Total messages from Redpanda streams |
| `stream_read_seconds` | Histogram | stream, group | Consumer poll latency |
| `db_batch_write_seconds` | Histogram | — | TimescaleDB batch write time |
| `engine_bars_processed` | Gauge | — | Total bars processed (cumulative) |
| `engine_throughput_per_sec` | Gauge | — | Current bars/second rate |

### Persistence Agent Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `persistence_batch_latency_seconds` | Histogram | **agent_id** | Time to persist batch |
| `persistence_consumer_lag_records` | Gauge | **agent_id** | Current consumer lag |

**Important:** The `agent_id` label (not `agent` or `name`) is the canonical label for persistence metrics.

### Pipeline Timing Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `indic_bar_to_i1_latency_seconds` | Histogram | symbol, tf | Bar close → I1 computed |
| `indic_bar_to_intelligence_latency_seconds` | Histogram | symbol, tf | Bar close → I3-I6 published |
| `indic_bar_to_signal_latency_seconds` | Histogram | symbol, tf | Bar close → I7 signal |

**Buckets:** `[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]`

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

**Panels:**
- Service status (up/down)
- Agent last message timestamps (stall detection)
- Consumer lag by service
- OTel Collector health
- Docker container status

**Key queries:**
```promql
# Service health
agent_last_message_timestamp_seconds{agent_id=~"indicagent-.*"}

# Consumer lag
persistence_consumer_lag_records{agent_id=~".*-writer"}

# OTel Collector up
up{job="otel-collector"}
```

**Use for:**
- Quick health check of entire fleet
- Identifying stalled services
- Verifying OTel pipeline health

#### 2. Pipeline Health Dashboard

**File:** `pipeline-health.json`
**Purpose:** End-to-end pipeline performance monitoring

**Panels:**
- Bars processing rate (BPS)
- End-to-end latency (p50, p95, p99)
- Per-stage latency breakdown
- I1-I7 plugin execution times
- Circuit breaker states

**Key queries:**
```promql
# BPS
rate(intelligence_pipeline_bars_processed_total[5m])

# E2E latency
histogram_quantile(0.95, rate(bar_e2e_latency_ms_bucket[5m]))

# Per-stage latency
rate(plugin_execution_seconds_sum{intelligence_tier="I1"}[5m]) /
  rate(plugin_execution_seconds_count{intelligence_tier="I1"}[5m])
```

**Use for:**
- Performance regression detection
- Identifying slow tiers/plugins
- Circuit breaker monitoring

#### 3. Plugin Latency Dashboard

**File:** `plugin-latency.json`
**Purpose:** Per-plugin performance profiling

**Panels:**
- Plugin execution time by tier
- Plugin fallback rate
- Cache hit rate
- State size by plugin

**Use for:**
- Plugin performance optimization
- Identifying expensive plugins
- Cache effectiveness analysis

#### 4. Signals & I8 Dashboard

**File:** `signals-i8.json`
**Purpose:** Signal generation and AI intelligence monitoring

**Panels:**
- Signal fire rate by plugin
- Signal win rate
- I8 LLM call latency
- LLM token usage
- Model performance scores

**Use for:**
- Signal quality monitoring
- LLM performance tracking
- Model comparison

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
- **Self-healing:** `docs/architecture/self-healing.md` — Watchdog, stall detection
- **Prometheus queries:** https://promql.io/
- **Grafana docs:** https://grafana.com/docs/
