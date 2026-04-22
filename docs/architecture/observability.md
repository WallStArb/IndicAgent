# Observability Patterns — Metrics & Monitoring

**Version:** 1.1
**Last Updated:** 2026-04-21
**Source:** `src/observability/metrics.py`

## Overview

IndicAgent uses Prometheus for metrics collection and Grafana for visualization. All agents emit the **Golden Signals** (Traffic, Latency, Errors, Saturation) plus domain-specific metrics.

## Metric Registry

```python
from src.observability.metrics import counter, gauge, start_metrics_server

# Avoid duplicate registration
my_counter = counter("my_metric", "Documentation")
my_counter.inc()

# Start metrics server (idempotent)
start_metrics_server(port=9100)
```

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
| `stream_messages_read_total` | Counter | stream, group | Total messages from Redis/Kafka streams |
| `stream_read_seconds` | Histogram | stream, group | XREADGROUP latency |
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

## Metrics Server Ports

| Service | Port | Dashboard Path |
|---------|------|----------------|
| IBKR Provider | 9129 | `http://localhost:9129/metrics` |
| Provider Merger | 9130 | `http://localhost:9130/metrics` |
| Bar Aggregator | 9120 | `http://localhost:9120/metrics` |
| Bar Writer | 9121 | `http://localhost:9121/metrics` |
| Bar Auditor | 9123 | `http://localhost:9123/metrics` |
| Roll Compute | 9122 | `http://localhost:9122/metrics` |
| Contract Metadata Writer | 9124 | `http://localhost:9124/metrics` |
| Intelligence Pipeline | 9125 | `http://localhost:9125/metrics` |
| Signal Writer | 9119 | `http://localhost:9119/metrics` |
| Signal Tracker | 9115 | `http://localhost:9115/metrics` |
| Signal Metrics Compute | 9126 | `http://localhost:9126/metrics` |
| Signal Metrics Writer | 9127 | `http://localhost:9127/metrics` |
| Signal Auditor | 9128 | `http://localhost:9128/metrics` |
| Feature Writer | 9116 | `http://localhost:9116/metrics` |
| Feature Snapshot Writer | 9132 | `http://localhost:9132/metrics` |
| Parity Auditor | 9133 | `http://localhost:9133/metrics` |
| LLM Writer | 9117 | `http://localhost:9117/metrics` |
| AI Narrative | 9113 | `http://localhost:9113/metrics` |
| Cross Asset | 9118 | `http://localhost:9118/metrics` |
| Service Auditor | 9131 | `http://localhost:9131/metrics` |

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

## Agent Self-Observability (Phase 67)

Metrics emitted by `BaseAgent` itself — not requiring concrete overrides. All agents inherit these automatically.

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `agent_crash_total` | Counter | agent | Uncaught exceptions in `BaseAgent._run()` |
| `agent_setup_success_total` | Counter | agent | Successful `_setup()` completions |
| `agent_setup_failure_total` | Counter | agent, error_type | Failed `_setup()` calls, classified by exception type |
| `agent_setup_latency_seconds` | Histogram | agent | `_setup()` execution time — buckets: 0.1s to 10s |

These are defined directly in `src/core/agent/base.py` (not in `src/observability/metrics.py`) to avoid circular imports.

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

## OTel Tracing

OTel is active. `opentelemetry-sdk` v1.41.0 is installed. Every agent gets `self.tracer` at init — tracing is a no-op when no OTLP endpoint is configured.

```python
from src.observability.otel import init_tracing, get_tracer

# Called automatically by BaseAgent.start() — manual call only needed in non-agent entry points
init_tracing(service_name="my-service")

# Usage within any agent (self.tracer is already set by BaseAgent.__init__)
with self.tracer.start_as_current_span("compute_i1"):
    result = self._run_i1_plugins(bar)
```

**Configuration:**
- `OTEL_EXPORTER_OTLP_ENDPOINT` — OTLP HTTP endpoint (default: `http://localhost:4318`)
- `OTEL_EXPORTER_OTLP_HEADERS` — Comma-separated `key=value` auth headers
- `APP_VERSION` — Sets `service.version` resource attribute
- `ENV` — Sets `deployment.environment` resource attribute

## See Also

- `base-agent-patterns.md` — Agent lifecycle and metric scaffolding
- `agent-standard.md` — Role taxonomy and naming conventions
- `current-state.md` — Active agents and their metrics ports
