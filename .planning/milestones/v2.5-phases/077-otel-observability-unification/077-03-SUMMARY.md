---
phase: 077-otel-observability-unification
plan: "03"
subsystem: observability
tags: [otel, observability, prometheus, loki, service-auditor, log-bridge, systemd]
dependency_graph:
  requires: [077-02]
  provides: [otlp-log-bridge, dynamic-service-discovery, collapsed-prometheus]
  affects:
    - src/observability/log_bridge.py
    - services/service_auditor_agent.py
    - src/core/agent/base.py
    - production/prometheus.yml
    - tests/unit/service_tests/test_service_auditor_agent.py
    - tests/conftest.py
tech_stack:
  added:
    - opentelemetry-sdk._logs (OTLP log exporter via BatchLogRecordProcessor)
  patterns:
    - Dynamic systemd discovery replacing static ServiceSpec registry
    - OTelGauge for per-unit service health metric
    - OTLP log bridge additive to file-based logging (WARNING+ forwarded to Collector)
    - Single Prometheus scrape target (OTel Collector :8889 + alertmanager :9093)
key_files:
  created:
    - src/observability/log_bridge.py
  modified:
    - services/service_auditor_agent.py
    - src/core/agent/base.py
    - production/prometheus.yml
    - tests/unit/service_tests/test_service_auditor_agent.py
    - tests/conftest.py
decisions:
  - "Strip .service suffix in _discover_services() to normalize unit names matching _DAG_ORDER keys — systemctl list-units returns names with .service; _DAG_ORDER, _LAG_THRESHOLDS, and all other dicts use bare names"
  - "Keep _AGENT_ID_TO_UNIT dict — lag metric uses agent_id labels from BaseAgent that do not match systemd unit names; 23 string pairs required for lag attribution"
  - "_fetch_prometheus_health() returns empty set as safe fallback post-OTel migration — per-service up{} metrics no longer scraped; systemd check loop provides primary health signal"
  - "Wire setup_otlp_logging() inside start() rather than __init__ — OTel providers must be initialized first (init_otel_providers is idempotent)"
  - "Fix tests/conftest.py to add services/ to sys.path — _path_bootstrap requires services/ on sys.path; worktree conftest was missing this vs main project conftest"
metrics:
  duration: "~7 minutes"
  completed_date: "2026-04-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 5
---

# Phase 77 Plan 03: Log Bridge + Service Auditor Systemd Discovery Summary

**One-liner:** OTLP log bridge created (structlog WARNING+ forwarded to Collector), ServiceAuditorAgent refactored from static ServiceSpec registry to dynamic systemd discovery with OTelGauge per unit, Prometheus collapsed to 2 scrape targets.

## What Was Built

### Files Created

- `src/observability/log_bridge.py` — `setup_otlp_logging()` function that attaches an OTLPLogExporter via BatchLogRecordProcessor to the root logger at WARNING level; non-blocking, fails silently if Collector unreachable

### Files Modified

- `services/service_auditor_agent.py` — removed `ServiceSpec` dataclass, `SERVICE_REGISTRY` list, `_SORTED_REGISTRY`, `_JOB_TO_UNIT` dict; added `_DAG_ORDER` (27 entries), `_LAG_THRESHOLDS` (17 entries), `SERVICE_UP_GAUGE` (OTelGauge), `_discover_services()` via asyncio subprocess, `_evaluate_service_dynamic()` taking unit string + lag_threshold int, `_restart_service_by_unit()` taking unit string

- `src/core/agent/base.py` — added `setup_otlp_logging(service_name=self.name)` call in `start()` after `init_otel_providers()` and before `agent.starting` log event

- `production/prometheus.yml` — collapsed from 14 scrape targets to 2: `otel-collector` (`:8889`) and `alertmanager` (`:9093`)

- `tests/unit/service_tests/test_service_auditor_agent.py` — rewrote all tests to use new dynamic API: `_evaluate_service_dynamic()`, `_restart_service_by_unit()`, `_discover_services()`, `SERVICE_UP_GAUGE`; 16 tests total, all passing

