---
phase: 077-otel-observability-unification
plan: "04"
subsystem: observability
tags: [alertmanager, otel, tracing, dead-code-cleanup, prometheus]
dependency_graph:
  requires: [otel-collector-infra, otel-sdk-migration, log-bridge]
  provides: [alertmanager-rules, hot-path-spans, clean-otel-only-metrics]
  affects: [production/docker-compose.yml, production/prometheus.yml, src/observability/metrics.py]
tech_stack:
  added:
    - prom/alertmanager:v0.27.0
  patterns:
    - Declarative Alertmanager rules replacing Python-level alerting
    - OTel start_as_current_span on hot-path methods
    - OTel wrapper classes fully replace prometheus_client in base classes
key_files:
  created:
    - production/alertmanager-rules.yml
    - production/alertmanager.yml
  modified:
    - production/docker-compose.yml
    - production/prometheus.yml
    - services/intelligence_pipeline_agent.py
    - src/core/agent/base.py
    - src/core/agent/base_writer.py
    - src/providers/base_provider_agent.py
    - src/observability/metrics.py
decisions:
  - "Alertmanager v0.27.0 on port 9093 — connects to Prometheus via alerting.alertmanagers section"
  - "Three alert rules: ProviderDataStoppage (bars_per_sec=0 for 60s), ServiceDown (up==0 for 2m), ConsumerLagHigh (lag > 5000 for 5m)"
  - "OTel spans on _publish_bar, _run_i7, _run_i7_inner (intelligence_pipeline), and _run consume loop (base_writer)"
  - "base.py and base_writer.py fully migrated from prometheus_client Counter/Gauge/Histogram to OTelCounter/OTelGauge/OTelHistogram"
  - "OTelLabeledCounter gains _total tracker + .get() method for test assertions"
  - "start_http_server import removed from metrics.py — HTTP metrics servers fully eliminated"
metrics:
  duration: "~25 minutes (partial — rate limit hit during execution, cleanup completed by orchestrator)"
  completed_date: "2026-04-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 7
---

# Phase 77 Plan 04: Alertmanager + Hot-Path Spans + Dead Code Cleanup

## What Was Built

### Task 1: Alertmanager Deployment + Hot-Path Spans

**Alertmanager Infrastructure:**
- `production/alertmanager-rules.yml` — three declarative alert rules replacing Python-level alerting in `service_auditor_agent`:
  - `ProviderDataStoppage`: fires when `bars_per_sec == 0` for 60s during active session
  - `ServiceDown`: fires when `up == 0` for 2m
  - `ConsumerLagHigh`: fires when consumer lag exceeds 5000 messages for 5m
- `production/alertmanager.yml` — route config with null receiver (Slack/PagerDuty wiring left for follow-up)
- `production/docker-compose.yml` — Alertmanager service on port 9093
- `production/prometheus.yml` — `rule_files` and `alerting.alertmanagers` sections added

**Hot-Path OTel Spans:**
- `services/intelligence_pipeline_agent.py` — `_process_bar` wraps inner logic; `_run_i7` wraps inner logic with `start_as_current_span`
- `src/providers/base_provider_agent.py` — `_publish_bar` wrapped with `start_as_current_span`
- `src/core/agent/base_writer.py` — consume loop in `_run` wrapped with `start_as_current_span`

### Task 2: Dead Code Cleanup

- `src/observability/metrics.py` — removed `start_http_server` import; renamed `_counters`/`_gauges` to `_counter_helpers`/`_gauge_helpers`; added `_total` tracker + `.get()` method to `_OTelLabeledCounter` for test assertions
- `src/core/agent/base.py` — switched from `prometheus_client.Counter/Histogram` imports to `OTelCounter/OTelHistogram` wrappers
- `src/core/agent/base_writer.py` — switched from `prometheus_client.Counter/Gauge/Histogram` to `OTelCounter/OTelGauge/OTelHistogram`; `_get_or_create_histogram` buckets made optional
- `tests/unit/test_base_agent.py` — updated crash/setup counter assertions to use `.get()` instead of `._value.get()`

## Self-Check: PASSED

All tasks completed. No STATE.md or ROADMAP.md modifications.
