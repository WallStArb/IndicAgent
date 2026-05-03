# Phase 77: OTel Observability Unification - Context

**Gathered:** 2026-04-28
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-28-otel-observability-unification-design.md)

<domain>
## Phase Boundary

Replace the ad-hoc monitoring stack with industry-standard OTel Collector:
- **Remove:** 24 per-process HTTP metrics servers, manual ServiceSpec registry, Python-level alerting
- **Add:** OTel Collector, OTLP push pipeline, Alertmanager, Loki, OTel SDK metrics/traces/logs
- **Refactor:** service_auditor_agent from alert evaluator to lightweight state emitter
- **NOT in scope:** ML pipeline changes, signal generation, trading logic, dashboard frontend
</domain>

<decisions>
## Implementation Decisions

### Migration Path — Four Deployable Phases
- D-01: Phase A — Deploy OTel Collector (infrastructure only, no agent changes). Zero risk.
- D-02: Phase B — Migrate BaseAgent to OTel SDK (metrics + traces). Thin wrapper classes preserve existing API.
- D-03: Phase C — Add log bridge, collapse Prometheus config, refactor service_auditor. Medium risk.
- D-04: Phase D — Add Alertmanager, hot-path spans, cleanup dead code. Low risk.

### BaseAgent Changes (D-02)
- Remove `_metrics_port` parameter and `start_http_server()` call
- Add OTel MeterProvider + TracerProvider initialization in `__init__`
- Graceful degradation: if Collector unreachable at startup, fall back to no-op providers

### Metrics Migration Strategy (D-02)
- Thin wrapper classes (OTelCounter, OTelGauge, OTelHistogram) in `metrics.py` provide `.labels().inc()` interface
- Existing call sites work unchanged while underlying export switches to OTLP
- API mapping: Counter.inc() → Counter.add(), Gauge.set() → Gauge.set(), Histogram.observe() → Histogram.record()

### OTel Collector Configuration (D-01)
- New Docker container alongside existing Prometheus and Tempo
- Receivers: OTLP gRPC :4317, OTLP HTTP :4318
- Exporters: Prometheus :8889, OTLP→Tempo, Loki
- Config: `production/otel-collector-config.yaml`

### Log Bridge (D-03)
- OTLPLogHandler attaches to Python root logger
- Structured log events forwarded to OTel Collector's OTLP log receiver
- File rotation in `logs/` kept as backup; OTLP export is additive

### Service Auditor Refactoring (D-03)
- Remove SERVICE_REGISTRY manual list, ServiceSpec per-service config, _AGENT_ID_TO_UNIT, _JOB_TO_UNIT
- Replace with dynamic systemd discovery: `systemctl list-units --all --no-legend 'indicagent-*'`
- DAG ordering from single static dict (unit → dag_order), not full ServiceSpec per service
- Expose service health as OTel metrics: `indicagent_service_up{unit="..."} = 1`
- Alert evaluation moves to Prometheus Alertmanager

### Alertmanager Integration (D-04)
- Declarative rules in `production/alertmanager-rules.yml`
- Rules: ProviderDataStoppage, ServiceDown, ConsumerLagHigh
- Replace Python-level alerting logic from service_auditor

### Distributed Tracing (D-02 + D-04)
- Kafka trace propagation already implemented (kafka_utils.py inject/extract)
- Activation requires real TracerProvider (not no-op) — done in D-02
- Hot-path spans added in D-04: _publish_bar(), _process_message(), _run_pipeline(), _evaluate_signal()

### Prometheus Config Collapse (D-03)
- 24 scrape targets → 1 target (OTel Collector's Prometheus exporter :8889)
- Metric names and labels preserved through OTel Collector
- Existing Grafana dashboards work unchanged

### Claude's Discretion
- Exact OTel SDK Python package version selection
- Exact wrapper class implementation details in metrics.py
- Specific Alertmanager notification channels and routing
- Loki label schema and retention policies
- Test strategy for wrapper class migration
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Specification
- `docs/plans/2026-04-28-otel-observability-unification-design.md` — Full architectural design with before/after tables, cost impact analysis, migration phases

### Infrastructure
- `src/core/kafka_utils.py` — Existing W3C traceparent inject/extract (lines 104-107 producer, 278-287 consumer)
- `src/observability/metrics.py` — Current prometheus_client metric definitions (all must be wrapped)
- `src/core/agent/base.py` — BaseAgent with init_tracing(), _metrics_port, start_http_server()
- `src/core/agent/base_writer.py` — BaseWriterAgent (inherits BaseAgent)
- `src/core/agent/base_provider.py` — BaseProviderAgent (inherits BaseAgent)

### Service Infrastructure
- `services/service_auditor_agent.py` — Current SERVICE_REGISTRY, ServiceSpec, _JOB_TO_UNIT, Python alerting
- `production/prometheus.yml` — Current 24-target scrape config
- `production/docker-compose.yml` (or equivalent) — Current Docker containers (TimescaleDB, Redpanda, Prometheus, Tempo)

### Prior Art (Already Implemented)
- Phase 52.7: Tempo deployed, Grafana datasource provisioned
- Phase 52.8: Kafka trace propagation (inject/extract in kafka_utils.py)
- Phase 71: Auto init_tracing() in BaseAgent
</canonical_refs>

<specifics>
## Specific Ideas

### OTel Collector Config (verbatim from design doc)
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
```

### Alertmanager Rules (verbatim from design doc)
```yaml
groups:
  - name: indicagent_pipeline
    rules:
      - alert: ProviderDataStoppage
        expr: rate(provider_bars_produced_total[5m]) == 0 and indicagent_session_open == 1
        for: 30s
        labels:
          severity: critical
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

### prometheus_client → OTel SDK API Mapping
| prometheus_client | OTel SDK |
|-------------------|----------|
| Counter("name", "help", ["label"]) | meter.create_counter("name", description="help") |
| counter.labels(x="y").inc() | counter.add(1, {"x": "y"}) |
| Gauge("name", "help", ["label"]) | meter.create_gauge("name", description="help") |
| gauge.labels(x="y").set(v) | gauge.set(v, {"x": "y"}) |
| Histogram("name", "help", ["label"]) | meter.create_histogram("name", description="help") |
| hist.labels(x="y").observe(v) | hist.record(v, {"x": "y"}) |

### Compute Cost Impact
- +2 Docker containers (OTel Collector ~125MB, Loki ~75MB)
- -24 threads, -21 ports across agents
- Negligible agent RSS change (OTel SDK lighter than HTTP server)
</specifics>

<deferred>
## Deferred Ideas

- Per-message Kafka spans (too expensive at production throughput)
- Custom Grafana dashboards for OTel data (use existing dashboards initially)
- OTel Collector horizontal scaling (single collector sufficient for current throughput)
- Object storage backend for Tempo (future optimization)
</deferred>

---

*Phase: 77-otel-observability-unification*
*Context gathered: 2026-04-28 via PRD Express Path*
