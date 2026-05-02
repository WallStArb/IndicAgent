# OTel Observability Unification Design

**Last Updated:** 2026-05-02

## Context

The current observability stack has three anti-patterns that caused an 11-hour undetected outage on 2026-04-28:

1. **24 per-process HTTP servers** for Prometheus metrics — wasteful in ports, threads, and config
2. **Manual service registries** in two places (`ServiceSpec` in service_auditor, `prometheus.yml`) that drift out of sync — `indicagent_service_health` metric referenced but nonexistent, 11 services missing from scrape config, port collisions
3. **Dead infrastructure** — OTel tracing configured but no-op, OTel Kafka context propagation implemented but inactive, metrics defined but never emitted

The fix: replace the ad-hoc monitoring with the industry-standard OTel stack. One collection pipeline, zero manual config, all three pillars (metrics, traces, logs) unified.

## Target Architecture

```
Agent Code (OTel SDK)
  |  metrics: Counter.add() / Gauge.set() / Histogram.record()
  |  traces:  spans via Tracer, context propagates through Kafka headers (already plumbed)
  |  logs:    structlog -> OTLP log bridge -> Collector
  |
  v  OTLP gRPC (localhost:4317)
OTel Collector (Docker container)
  |
  +--> Prometheus Remote Write Exporter  -- metrics storage
  +--> OTLP Exporter -> Tempo            -- traces (already deployed)
  +--> Loki Exporter                     -- centralized logs
  |
  +--> Service health state as metrics (systemd-derived, not manual registry)
        |
        v
     Grafana (unified metrics + traces + logs)
     Alertmanager (declarative rules, no Python alerting code)
```

### What Changes

