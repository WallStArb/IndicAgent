# Observability Patterns — Metrics, Traces & Logs

**Status:** current
**Version:** 1.3
**Last Updated:** 2026-05-28
**Sources:** `src/observability/metrics.py`, `src/observability/otel.py`, `src/observability/log_bridge.py`, `src/core/agent/base.py`

## Overview

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
- **Push-only** — `otel.py` initialises a `MeterProvider` with `PeriodicExportingMetricReader` (15s interval) and a `TracerProvider` with `BatchSpanProcessor`, both exporting via OTLP gRPC to `localhost:4317`. Services never open HTTP `/metrics` endpoints.
- **Single Prometheus scrape target** — Prometheus only scrapes the Collector's `:8889` Prometheus exporter. All service metrics flow through one path.
- **Graceful degradation** — `init_otel_providers()` wraps all setup in try/except. If the Collector is unreachable, services fall back to no-op providers and continue running.
- **`deployment.environment` tagged at Collector** — the Collector's `resource` processor injects `INDICAGENT_ENV`, so dev/prod metrics are tagged centrally rather than per-service.

## Initialising Telemetry in a Service

```python
from src.observability.otel import init_otel_providers
from src.observability.log_bridge import setup_otlp_logging

# Called automatically by BaseAgent.start() — manual call only needed in non-agent entry points
init_otel_providers(service_name="my-service")   # metrics + traces
setup_otlp_logging(service_name="my-service")    # OTLP log bridge (additive to file logging)
```

`setup_otlp_logging` is additive — structlog still writes to `logs/<service>.log` first; the OTLP bridge forwards to Loki on a best-effort basis.

## Traces (Tempo)

Spans flow: service → OTel Collector → Tempo. Query in Grafana via the Tempo datasource.

```python
from src.observability.otel import get_tracer

tracer = get_tracer("my-service")
with tracer.start_as_current_span("compute_i7"):
    result = self._run_i7_plugins(bar)
```

`BaseAgent.__init__` sets `self.tracer` automatically — no manual setup needed inside agents.

## Logs (Loki)

Three layers, in order of reliability:
1. **File** (`logs/<service>.log`) — always on, primary source for debugging
2. **Loki** (via `log_bridge.py`) — best-effort OTLP push, queryable in Grafana
3. **journald** — only captures `print()` output, not structlog

## Metric Registry

```python
from src.observability.metrics import counter, gauge

# Create instruments (module-level, avoid duplicate registration)
my_counter = counter("my_metric", "Documentation")
my_counter.add(1, {"label_key": "value"})

my_gauge = gauge("my_gauge", "Documentation")
my_gauge.add(delta, {"label_key": "value"})
```

Services do not start a `/metrics` HTTP server. All metrics are pushed via OTLP gRPC to the OTel Collector (`:4317`).

## Golden Signals

| Signal | Metric | Type | Labels |
|--------|--------|------|--------|
| **Traffic** | `stream_messages_read_total` | Counter | stream, group |
| **Latency** | `stream_read_seconds` | Histogram | stream, group |
| **Errors** | `plugin_fallbacks_total` | Counter | plugin_name, reason |
| **Saturation** | `plugin_state_size_bytes` | Gauge | plugin_name, symbol, timeframe |

## Core Engine Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `stream_messages_read_total` | Counter | stream, group | Total messages from Redpanda streams |
| `stream_read_seconds` | Histogram | stream, group | Consumer poll latency |
| `db_batch_write_seconds` | Histogram | — | TimescaleDB batch write time |
| `engine_bars_processed` | Gauge | — | Total bars processed (cumulative) |
| `engine_throughput_per_sec` | Gauge | — | Current bars/second rate |

## Service Orchestrator Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `indicagent_service_health` | Gauge | service | Health status (1=healthy) |
| `indicagent_service_starts_total` | Counter | service | Total service starts |
| `indicagent_service_stops_total` | Counter | service | Total service stops |
| `indicagent_service_restarts_total` | Counter | service | Total service restarts |

## Plugin Execution Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `plugin_executions_total` | Counter | plugin_name, symbol, timeframe, status | Total plugin runs |
| `plugin_execution_seconds` | Histogram | plugin_name, intelligence_tier | Plugin execution time |
| `plugin_fallbacks_total` | Counter | plugin_name, reason | Fallbacks to direct calc |
| `plugin_accuracy_percentage` | Gauge | plugin_name, symbol, timeframe | Cache vs direct accuracy |
| `plugin_state_size_bytes` | Gauge | plugin_name, symbol, timeframe | In-memory state size |
| `plugin_skipped_total` | Counter | plugin_name, asset_class | Asset-class filter skips |

