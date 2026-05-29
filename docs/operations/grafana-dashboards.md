# Grafana Dashboards Catalog

**Version:** 2.8
**Last Updated:** 2026-05-28
**Grafana URL:** http://localhost:3001

---

## Overview

Grafana is the single pane of glass for IndicAgent observability. All dashboards consume Prometheus metrics collected via OTel. Dashboards are provisioned from `production/grafana/dashboards/` and auto-loaded on Grafana startup.

**Data sources:**
- Prometheus (metrics) — http://prometheus:9090
- Tempo (traces) — http://tempo:3200
- Loki (logs) — http://loki:3100

---

## Dashboard Catalog

### 1. Operations Dashboard

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

---

### 2. Pipeline Health Dashboard

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

# Circuit breaker states
intelligence_pipeline_plugin_cb_state
```

**Use for:**
- Performance regression detection
- Identifying slow tiers/plugins
- Circuit breaker monitoring

---

### 3. Plugin Latency Dashboard

**File:** `plugin-latency.json`
**Purpose:** Per-plugin performance profiling

**Panels:**
- Plugin execution time by tier
- Plugin fallback rate
- Cache hit rate
- State size by plugin

**Key queries:**
```promql
# Plugin execution time (p95 by tier)
histogram_quantile(0.95,
  rate(plugin_execution_seconds_sum{intelligence_tier="I7"}[5m]) /
  rate(plugin_execution_seconds_count{intelligence_tier="I7"}[5m])
)

# Fallback rate
rate(plugin_fallbacks_total[5m])

# State size
plugin_state_size_bytes{plugin_name=~".*"}
```

**Use for:**
- Plugin performance optimization
- Identifying expensive plugins
- Cache effectiveness analysis

---

### 4. Signals & I8 Dashboard

**File:** `signals-i8.json`
**Purpose:** Signal generation and AI intelligence monitoring

**Panels:**
- Signal fire rate by plugin
- Signal win rate
- I8 LLM call latency
- LLM token usage
- Model performance scores

**Key queries:**
```promql
# Signal fire rate
rate(indic_agent_i7_signals_fired_total[5m])

# LLM latency
histogram_quantile(0.95, rate(llm_call_duration_seconds_bucket[5m]))

# Token usage
rate(llm_tokens_used_total[5m])

# Model win rate
llm_model_win_rate{model=~".*"}
```

**Use for:**
- Signal quality monitoring
- LLM performance tracking
- Model comparison

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

## Creating New Dashboards

### Manual Creation

1. Open Grafana at http://localhost:3001
2. Click "+" → "New dashboard"
3. Add panels with PromQL queries
4. Save dashboard
5. Export JSON: Share → Export → Save to file
6. Copy to `production/grafana/dashboards/`
7. Update `dashboards.yml` provisioning config

### From Template

```bash
# Copy existing dashboard as template
cp production/grafana/dashboards/pipeline-health.json \
   production/grafana/dashboards/new-dashboard.json

# Edit JSON to customize
vim production/grafana/dashboards/new-dashboard.json

# Reload Grafana (or wait for auto-reload)
docker restart indicant-grafana
```

---

## Dashboard Provisioning

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

Dashboards are mounted from host at `/etc/grafana/provisioning/dashboards` via Docker volume:

```yaml
# docker-compose.yml
volumes:
  - ./grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
```

---

## Common Query Patterns

### Rate Calculations

```promql
# Per-second rate
rate(metric_total[5m])

# Per-minute rate
rate(metric_total[1m]) * 60

# Absolute increase
increase(metric_total[1h])
```

### Percentiles

```promql
# p50
histogram_quantile(0.50, rate(metric_duration_seconds_bucket[5m]))

# p95
histogram_quantile(0.95, rate(metric_duration_seconds_bucket[5m]))

# p99
histogram_quantile(0.99, rate(metric_duration_seconds_bucket[5m]))
```

### Filtering

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

### Aggregation

```promql
# Sum by label
sum(metric) by (label)

# Average by label
avg(metric) by (label)

# Max by label
max(metric) by (label)

# Count distinct
count(distinct(label_value)) by (group_label)
```

---

## Troubleshooting Dashboards

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

## Dashboard Maintenance

### Updating Existing Dashboards

1. Open dashboard in Grafana
2. Make changes
3. Save dashboard (overwrites existing)
4. Export JSON: Share → Export → Save to file
5. Update `production/grafana/dashboards/<dashboard>.json`
6. Grafana auto-reloads within 10 seconds

### Deleting Dashboards

Delete from `production/grafana/dashboards/` and Grafana will remove on next reload.

### Version Control

All dashboards are in version control. Commit changes after updating:

```bash
git add production/grafana/dashboards/
git commit -m "update(dashboards): <change description>"
```

---

## See Also

- **Observability:** `docs/architecture/observability.md`
- **Self-healing:** `docs/architecture/self-healing.md`
- **Alerting runbook:** `docs/guides/alerting-runbook.md`
- **Prometheus queries:** https://promql.io/
- **Grafana docs:** https://grafana.com/docs/
