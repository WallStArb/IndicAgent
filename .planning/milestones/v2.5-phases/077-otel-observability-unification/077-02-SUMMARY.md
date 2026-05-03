---
phase: 077-otel-observability-unification
plan: "02"
subsystem: observability
tags: [otel, metrics, base-agent, otlp, grpc, wrapper-classes]
dependency_graph:
  requires: [077-01]
  provides: [otel-metric-wrappers, base-agent-otel-migration]
  affects:
    - src/observability/metrics.py
    - src/observability/otel.py
    - src/core/agent/base.py
    - requirements.txt
tech_stack:
  added:
    - opentelemetry-exporter-otlp-proto-grpc>=1.20.0
  patterns:
    - OTel SDK wrapper classes preserving prometheus_client .labels().inc()/.set()/.observe() API
    - BaseAgent initializes MeterProvider + TracerProvider via init_otel_providers() on start()
    - __getattr__ fallback for __new__ test pattern compatibility
key_files:
  created:
    - tests/unit/test_otel_metrics_wrappers.py
  modified:
    - requirements.txt
    - src/observability/otel.py
    - src/observability/metrics.py
    - src/core/agent/base.py
    - tests/unit/test_base_agent.py
decisions:
  - "Keep metrics_port in BaseAgent signature for backward compat — all 25+ service files pass it; silently ignored instead of removed"
  - "Use __getattr__ fallback for _meter/_metrics_port — handles ~149 test instances using __new__ pattern without modifying each test"
  - "OTelGauge.labels().inc() sets gauge to amount (OTel SDK has no increment for gauges)"
  - "gRPC endpoint stripping: remove http:// prefix and trailing /path for OTLPMetricExporter"
  - "Install opentelemetry-exporter-otlp-proto-grpc despite minor version conflict with existing http exporter — functional"
metrics:
  duration: "~20 minutes"
  completed_date: "2026-04-29"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 4
---

# Phase 77 Plan 02: BaseAgent OTel Migration Summary

**One-liner:** OTelCounter/OTelGauge/OTelHistogram wrapper classes preserve .labels().inc() API over OTel SDK, and BaseAgent now initializes MeterProvider + TracerProvider via OTLP gRPC instead of starting a per-process HTTP server.

## What Was Built

### TDD Execution

Followed RED/GREEN cycle:
- **RED:** Created `tests/unit/test_otel_metrics_wrappers.py` with 8 failing tests for wrapper classes and `init_otel_providers()` — commit `9ab87af7`
- **GREEN:** Implemented wrapper classes and otel.py update — all 8 tests pass — commit `70006e2c`
- **Task 2:** BaseAgent migration — no separate TDD needed as existing base_agent tests updated — commit `7fcabc19`

### Files Modified

**`requirements.txt`** — Added `opentelemetry-exporter-otlp-proto-grpc>=1.20.0` for OTLP gRPC metric export.

**`src/observability/otel.py`** — Complete rewrite:
- New `init_otel_providers(service_name, endpoint)` initializes MeterProvider (gRPC metrics) + TracerProvider (HTTP traces) with graceful degradation
- New `get_meter(name)` for OTel meter access
- `init_tracing()` kept as backward-compat shim delegating to `init_otel_providers()`
- Idempotent: checks provider class names before initialization

**`src/observability/metrics.py`** — Added 9 new classes:
- `OTelCounter` + `_OTelLabeledCounter` — `.labels(**kw).inc(amount=1.0)`
- `OTelGauge` + `_OTelLabeledGauge` — `.labels(**kw).set(value)`
- `OTelHistogram` + `_OTelLabeledHistogram` — `.labels(**kw).observe(value)`
- All existing prometheus_client definitions untouched

**`src/core/agent/base.py`** — BaseAgent migrated:
- Removed `start_metrics_server` import and call
- Added `init_otel_providers` + `get_meter` imports
- Added `self._meter = get_meter(name)` in `__init__`
- Replaced `init_tracing()` with `init_otel_providers()` in `start()`
- `metrics_port` parameter kept in signature, accepted but ignored
- Added `__getattr__` fallback for `_meter` and `_metrics_port` (handles `__new__` test pattern)