## Persistence Agent Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `persistence_batch_latency_seconds` | Histogram | **agent_id** | Time to persist batch |
| `persistence_consumer_lag_records` | Gauge | **agent_id** | Current consumer lag |

**Important:** The `agent_id` label (not `agent` or `name`) is the canonical label for persistence metrics.

### Persistence Metric Contracts

| Agent | `agent_id` Value | Target Latency | Alert Threshold |
|-------|------------------|----------------|-----------------|
| BarWriterAgent | `bar_writer` | <100ms | >500ms |
| FeatureWriterAgent | `feature_writer` | <250ms | >1s |
| SignalWriterAgent | `signal_writer` | <100ms | >500ms |

## Pipeline Timing Metrics (End-to-End)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `indic_bar_to_i1_latency_seconds` | Histogram | symbol, tf | Bar close → I1 computed |
| `indic_bar_to_intelligence_latency_seconds` | Histogram | symbol, tf | Bar close → I3-I6 published |
| `indic_bar_to_signal_latency_seconds` | Histogram | symbol, tf | Bar close → I7 signal |

**Buckets:** `[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]`

## Provider Layer Metrics (Phase 54)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `provider_bars_produced_total` | Counter | provider, agent | Bars published to raw topic |
| `provider_reconnects_total` | Counter | provider, agent | Reconnection attempts |
| `provider_connected` | Gauge | provider, agent | Connection state (0/1) |
| `provider_gaps_filled_total` | Counter | provider, agent | Gap-fill bars fetched |
| `merger_bars_routed_total` | Counter | provider | Bars routed to canonical |
| `merger_bars_dropped_total` | Counter | provider | Dropped (duplicate/stale) |
| `merger_failovers_total` | Counter | from_provider, to_provider | Failover executions |
| `merger_bar_latency_seconds` | Histogram | provider | Publish→consume latency |

## Shadow Plugin Monitoring (Phase 47)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `shadow_n_resolved` | Gauge | plugin | Resolved shadow signals |
| `shadow_win_rate` | Gauge | plugin | Shadow plugin win rate |
| `shadow_ev_r` | Gauge | plugin | Shadow E[PnL_R] |
| `shadow_ev_ci_lower` | Gauge | plugin | 95% CI lower bound |
| `shadow_days_to_gate` | Gauge | plugin | Est. days to N=100 |
| `shadow_promotion_ready` | Gauge | plugin | 1 when gate conditions met |

## Parity Auditor Metrics (Phase 52.5)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `parity_match_rate` | Gauge | symbol, tf | Primary/shadow match rate |
| `shadow_ahead_rows_total` | Counter | symbol, tf | Shadow-ahead (timing race) |
| `parity_violations_total` | Counter | symbol, tf | Field-level violations |
| `parity_cycles_total` | Counter | — | Total comparison cycles |

## Market Condition Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `market_conditions_detected` | Gauge | symbol, timeframe | Current regime (0=ranging, 1=trending, 2=volatile) |
| `provider_active_subscriptions` | Gauge | provider | Active data subscriptions |

## Per-Symbol/Timeframe Counters

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `indicator_bars_processed_labeled_total` | Counter | symbol, tf | Bars processed by indicator service |
| `market_analysis_bars_processed_labeled_total` | Counter | symbol, tf | Bars processed by market analysis |

## Circuit Breaker Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `plugin_circuit_breaker_state` | Gauge | plugin_name | State (0=closed, 1=open, 2=half-open) |
| `circuit_breaker_failures_total` | Counter | plugin_name, error_type | Failures by type |
| `circuit_breaker_successes_total` | Counter | plugin_name | Successful executions |
| `circuit_breaker_state_transitions_total` | Counter | plugin_name, from_state, to_state | State changes |
| `circuit_breaker_open_duration_seconds` | Histogram | plugin_name | Time in OPEN state |

## Grafana Dashboard Patterns

### Agent Health Panel