| Component | Before | After |
|-----------|--------|-------|
| Metrics export | 24 HTTP servers (`start_http_server()`) | OTLP push to Collector |
| Metric definitions | `prometheus_client` Counter/Gauge/Histogram | OTel SDK equivalents |
| Trace context | No-op (plumbing exists, no active provider) | Active TracerProvider, spans in hot path |
| Logs | 24 rotating files in `logs/` | OTLP log bridge + file rotation |
| Prometheus config | 24 manual scrape targets | 1 target (Collector's Prometheus exporter) |
| Service registry | Hand-maintained `ServiceSpec` list | `systemctl list-units 'indicagent-*'` |
| Alerting | Python code in service_auditor | Prometheus Alertmanager rules |
| OTel Collector | Not deployed | New Docker container |

### What Stays

- **Prometheus** -- metrics storage, PromQL, existing Grafana dashboards
- **Tempo** -- trace storage (already deployed)
- **Grafana** -- visualization
- **Kafka trace propagation** -- `inject()`/`extract()` already implemented in `src/core/kafka_utils.py`
- **Metric names and labels** -- OTel Collector's Prometheus exporter preserves them
- **structlog** -- log formatting layer, now also bridges to OTLP
- **File-based logging** -- rotating files in `logs/` kept as backup; OTLP export is additive

## Detailed Design

### 1. BaseAgent Changes (`src/core/agent/base.py`)

**Remove:**
- `_metrics_port` parameter
- `start_metrics_server()` call
- `_agent_metrics_port()` abstract method

**Add:**
- OTel `MeterProvider` initialization in `__init__`
- OTel `TracerProvider` initialization in `__init__`
- OTLP log handler attachment in `start()`

The MeterProvider and TracerProvider both export via OTLP gRPC to `localhost:4317` (OTel Collector). Graceful degradation: wrap provider init in try/except. If Collector is unreachable at startup, fall back to no-op providers. Agents still run; metrics/traces just drop until Collector recovers.

### 2. Metrics Migration (`src/observability/metrics.py`)

Replace `prometheus_client` imports with OTel SDK. The API differs:

| prometheus_client | OTel SDK |
|-------------------|----------|
| `Counter("name", "help", ["label"])` | `meter.create_counter("name", description="help")` |
| `counter.labels(x="y").inc()` | `counter.add(1, {"x": "y"})` |
| `Gauge("name", "help", ["label"])` | `meter.create_gauge("name", description="help")` |
| `gauge.labels(x="y").set(v)` | `gauge.set(v, {"x": "y"})` |
| `Histogram("name", "help", ["label"])` | `meter.create_histogram("name", description="help")` |
| `hist.labels(x="y").observe(v)` | `hist.record(v, {"x": "y"})` |

**Migration strategy:** Define thin wrapper classes (`OTelCounter`, `OTelGauge`, `OTelHistogram`) in `metrics.py` that provide the `.labels().inc()` interface but delegate to OTel SDK internally. This allows incremental migration -- existing call sites work unchanged while the underlying export switches to OTLP.

### 3. OTel Collector Configuration

New Docker container alongside existing Prometheus and Tempo. Config file `production/otel-collector-config.yaml`:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
  resource:
    attributes:
      - key: deployment.environment
        value: ${INDICAGENT_ENV}
        action: upsert

exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true
  loki:
    endpoint: http://loki:3100/loki/api/v1/push

service:
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [batch, resource]
      exporters: [prometheusremotewrite]
    traces:
      receivers: [otlp]
      processors: [batch, resource]
      exporters: [otlp/tempo]
    logs:
      receivers: [otlp]
      processors: [batch, resource]
      exporters: [loki]
```

### 4. Log Bridge (`src/observability/log_bridge.py`)

Bridge structlog output to OTLP log export alongside existing file rotation. A new `OTLPLogHandler` attaches to the Python root logger. Structured log events are forwarded to the OTel Collector's OTLP log receiver. Logs still write to rotating files (existing behavior); OTLP export is additive.

### 5. Service Auditor Refactoring (`services/service_auditor_agent.py`)

**Remove:**
- `SERVICE_REGISTRY` manual list of all services
- `ServiceSpec` per-service config (metrics_port, lag_threshold)
- `_AGENT_ID_TO_UNIT` mapping
- `_JOB_TO_UNIT` mapping
- `_metrics_port` tracking
- Python-level alerting logic (data_stoppage, degraded, escalated)

**Replace with:**
- Dynamic service discovery from systemd via `systemctl list-units --all --no-legend 'indicagent-*'`
- DAG ordering derived from a single static dict (unit name -> dag_order), not a full ServiceSpec per service. This is the pipeline topology -- it changes rarely and is much smaller than the current ServiceSpec registry
- Expose service health as OTel metrics: `indicagent_service_up{unit="indicagent-bar-writer"} = 1`
- Alert evaluation moves to Prometheus Alertmanager (declarative rules)
- Service auditor becomes a lightweight state emitter, not an alert evaluator

### 6. Alertmanager Integration

New file `production/alertmanager-rules.yml` with declarative alert rules replacing Python code:

```yaml
groups:
  - name: indicagent_pipeline
    rules:
      - alert: ProviderDataStoppage
        expr: rate(provider_bars_produced_total[5m]) == 0 and indicagent_session_open == 1
        # indicagent_session_open is a gauge emitted by service_auditor (1=market open, 0=closed)
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "IBKR provider producing zero bars during active session"

      - alert: ServiceDown
        expr: indicagent_service_up == 0
        for: 1m
        labels:
          severity: warning

      - alert: ConsumerLagHigh
        expr: persistence_consumer_lag > 1000
        for: 2m
        labels:
          severity: warning
```

### 7. Distributed Tracing in the Hot Path

Trace context propagation through Kafka is already implemented (`src/core/kafka_utils.py` lines 104-107 inject, 278-287 extract). Activation requires only a real TracerProvider (Section 1).

Add spans at key processing boundaries:
- `IBKRProviderAgent._publish_bar()` -- root span per bar
- `BaseWriterAgent._process_message()` -- child span per write
- `intelligence_pipeline_agent._run_pipeline()` -- child span per pipeline run
- `SignalTrackerCompute._evaluate_signal()` -- child span per signal evaluation

Spans carry: symbol, timeframe, processing stage, latency. The existing `inject()`/`extract()` in Kafka producer/consumer automatically links parent to child spans across service boundaries.

### 8. Prometheus Config Collapse

`prometheus.yml` collapses from 24 targets to one:

```yaml
scrape_configs:
  - job_name: "otel-collector"
    static_configs:
      - targets: ["otel-collector:8889"]

  - job_name: "alertmanager"
    static_configs:
      - targets: ["alertmanager:9093"]
```

All metric names and labels are preserved through OTel Collector's Prometheus exporter. Existing Grafana dashboards work unchanged.

## Migration Path

Four phases, each independently deployable. No phase breaks the running system.

### Phase A: Deploy OTel Collector (infrastructure only, no agent changes)
- Add OTel Collector to docker-compose
- Configure to receive OTLP, export to Prometheus + Tempo
- Verify Collector starts and Prometheus can scrape it
- **Risk:** Zero -- nothing sends to it yet

### Phase B: Migrate BaseAgent to OTel SDK (metrics + traces)
- Swap `start_http_server()` for OTel MeterProvider + TracerProvider in BaseAgent
- Deploy metric wrappers in metrics.py
- Rolling restart of all services
- OTel Collector now receives metrics and traces
- Remove per-process HTTP servers and port allocation
- **Risk:** Low -- wrappers preserve existing API, Collector already deployed

### Phase C: Add log bridge, collapse Prometheus config, refactor auditor
- Bridge structlog to OTLP logs
- Add Loki to docker-compose
- Collapse prometheus.yml to single target
- Refactor service_auditor to use systemd discovery
- Remove ServiceSpec registry, _JOB_TO_UNIT, _AGENT_ID_TO_UNIT
- **Risk:** Medium -- auditor behavior changes, needs careful testing

### Phase D: Add Alertmanager, hot-path spans, cleanup
- Deploy Alertmanager with declarative rules
- Add spans in pipeline hot path
- Remove dead code (unused metrics, no-op OTel init, port references)
- Remove prometheus.yml per-service entries
- **Risk:** Low -- additive (spans), replacement (alerting)

## Compute Cost Impact

| Resource | Before | After | Delta |
|----------|--------|-------|-------|
| Docker containers | 3 (TimescaleDB, Redpanda, Prometheus) + Tempo | +2 (OTel Collector, Loki) | +2 containers |
| Per-agent threads | ~5-28 per process (incl HTTP server thread) | -1 per process (no HTTP server) | -24 threads total |
| Per-agent ports | 21 bound ports | 0 bound ports | -21 ports |
| Agent RSS | ~1.9 GB total | ~1.9 GB (OTel SDK is lighter than HTTP server) | Negligible |
| OTel Collector | N/A | ~100-150 MB RSS | +125 MB |
| Loki | N/A | ~50-100 MB RSS | +75 MB |

Net: +200 MB RSS for 2 new containers, -24 threads and -21 ports in agents. Simpler config, zero manual registry maintenance.
