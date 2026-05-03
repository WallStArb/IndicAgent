---
phase: 077-otel-observability-unification
status: passed
verified_by: orchestrator
date: 2026-04-29
must_haves_passed: 8
must_haves_total: 8
human_verification: []
gaps: []
---

# Phase 077 Verification

## Goal
OTel Observability Unification — replace per-process HTTP metrics servers with OTLP push pipeline; deploy OTel Collector + Loki + Alertmanager; migrate BaseAgent to OTel SDK; add log bridge; refactor service_auditor to systemd discovery; add hot-path spans.

## Must-Have Checks

### ✓ 1. OTel Collector deployed in docker-compose
- `production/docker-compose.yml` — `otel-collector` service added (image: `otel/opentelemetry-collector-contrib:0.102.0`, ports 4317/4318/8889)
- `production/otel-collector-config.yaml` created — receivers: OTLP gRPC/HTTP; exporters: prometheus, otlp/tempo, loki; pipelines: metrics/traces/logs

### ✓ 2. Loki deployed and wired to Grafana
- `production/docker-compose.yml` — `loki` service added (grafana/loki:2.9.6, port 3100)
- `production/grafana/provisioning/datasources/datasource-loki.yml` created

### ✓ 3. OTel SDK wrapper classes in metrics.py
- `src/observability/metrics.py` — `OTelCounter`, `OTelGauge`, `OTelHistogram` classes present with `.labels()`, `.inc()/.set()/.observe()` API
- `_OTelLabeledCounter._total` tracker + `.get()` method present
- `_OTelLabeledGauge._last_value` tracker + `.get()` method present
- `_OTelLabeledHistogram._count` tracker + `.get_count()` method present

### ✓ 4. BaseAgent migrated to OTel (HTTP server removed)
- `src/core/agent/base.py` — `start_metrics_server` import removed; `init_otel_providers()` called in `start()`; `self._meter` from `get_meter()`
- `src/core/agent/base_writer.py` — `prometheus_client` imports replaced with `OTelCounter/OTelGauge/OTelHistogram`
- `requirements.txt` — `opentelemetry-exporter-otlp-proto-grpc>=1.20.0` added

### ✓ 5. Log bridge created
- `src/observability/log_bridge.py` created — `setup_otlp_logging()` forwards structlog WARNING+ to OTel Collector via OTLP gRPC
- Called in `BaseAgent.start()`

### ✓ 6. service_auditor refactored to systemd discovery
- `services/service_auditor_agent.py` — `ServiceSpec`/`SERVICE_REGISTRY` removed; `_discover_services()` via `systemctl list-units` added; `_evaluate_service_dynamic(unit, ...)` replaces `_evaluate_service(spec, ...)`
- `production/prometheus.yml` — collapsed from 14 scrape targets to 2 (otel-collector + alertmanager)

### ✓ 7. Alertmanager deployed with declarative rules
- `production/alertmanager-rules.yml` — 3 alert rules: ProviderDataStoppage, ServiceDown, ConsumerLagHigh
- `production/alertmanager.yml` — route + null receiver config
- `production/docker-compose.yml` — Alertmanager service on port 9093
- `production/prometheus.yml` — `rule_files` and `alerting.alertmanagers` sections added

### ✓ 8. Hot-path OTel spans added
- `services/intelligence_pipeline_agent.py` — `_process_bar` and `_run_i7` wrapped with `start_as_current_span`
- `src/providers/base_provider_agent.py` — `_publish_bar` wrapped with `start_as_current_span`
- `src/core/agent/base_writer.py` — consume loop in `_run` wrapped with span

## Test Results
- 3452 unit tests passing (8 new OTel wrapper tests + 24 service_auditor tests)
- No regressions in prior phase tests

## Known Issues (from code review — all resolved)

- **CR-01: Trace exporter uses HTTP transport to gRPC port** — RESOLVED. Code correctly uses `OTLPSpanExporter` (gRPC) with endpoint `localhost:4317`. The `http://` prefix is stripped and gRPC transport is used throughout (`otel.py`, `log_bridge.py`). The `.env` file has a commented-out 4318 value but the code default is 4317.
- **CR-02: `_OTelLabeledGauge.inc()` sets instead of accumulates** — RESOLVED. `.inc()` correctly accumulates: `self._last_value += amount` then `self._gauge.set(self._last_value, ...)`. No callers of `.dec()` exist in the codebase.
- **WR-05: `_discover_services()` may miss failed units with bullet prefix** — RESOLVED. `lstrip("●")` + fallback logic handles bullet-prefixed lines. Test `test_discover_services_strips_bullet_prefix_from_failed_units` added to cover this case.