```promql
# Service health
indicagent_service_health{service="indicagent-intelligence-pipeline"}

# Consumer lag (persistence agents)
persistence_consumer_lag_records{agent_id="feature_writer"}

# Batch latency
rate(persistence_batch_latency_seconds_sum{agent_id="signal_writer"}[5m])
  / rate(persistence_batch_latency_seconds_count{agent_id="signal_writer"}[5m])
```

### Pipeline Performance

```promql
# End-to-end latency (bar close → signal)
histogram_quantile(0.95,
  indic_bar_to_signal_latency_seconds{symbol="ES", tf="1m"}
)

# Plugin execution time by tier
rate(plugin_execution_seconds_sum{intelligence_tier="I7"}[5m])
  / rate(plugin_execution_seconds_count{intelligence_tier="I7"}[5m])
```

### Provider Health

```promql
# Provider connection state
provider_connected{provider="ibkr"}

# Merger throughput
rate(merger_bars_routed_total[5m])

# Failover events
increase(merger_failovers_total[1h])
```

## Telemetry Endpoints

Services do **not** expose per-service HTTP `/metrics` scrape endpoints. All metrics are pushed via OTLP gRPC to the OTel Collector. To query metrics, use Prometheus (`:9090`) or Grafana (`:3001`).

| Backend | Port | Purpose |
|---------|------|---------|
| OTel Collector (gRPC) | `:4317` | Receives OTLP metrics/traces/logs from all services |
| OTel Collector (HTTP) | `:4318` | Alternative OTLP HTTP endpoint |
| OTel Collector (Prometheus exporter) | `:8889` | Scraped by Prometheus |
| Prometheus | `:9090` | Metrics storage + alerting |
| Grafana | `:3001` | Dashboards (Prometheus + Tempo + Loki) |
| Loki | `:3100` | Log aggregation |
| Tempo | `:3200` | Distributed traces |
| Alertmanager | `:9093` | Alert routing |

## Recording Rules (Recommended)

Create `/etc/prometheus/recording_rules.yml`:

```yaml
groups:
  - name: indicagent_latency
    interval: 30s
    rules:
      - record: job:persistence_batch_latency_seconds:p95
        expr: histogram_quantile(0.95,
               rate(persistence_batch_latency_seconds_sum[5m])
               / rate(persistence_batch_latency_seconds_count[5m]))

      - record: job:pipeline_e2e_latency:p95
        expr: histogram_quantile(0.95,
               rate(indic_bar_to_signal_latency_seconds_sum[5m])
               / rate(indic_bar_to_signal_latency_seconds_count[5m]))
```

## Alerting Rules (Recommended)

Create `/etc/prometheus/alert_rules.yml`:

```yaml
groups:
  - name: indicagent_alerts
    rules:
      - alert: HighConsumerLag
        expr: persistence_consumer_lag_records > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High consumer lag on {{ $labels.agent_id }}"

      - alert: ProviderDisconnected
        expr: provider_connected == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "{{ $labels.provider }} provider disconnected"

      - alert: HighBatchLatency
        expr: histogram_quantile(0.95,
               rate(persistence_batch_latency_seconds_sum[5m])
               / rate(persistence_batch_latency_seconds_count[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High batch latency on {{ $labels.agent_id }}"
```

## Agent Liveness

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `agent_last_message_timestamp_seconds` | Gauge | agent | Unix timestamp of last successfully processed Kafka message — stall detection |

**Stall detection threshold:** ServiceAuditor monitors `agent_last_message_timestamp_seconds` and fires `CONSUMER_STALL_DETECTED_TOTAL` when a service exceeds 120 seconds without processing a message (lowered from 360s in Phase 108). This triggers systemd watchdog auto-restart for daemon services.

## Agent Self-Observability (Phase 67)

Metrics emitted by `BaseAgent` itself — not requiring concrete overrides. All agents inherit these automatically.

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `agent_setup_latency_seconds` | Histogram | agent | `_setup()` execution time — buckets: 0.1s to 10s |

**Note:** `agent_crash_total`, `agent_setup_success_total`, and `agent_setup_failure_total` are covered in the OTel Health Contract section above. These are defined directly in `src/core/agent/base.py` (not in `src/observability/metrics.py`) to avoid circular imports.

## LLM Infrastructure Metrics (Phase 56)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `llm_call_duration_seconds` | Histogram | provider, call_type, status | LLM call latency per provider |
| `llm_tokens_used_total` | Counter | provider, call_type | Total tokens consumed |
| `llm_cache_hit_total` | Counter | call_type | Semantic cache hits (SemanticCache) |
| `llm_guardrails_rejections_total` | Counter | call_type | Responses rejected by GuardrailsValidator schema check |
| `llm_rate_limit_wait_seconds` | Histogram | provider | Time waiting for rate limit token bucket |

