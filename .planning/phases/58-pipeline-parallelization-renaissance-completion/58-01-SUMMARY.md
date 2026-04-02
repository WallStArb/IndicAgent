---
phase: 58-pipeline-parallelization-renaissance-completion
plan: 01
subsystem: observability
tags: [prometheus, metrics, histogram, counter, gauge, pydantic-settings, thread-pool]

# Dependency graph
requires: []
provides:
  - PLUGIN_DURATION_MS Histogram for per-plugin execution latency (plugin_name, tier labels)
  - PLUGIN_ERRORS_TOTAL Counter for per-plugin errors (plugin_name, tier labels)
  - THREAD_POOL_WORKERS Gauge for active worker count
  - Settings.intelligence_thread_pool_workers (INTELLIGENCE_THREAD_POOL_WORKERS env var, default 0=auto)
  - Settings.pipeline_metrics_port (METRICS_PORT env var, default 9125)
  - _timed_plugin_call module-level wrapper returning (result, duration_ms) tuple
  - _collect_plugin_results wired to record labeled latency/error metrics per plugin
affects: [58-02-PLAN, 58-03-PLAN, intelligence_pipeline_agent]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-plugin labeled Prometheus metrics using direct prometheus_client (not metrics.py helpers which lack label support)
    - _timed_plugin_call wraps plugin.compute_full returning (result, duration_ms) for timing without blocking hot path
    - Backward-compatible _collect_plugin_results handles both bare dicts and (result, duration_ms) tuples

key-files:
  created: []
  modified:
    - src/observability/metrics.py
    - src/config/settings.py
    - services/intelligence_pipeline_agent.py

key-decisions:
  - "LOG_FILE env var overrides setup_service_logging path — justified exception to no-os.environ rule since logging is bootstrapped before Settings"
  - "default=0 for intelligence_thread_pool_workers means auto (cpu_count*2) — avoids surprising cpu count behavior on different machines"
  - "METRICS_PORT alias for pipeline_metrics_port — non-colliding with existing INDICAGENT_METRICS_PORT alias on metrics_port"
  - "Backward-compat branch in _collect_plugin_results for bare dict results — safe for any caller that bypasses _timed_plugin_call"

patterns-established:
  - "Per-plugin observability: labeled Histogram + Counter at module level in metrics.py, recorded in _collect_plugin_results per task"

requirements-completed: [PIPE-01, PIPE-02, PIPE-03, PIPE-06]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 58 Plan 01: Plugin Observability Foundation Summary

**Per-plugin latency histogram (PLUGIN_DURATION_MS) and error counter (PLUGIN_ERRORS_TOTAL) wired into I1/I7 pipeline tiers with configurable thread pool size and metrics port via Settings fields**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-02T08:09:28Z
- **Completed:** 2026-04-02T08:12:15Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added three new Prometheus metrics (PLUGIN_DURATION_MS Histogram, PLUGIN_ERRORS_TOTAL Counter, THREAD_POOL_WORKERS Gauge) to metrics.py using direct prometheus_client (not helpers, which lack label support)
- Added two Settings fields for runtime configuration: `intelligence_thread_pool_workers` (INTELLIGENCE_THREAD_POOL_WORKERS) and `pipeline_metrics_port` (METRICS_PORT)
- Wired per-plugin timing via `_timed_plugin_call` wrapper in I1 and I7 executor submissions; `_collect_plugin_results` now records labeled latency and error metrics per plugin per tier

## Task Commits

Each task was committed atomically:

1. **Task 1: Add three new Prometheus metrics and two Settings fields** - `b274c42` (feat)
2. **Task 2: Wire per-plugin metrics, configurable pool size and metrics port** - `7d056ad` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `src/observability/metrics.py` - Added PLUGIN_DURATION_MS, PLUGIN_ERRORS_TOTAL, THREAD_POOL_WORKERS at module level
- `src/config/settings.py` - Added intelligence_thread_pool_workers and pipeline_metrics_port Settings fields
- `services/intelligence_pipeline_agent.py` - Added _timed_plugin_call, wired metrics in _collect_plugin_results, updated __init__ for configurable port/workers, added LOG_FILE env var support

## Decisions Made
- LOG_FILE env var overrides setup_service_logging path: justified exception to no-os.environ rule since logging must be bootstrapped before Settings is fully loaded
- default=0 for intelligence_thread_pool_workers means auto (cpu_count*2): avoids confusing hard-coded defaults when deployed on different hardware
- METRICS_PORT alias does not collide with existing INDICAGENT_METRICS_PORT (different fields, different aliases)
- Backward-compatible branch in _collect_plugin_results handles bare dict results: safe fallback for any caller that bypasses _timed_plugin_call

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## Known Stubs
None - all wiring is complete. Metrics are recorded live per plugin execution.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 02 (tests) can now assert PLUGIN_DURATION_MS.labels(...).observe() is called per plugin
- Plan 03 (systemd) can add Environment=INTELLIGENCE_THREAD_POOL_WORKERS= and Environment=METRICS_PORT= to unit file
- All 3 existing parallelization tests pass confirming backward compatibility

## Self-Check: PASSED

- All 3 modified files exist on disk
- Both task commits (b274c42, 7d056ad) exist in git log
- All 3 parallelization tests pass

---
*Phase: 58-pipeline-parallelization-renaissance-completion*
*Completed: 2026-04-02*
