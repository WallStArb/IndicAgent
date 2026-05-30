---
phase: 108-self-healing-hardening
plan: "01"
subsystem: observability
tags: [otel, metrics, watchdog, base-agent, fastapi]
dependency_graph:
  requires: []
  provides:
    - "DLQ_QUARANTINE_TOTAL counter importable from src.observability.metrics"
    - "CONSUMER_STALL_DETECTED_TOTAL counter importable from src.observability.metrics"
    - "JOB_COMPLETED_TOTAL counter importable from src.observability.metrics (with force_flush contract)"
    - "API_HEALTH gauge importable from src.observability.metrics"
    - "WATCHDOG_NOTIFY_TOTAL counter wired into BaseAgent._watchdog_notify()"
    - "WATCHDOG_NOTIFY_SUPPRESSED_TOTAL counter wired into BaseAgent._watchdog_notify()"
    - "opentelemetry-instrumentation-fastapi installed in venv"
  affects:
    - "src/observability/metrics.py"
    - "src/core/agent/base.py"
    - "requirements.txt"
tech_stack:
  added:
    - "opentelemetry-instrumentation-fastapi==0.62b1"
  patterns:
    - "_base_meter.create_counter for BaseAgent-level instruments (avoids duplicate OTel instrument registration)"
    - "_meter.create_counter / _meter.create_gauge for module-level instruments in metrics.py"
key_files:
  modified:
    - "src/observability/metrics.py"
    - "src/core/agent/base.py"
    - "requirements.txt"
decisions:
  - "Used _base_meter (not _meter) for watchdog counters in base.py to avoid duplicate OTel instrument registration (Pitfall 1 from RESEARCH.md)"
  - "Placed JOB_COMPLETED_TOTAL force_flush/shutdown contract as code comment directly above counter definition for in-code discoverability"
  - "API_HEALTH uses _meter.create_gauge() directly rather than point_gauge() helper for consistency with plan spec"
metrics:
  duration: "~6 minutes"
  completed_date: "2026-05-28"
  tasks_completed: 3
  files_modified: 3
---

# Phase 108 Plan 01: OTel Foundation Layer Summary

OTel foundation layer for Phase 108 self-healing hardening: four new instruments in metrics.py, two watchdog counters wired into BaseAgent, and FastAPI instrumentation dependency declared and installed.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add new OTel instruments to metrics.py | 103921c0 | src/observability/metrics.py |
| 2 | Add WATCHDOG_NOTIFY_TOTAL and WATCHDOG_NOTIFY_SUPPRESSED_TOTAL to BaseAgent | bf8cf118 | src/core/agent/base.py |
| 3 | Add opentelemetry-instrumentation-fastapi to requirements.txt | 80cd91cc | requirements.txt |

## What Was Built

### Task 1 — Four new OTel instruments in src/observability/metrics.py

Added after the existing DLQ metrics block:

- `DLQ_QUARANTINE_TOTAL` — counter for DLQ messages quarantined after DLQ_MAX_RETRIES identical errors in 24h (consumed by Plan 03)
- `CONSUMER_STALL_DETECTED_TOTAL` — counter for consumer stall events detected by ServiceAuditor before restart (consumed by Plan 04)
- `JOB_COMPLETED_TOTAL` — counter for oneshot job completions by name and status, with a code comment documenting the `force_flush()`/`shutdown()` contract for oneshot consumers (Plan 06 implements the call site)
- `API_HEALTH` — gauge for API DB connectivity: 1=reachable, 0=unreachable (consumed by Plan 05)

All four use the module-level `_meter` (not `_base_meter`) to match the existing pattern in metrics.py.

### Task 2 — Watchdog counters wired into BaseAgent._watchdog_notify()

Added two counters at module level in src/core/agent/base.py using `_base_meter`:

- `WATCHDOG_NOTIFY_TOTAL` — incremented inside `if should_notify:` branch immediately after `notifier.notify("WATCHDOG=1")`
- `WATCHDOG_NOTIFY_SUPPRESSED_TOTAL` — incremented in new `else:` branch when ping is suppressed

Label attribute is `self._last_msg_ts_attrs` = `{"agent_id": name}` per CLAUDE.md convention. All 39 daemons inherit watchdog visibility automatically.

### Task 3 — FastAPI instrumentation dependency

Added `opentelemetry-instrumentation-fastapi>=0.45b0` to requirements.txt adjacent to the existing opentelemetry-instrumentation block. Installed into the venv (resolved as 0.62b1 with required transitive deps: asgiref, opentelemetry-instrumentation-asgi, opentelemetry-util-http).

## Verification Results

- `python -c "from src.observability.metrics import DLQ_QUARANTINE_TOTAL, CONSUMER_STALL_DETECTED_TOTAL, JOB_COMPLETED_TOTAL, API_HEALTH; from src.core.agent.base import WATCHDOG_NOTIFY_TOTAL, WATCHDOG_NOTIFY_SUPPRESSED_TOTAL; from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor"` — exits 0
- `.venv/bin/pytest tests/unit/ -q` — 4052 passed, 31 skipped (no regressions)
- `.venv/bin/ruff check src/observability/metrics.py src/core/agent/base.py` — clean

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `src/observability/metrics.py` — contains all 4 new instruments
- `src/core/agent/base.py` — contains WATCHDOG_NOTIFY_TOTAL and WATCHDOG_NOTIFY_SUPPRESSED_TOTAL at module level and in _watchdog_notify()
- `requirements.txt` — contains `opentelemetry-instrumentation-fastapi>=0.45b0`
- Commits 103921c0, bf8cf118, 80cd91cc all verified present