## ML Observability Metrics (Phase 56)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `feature_ic_score` | Gauge | feature_name, regime | Information coefficient per feature/regime (updated weekly by MLDiscoveryComputeAgent) |
| `data_quality_score` | Gauge | — | Training data quality 0–1 (updated by MLDataQualityAuditorAgent) |
| `ml_discovery_features_extracted` | Gauge | — | tsfresh features extracted in last discovery run |

## LangGraph Workflow Metrics

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `langgraph_workflow_executions_total` | Counter | workflow_name, status | Total workflow executions |
| `langgraph_workflow_duration_seconds` | Histogram | workflow_name, intelligence_tier | Workflow execution time |
| `langgraph_node_executions_total` | Counter | workflow_name, node_name, status | Node-level execution counts |
| `langgraph_node_duration_seconds` | Histogram | workflow_name, node_name | Per-node execution time |
| `langgraph_agent_invocations_total` | Counter | agent_name, workflow_name, status | Agent invocations within workflows |
| `langgraph_event_routing_total` | Counter | workflow_name, source_node, target_node, condition | Conditional edge routing |
| `langgraph_workflow_state_size_bytes` | Gauge | workflow_name, symbol, timeframe | Workflow state size |
| `langgraph_parallel_executions_active` | Gauge | workflow_name | Concurrent workflow executions |

## DLQ Metrics (Phase 67)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `dlq_depth` | Gauge | agent, topic | Current messages in Dead Letter Queue |
| `dlq_messages_total` | Counter | agent, topic, error_type | Total messages routed to DLQ |
| `bar_auditor_gap_fill_dlq_depth` | Counter | — | Gap-fill requests escalated to DLQ after retry exhaustion |
| `service_auditor_service_restarts_total` | Counter | service_name | Systemd restarts triggered by ServiceAuditorAgent |

## Regime Gate Metrics (Phase 68)

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `regime_gate_suppressions_total` | Counter | reason, plugin, tf | Signals suppressed by regime eligibility gate |

## Self-Healing Metrics (Phase 108)

Phase 108 introduced comprehensive self-healing instrumentation for systemd watchdog integration, stall detection, DLQ quarantine, and oneshot completion tracking.

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `dlq_quarantine_total` | Counter | agent, source_topic, error_type | Messages quarantined after 4 occurrences within 24h |
| `consumer_stall_detected_total` | Counter | unit | Services stalled >120s (ServiceAuditor threshold) |
| `job_completed_total` | Counter | job, status | Oneshot timer-triggered script completion |
| `api_health` | Gauge | service | FastAPI DB connectivity (1=connected, 0=unreachable) |
| `watchdog_notify_total` | Counter | agent | Successful sd_notify() calls (watchdog heartbeat) |
| `watchdog_notify_suppressed_total` | Counter | agent | Failed sd_notify() calls (missing NotifyAccess=main) |
| `bar_e2e_latency_ms` | Histogram | symbol, tf | End-to-end latency from bar arrival to signal enqueue |

### Grafana SLO Alert Thresholds (Phase 108)

| Alert | Metric | Condition | Severity | Purpose |
|-------|--------|-----------|----------|---------|
| DLQ Quarantine Spike | `dlq_quarantine_total` | `rate(dlq_quarantine_total[5m]) > 0.1` | warning | Quarantine system active — investigate poison pill |
| Service Stall | `consumer_stall_detected_total` | `increase(consumer_stall_detected_total[10m]) > 0` | critical | Service not processing — systemd auto-restart triggered |
| Oneshot Failure | `job_completed_total{status="failure"}` | `increase(job_completed_total{status="failure"}[1h]) > 0` | warning | Timer job failed — manual investigation required |
| API Health Down | `api_health{service="indicagent-api"}` | `api_health < 1` | critical | FastAPI cannot reach TimescaleDB |
| Watchdog Suppression | `rate(watchdog_notify_suppressed_total[5m]) > 0.01` | warning | sd_notify() failing — unit file missing NotifyAccess=main |

### Systemd Watchdog Integration