**`tests/unit/test_base_agent.py`** — Updated 2 tests:
- `test_metrics_server_started_when_port_set` → `test_metrics_port_accepted_but_no_http_server_started`
- `test_metrics_server_not_started_when_port_none` → `test_otel_providers_initialized_on_start`
- `test_metrics_port_stored` → `test_metrics_port_accepted_param`

### Files Created

**`tests/unit/test_otel_metrics_wrappers.py`** — 8 unit tests for wrapper classes using mocked OTel meter.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 (RED) | Failing tests for OTel wrappers | 9ab87af7 | test_otel_metrics_wrappers.py |
| 1 (GREEN) | OTel wrapper classes + MeterProvider init | 70006e2c | requirements.txt, otel.py, metrics.py |
| 2 | Migrate BaseAgent to OTel providers | 7fcabc19 | base.py, test_base_agent.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] grpc exporter not installed in venv**
- **Found during:** Task 1 GREEN implementation
- **Issue:** `opentelemetry-exporter-otlp-proto-grpc` was in requirements.txt but not installed in the venv
- **Fix:** Ran `pip install opentelemetry-exporter-otlp-proto-grpc>=1.20.0` — minor version conflict with http exporter (both functional)
- **Files modified:** requirements.txt (already updated)
- **Commit:** 70006e2c

**2. [Rule 1 - Bug] Module-level `_tracing_initialized` flag causes test interference**
- **Found during:** Task 2 verification
- **Issue:** `test_metrics_port_accepted_but_no_http_server_started` failed because `_tracing_initialized` was already `True` from a previous test run, causing `init_otel_providers` to never be called in the test
- **Fix:** Added explicit `_tracing_initialized = False` reset in the two affected tests with try/finally cleanup
- **Files modified:** tests/unit/test_base_agent.py
- **Commit:** 7fcabc19

## TDD Gate Compliance

- RED gate: commit `9ab87af7` (`test(077-02): add failing tests...`) — all 8 tests errored
- GREEN gate: commit `70006e2c` (`feat(077-02): OTel wrapper classes...`) — all 8 tests pass

## Known Stubs

None. The wrapper classes delegate to live OTel SDK instruments. All call sites compile and function correctly. Existing prometheus_client metrics unchanged.

## Threat Flags

None beyond plan's threat model. The added `get_meter()` export in `otel.py` is internal — no new network surface.

## Self-Check

- [x] `requirements.txt` contains `opentelemetry-exporter-otlp-proto-grpc>=1.20.0`
- [x] `src/observability/otel.py` has `init_otel_providers()` function
- [x] `src/observability/otel.py` has `get_meter()` function
- [x] `src/observability/metrics.py` has `class OTelCounter`
- [x] `src/observability/metrics.py` has `class OTelGauge`
- [x] `src/observability/metrics.py` has `class OTelHistogram`
- [x] `src/core/agent/base.py` does NOT import `start_metrics_server`
- [x] `src/core/agent/base.py` imports `init_otel_providers` from `src.observability.otel`
- [x] `src/core/agent/base.py` imports `get_meter` from `src.observability.otel`
- [x] `src/core/agent/base.py` has `self._meter = get_meter(name)` in `__init__`
- [x] `src/core/agent/base.py` has `__getattr__` fallback for `_meter` and `_metrics_port`
- [x] `src/core/agent/base.py` does NOT call `start_metrics_server` anywhere
- [x] `src/core/agent/base.py` calls `init_otel_providers` in `start()`
- [x] `src/core/agent/base.py` still accepts `metrics_port` parameter
- [x] Commits 9ab87af7, 70006e2c, 7fcabc19 exist
- [x] 39 unit tests pass (29 base_agent + 8 wrapper + 2 metrics)

## Self-Check: PASSED
