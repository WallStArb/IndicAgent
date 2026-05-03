---
phase: 077-otel-observability-unification
plan: "01"
subsystem: infrastructure
tags: [otel, observability, docker, loki, prometheus, tempo]
dependency_graph:
  requires: []
  provides: [otel-collector-infra, loki-infra, grafana-loki-datasource]
  affects: [production/docker-compose.yml, production/prometheus.yml]
tech_stack:
  added:
    - otel/opentelemetry-collector-contrib:0.102.0
    - grafana/loki:2.9.6
  patterns:
    - OTel Collector as OTLP hub (agents -> Collector -> Prometheus/Tempo/Loki)
    - Prometheus exporter pattern (Collector exposes :8889 scrape endpoint)
key_files:
  created:
    - production/otel-collector-config.yaml
    - production/grafana/provisioning/datasources/datasource-loki.yml
  modified:
    - production/docker-compose.yml
    - production/tempo.yaml
    - production/prometheus.yml
decisions:
  - "Use prometheus exporter (not prometheusremotewrite) in OTel Collector — Collector exposes :8889 scrape endpoint, Prometheus pulls from it; simpler than enabling Prometheus remote_write receiver"
  - "Remove Tempo port 4318 host binding — OTel Collector now owns :4318 on host and forwards traces to Tempo internally via OTLP gRPC; avoids port conflict"
  - "Add gRPC receiver to Tempo config (tempo.yaml) — required for OTel Collector otlp/tempo exporter which uses gRPC :4317"
  - "Separate datasource-loki.yml file (not merged into datasources.yml) — follows plan spec; Grafana loads all files in provisioning directory"
metrics:
  duration: "~22 minutes"
  completed_date: "2026-04-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 3
---

# Phase 77 Plan 01: OTel Collector Infrastructure Deployment Summary

**One-liner:** OTel Collector + Loki deployed as Docker services with OTLP receivers (:4317/:4318), Prometheus scrape exporter (:8889), trace forwarding to Tempo, and Grafana Loki datasource provisioned.

## What Was Built

Docker Compose infrastructure foundation for the OTel observability unification. The OTel Collector now acts as the single OTLP ingress point for all agent telemetry. Zero agent changes — this plan is infrastructure-only per D-01.

### Files Created

- `production/otel-collector-config.yaml` — full OTel Collector pipeline config with three pipelines (metrics→prometheus exporter, traces→Tempo OTLP gRPC, logs→Loki)
- `production/grafana/provisioning/datasources/datasource-loki.yml` — auto-provisioned Loki datasource for Grafana

### Files Modified

- `production/docker-compose.yml` — added `otel-collector` service (ports 4317/4318/8889), `loki` service (port 3100), `loki-data` volume; removed port 4318 host binding from Tempo
- `production/tempo.yaml` — added gRPC receiver on :4317 so OTel Collector can forward traces
- `production/prometheus.yml` — added `otel-collector` scrape target at `host.docker.internal:8889`

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add OTel Collector to Docker Compose + write Collector config | 8575d9ee | docker-compose.yml, otel-collector-config.yaml, tempo.yaml |
| 2 | Add Prometheus remote_write config and Grafana Loki datasource | a31c4bdb | prometheus.yml, datasource-loki.yml |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Port conflict: Tempo and OTel Collector both needing :4318**
- **Found during:** Task 1
- **Issue:** Tempo had `4318:4318` host binding. OTel Collector also needs to bind :4318 on host (for OTLP HTTP from agents). Two Docker services cannot bind the same host port.
- **Fix:** Removed `ports: - "4318:4318"` from Tempo service — Tempo stays accessible internally on the Docker network. OTel Collector owns port 4318 on the host and forwards traces to Tempo internally via OTLP gRPC (:4317).
- **Files modified:** `production/docker-compose.yml`, `production/tempo.yaml`
- **Commit:** 8575d9ee

**2. [Rule 2 - Missing critical functionality] Tempo lacked gRPC receiver**
- **Found during:** Task 1
- **Issue:** Tempo's config only had OTLP HTTP receiver. The OTel Collector's `otlp/tempo` exporter uses OTLP gRPC (standard for inter-service within Docker network).
- **Fix:** Added `grpc: endpoint: 0.0.0.0:4317` to Tempo's distributor receivers in `tempo.yaml`.
- **Files modified:** `production/tempo.yaml`
- **Commit:** 8575d9ee

## Known Stubs

None. This plan is infrastructure-only — no code paths, no data flows until agents are configured to send OTLP in subsequent plans.

## Threat Flags

None. The new network surfaces (OTel Collector :4317/:4318, Loki :3100) are within the existing Docker network trust boundary documented in the plan's threat model. All exposed host ports serve the same local-network threat model as existing services.

## Self-Check

- [x] `production/otel-collector-config.yaml` exists
- [x] `production/grafana/provisioning/datasources/datasource-loki.yml` exists
- [x] `production/docker-compose.yml` contains `otel-collector:` service
- [x] `production/docker-compose.yml` contains `loki:` service with port 3100
- [x] `production/docker-compose.yml` has `loki-data:` in volumes
- [x] `production/prometheus.yml` has `otel-collector` scrape target
- [x] OTel Collector config uses `prometheus` exporter with endpoint `0.0.0.0:8889`
- [x] No Python source files modified
- [x] Commits 8575d9ee and a31c4bdb exist

## Self-Check: PASSED