All 25 daemon services run with `WatchdogSec=60` and `NotifyAccess=main` in their systemd unit files. When a service stalls (no message processed for 60s), systemd auto-restarts it. The `watchdog_notify_total` counter tracks successful sd_notify() heartbeats; `watchdog_notify_suppressed_total` indicates missing `NotifyAccess=main` configuration.

### Oneshot Completion Counter Contract (D-06)

Timer-triggered scripts (ml-training, shadow-auditor, roll-batch) MUST emit `job_completed_total{job, status}` at script exit:
- `job` label MUST match systemd unit `%n` suffix exactly (kebab-case)
- `status` label is either `"success"` or `"failure"`
- OTel flush (`flush_and_shutdown_metrics()`) MUST be called in finally block before exit

Example from `ml_training_agent.py`:
```python
try:
    await run_training()
    JOB_COMPLETED_TOTAL.add(1, {"job": "ml-training", "status": "success"})
except Exception:
    JOB_COMPLETED_TOTAL.add(1, {"job": "ml-training", "status": "failure"})
    raise
finally:
    flush_and_shutdown_metrics(timeout_millis=5000)
```

### DLQ Quarantine Semantics

The `dlq_quarantine_total` counter fires on the 4th occurrence of any `(agent, source_topic, error_type)` triple within a rolling 24-hour window. Quarantined messages have `quarantined=TRUE` in the `dlq_events` table and are excluded from retry processing. The rolling counter is seeded from the database at `DLQDrainAgent` startup, so restarts do not reset poison-pill detection.

### Instrument Lifecycle

| Instrument | Survives Restart | Backed by DB | Notes |
|------------|------------------|--------------|-------|
| `dlq_quarantine_total` | No | Yes (dlq_events.quarantined) | 24h rolling counter seeded at startup |
| `consumer_stall_detected_total` | No | No | Counter resets on service restart |
| `job_completed_total` | No | No | Ephemeral — emits only at script exit |
| `api_health` | Yes | No | Gauge persists across service restarts |
| `watchdog_notify_total` | No | No | Counter resets on service restart |
| `watchdog_notify_suppressed_total` | No | No | Counter resets on service restart |
| `bar_e2e_latency_ms` | Yes | No | Histogram data persists in OTel Collector |

## OTel Configuration

**Environment variables:**
- `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP gRPC endpoint (default: `http://localhost:4317`)
- `APP_VERSION` — Sets `service.version` resource attribute
- `INDICAGENT_ENV` — Sets `deployment.environment` (also injected by the Collector's resource processor)
- `NOTIFYACCESS=main` — Required in systemd unit files for watchdog integration (absent = `watchdog_notify_suppressed_total` increments)

**Systemd watchdog requirements (Phase 108):**
All daemon unit files MUST include:
```ini
[Service]
WatchdogSec=60
NotifyAccess=main
```

Without `NotifyAccess=main`, sd_notify() calls fail silently and `WATCHDOG_NOTIFY_SUPPRESSED_TOTAL` increments. This is monitored via Grafana alert `watchdog-suppression-spike`.

## OTel Health Contract (Phase 108 SOP)

All agents MUST emit the following signals at startup/shutdown/crash boundaries. See CLAUDE.md "OTel Health Contract (Phase 108 SOP)" for full contract.

| Signal | Type | Labels | When |
|--------|------|--------|------|
| `agent_setup_success_total` | Counter | agent | `_setup()` completes successfully |
| `agent_setup_failure_total` | Counter | agent, error_type | `_setup()` throws exception |
| `agent_crash_total` | Counter | agent | Uncaught exception in `_run()` |
| `agent_last_message_timestamp_seconds` | Gauge | agent | Message processed (stall detection) |
| `dlq_depth` | Gauge | agent, topic | DLQ size (per-destination) |

**Oneshot contract (D-06):** Timer-triggered scripts MUST emit `job_completed_total{job, status}` at script exit with OTel flush. See Oneshot Completion Counter Contract above.

## See Also

- **CLAUDE.md** — "OTel Health Contract (Phase 108 SOP)" section: 5 mandatory BaseAgent signals + oneshot contract
- `.planning/phases/108-self-healing-hardening/` — Phase 108 plans and summaries: OTel foundation, watchdog rollout, DLQ quarantine, stall detection
- `base-agent-patterns.md` — Agent lifecycle and metric scaffolding
- `agent-standard.md` — Role taxonomy and naming conventions
- `current-state.md` — Active agents and their metrics ports