- `tests/conftest.py` — added `services/` directory to sys.path alongside project root to enable `import _path_bootstrap` in service test context (pre-existing divergence from main project conftest)

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create OTLPLogHandler + refactor service_auditor to systemd discovery | 1165fad9 | log_bridge.py, service_auditor_agent.py, test_service_auditor_agent.py, conftest.py |
| 2 | Collapse Prometheus config + wire log bridge in BaseAgent | 8ea06e99 | prometheus.yml, base.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _discover_services() sort broken due to .service suffix mismatch**
- **Found during:** Task 1 — test failure after implementation
- **Issue:** `systemctl list-units` returns unit names with `.service` suffix (e.g. `indicagent-bar-writer.service`). `_DAG_ORDER` keys use bare names (e.g. `indicagent-bar-writer`). The sort key lookup `_DAG_ORDER.get(u, 99)` always returned 99, defeating DAG ordering.
- **Fix:** Added `.removesuffix(".service")` normalization in `_discover_services()` loop. All downstream consumers (`_DAG_ORDER`, `_LAG_THRESHOLDS`, `_check_systemd_state`, `SERVICE_UP_GAUGE.labels`) receive bare names, which is what systemctl also accepts.
- **Files modified:** `services/service_auditor_agent.py`, `tests/unit/service_tests/test_service_auditor_agent.py`
- **Commit:** 1165fad9

**2. [Rule 3 - Blocking] worktree tests/conftest.py missing services/ on sys.path**
- **Found during:** Task 1 — all 16 service_auditor tests failing with `ModuleNotFoundError: No module named '_path_bootstrap'`
- **Issue:** The worktree's `tests/conftest.py` only added project root to sys.path. The main project's conftest.py (which the main project uses) also adds `services/` to sys.path. Service module files import `_path_bootstrap` as a bare module, which lives in `services/`. Without `services/` on sys.path, all service tests fail in the worktree.
- **Fix:** Added `_services_dir` insertion to worktree conftest.py matching the pattern in the main project conftest.
- **Files modified:** `tests/conftest.py`
- **Commit:** 1165fad9

## Known Stubs

None. All functional paths are wired: `setup_otlp_logging()` attaches a real OTLP handler; `_discover_services()` makes a real subprocess call; `SERVICE_UP_GAUGE` emits real OTel metrics; the Prometheus config points to a real endpoint.

## Threat Flags

None. The changes are within the trust boundaries documented in the plan's threat model:
- OTLP logs forwarded contain no PII; same boundary as file logs
- `systemctl list-units` is read-only; no injection surface (args passed as list, not shell string)
- Prometheus collapsed scrape endpoint (`host.docker.internal:8889`) is the existing OTel Collector endpoint from Plan 01

## Self-Check

- [x] `src/observability/log_bridge.py` exists with `setup_otlp_logging()` function
- [x] `services/service_auditor_agent.py` does NOT contain `class ServiceSpec`
- [x] `services/service_auditor_agent.py` does NOT contain `SERVICE_REGISTRY`
- [x] `services/service_auditor_agent.py` does NOT contain `_SORTED_REGISTRY`
- [x] `services/service_auditor_agent.py` does NOT contain `_JOB_TO_UNIT`
- [x] `services/service_auditor_agent.py` contains `_DAG_ORDER` with 27 entries (>= 20)
- [x] `services/service_auditor_agent.py` contains `_LAG_THRESHOLDS` dict
- [x] `services/service_auditor_agent.py` has `async def _discover_services()`
- [x] `services/service_auditor_agent.py` imports `OTelGauge` for SERVICE_UP_GAUGE
- [x] `services/service_auditor_agent.py` has `_evaluate_service_dynamic()` method
- [x] `services/service_auditor_agent.py` has `_restart_service_by_unit()` method
- [x] `production/prometheus.yml` has exactly 2 scrape targets (otel-collector + alertmanager)
- [x] `production/prometheus.yml` does NOT contain per-service scrape targets
- [x] `src/core/agent/base.py` calls `setup_otlp_logging()` in `start()` method
- [x] All 24 tests pass (16 service_auditor + 8 otel_metrics_wrappers)
- [x] Commits 1165fad9 and 8ea06e99 exist

## Self-Check: PASSED
