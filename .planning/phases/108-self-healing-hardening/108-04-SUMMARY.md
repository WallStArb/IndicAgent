---
phase: 108-self-healing-hardening
plan: "04"
subsystem: observability
tags: [otel, circuit-breaker, stall-detection, pipeline, self-healing]
dependency_graph:
  requires:
    - "CONSUMER_STALL_DETECTED_TOTAL counter importable from src.observability.metrics (Plan 01)"
  provides:
    - "_STALL_THRESHOLD_SECONDS = 120 in service_auditor_agent.py (HEAL-04)"
    - "CONSUMER_STALL_DETECTED_TOTAL.add() called per detected stall (HEAL-04)"
    - "PluginExecutor.circuit_breakers read-only @property (HEAL-03)"
    - "bar_e2e_latency_ms histogram recorded per bar in IntelligencePipelineComputeAgent (D-15)"
    - "CB open transition structured logs: intelligence_pipeline.cb_open / cb_closed / cb_scan_failed"
  affects:
    - "services/service_auditor_agent.py"
    - "src/intelligence/pipeline/executor.py"
    - "services/intelligence_pipeline_agent.py"
tech_stack:
  added: []
  patterns:
    - "Defensive getattr chain on CB.state.value protects bar loop from malformed CB objects"
    - "_cb_open_reported set tracks OPEN transitions to avoid log spam (emit once per transition)"
    - "Public @property exposes private dict read-only with live reference (no copy overhead)"
key_files:
  modified:
    - "services/service_auditor_agent.py"
    - "src/intelligence/pipeline/executor.py"
    - "services/intelligence_pipeline_agent.py"
decisions:
  - "120s stall threshold verified safe: at 4PM UTC (9AM EST, market open), active agents last-messaged <60s ago; llm_writer 183s was a crash-restart loop not healthy quiescence"
  - "bar_e2e_latency_ms reuses already-computed pipeline_latency_ms value (no new t0 needed per Pattern 7)"
  - "CB scan placed per-bar post-pipeline (not on a separate timer) per Open Question 3: scan cost negligible vs bar processing time"
  - "No Kafka publish for CB state per D-19: Phase 106 OTel gauge intelligence_pipeline_plugin_cb_state is the signal"
metrics:
  duration: "~12 minutes"
  completed_date: "2026-05-28"
  tasks_completed: 3
  files_modified: 3
---

# Phase 108 Plan 04: Stall Detection + CB Visibility Summary

Lowered ServiceAuditor stall threshold 3x to 120s with OTel counter, added PluginExecutor.circuit_breakers public property, and wired bar_e2e_latency_ms histogram plus CB open transition structured logs into the pipeline agent.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Lower ServiceAuditor stall threshold to 120s and add CONSUMER_STALL_DETECTED_TOTAL counter | 040e2809 | services/service_auditor_agent.py |
| 2 | Add `circuit_breakers` read-only property to PluginExecutor | 9c930677 | src/intelligence/pipeline/executor.py |
| 3 | Add CB open transition logging and bar_e2e_latency_ms histogram to IntelligencePipelineComputeAgent | c67f4e88 | services/intelligence_pipeline_agent.py |

## What Was Built

### Task 1 - ServiceAuditor stall threshold and stall counter

Changed `_STALL_THRESHOLD_SECONDS` from 360 to 120 in `services/service_auditor_agent.py`. The stall detection loop now fires 3x faster.

Added `CONSUMER_STALL_DETECTED_TOTAL` to the import block (alphabetically between existing imports) and added `.add(1, {"unit": unit})` immediately after the existing `logger.warning("service_auditor.stall_detected")` call and before `_restart_service_by_unit()`. Order is preserved: warning -> counter -> restart.

**Pre-change cadence sanity check (required per REVIEWS.md Plan 04):**

Queried `agent_last_message_timestamp_seconds` from Prometheus at 4PM UTC (9AM EST, US market open):

| Agent | Last message age |
|-------|-----------------|
| CrossAssetComputeAgent | 58s |
| MacroComputeAgent | 59s |
| llm_writer_agent | 183s |
| signal_writer_agent | 58s |

The `llm_writer_agent` at 183s appeared stale but investigation showed it was in an active crash-restart loop (watchdog kill, `code=dumped, status=6/ABRT`) - not healthy quiescence. A stale-but-crashing service is precisely the kind of stall the threshold lowering should catch. All healthy daemons were messaging within 60s. The 120s threshold is safe.

Service-auditor restarted cleanly, zero false-positive stalls observed in the 2 minutes post-deploy.

### Task 2 - PluginExecutor.circuit_breakers property

Added a `@property` named `circuit_breakers` to `PluginExecutor` immediately before the existing `shutdown()` method, in a new "Public accessors" section:

```python
@property
def circuit_breakers(self) -> dict[str, CircuitBreaker]:
    """Read-only view of per-plugin circuit breakers (Phase 108)."""
    return self._plugin_circuit_breakers
```

Returns the live dict reference (no copy). No setter defined. Eliminates the need for consumers to reach into the private `_plugin_circuit_breakers` attribute.

### Task 3 - bar_e2e_latency_ms histogram and CB open logging

Three additions to `services/intelligence_pipeline_agent.py`:

1. **bar_e2e_latency histogram** in `__init__` after `self._pipeline_latency`:
   - Name: `bar_e2e_latency_ms`, description: "End-to-end bar latency from arrival to signal enqueue", unit: ms
   - Attribute: `self._bar_e2e_latency`

2. **`self._cb_open_reported: set[str] = set()`** in `_setup` before `PerKeyWorkerManager` construction.

3. **Post-bar CB scan** in `_process_bar_compute` after `self._pipeline_latency.record()`:
   - `self._bar_e2e_latency.record(pipeline_latency_ms, ...)` reusing existing value
   - CB scan via `self._executor.circuit_breakers` (public property)
   - Defensive `getattr(getattr(cb, "state", None), "value", None)` pattern inside outer try/except
   - `intelligence_pipeline.cb_open` warning on CLOSED->OPEN (once per transition via `_cb_open_reported`)
   - `intelligence_pipeline.cb_closed` info on OPEN->CLOSED recovery
   - `intelligence_pipeline.cb_scan_failed` warning if scan raises unexpectedly
   - No Kafka publish per D-19

Intelligence pipeline restarted cleanly post-deploy. No errors in first 2 minutes.

## Verification Results

- `grep -n '_STALL_THRESHOLD_SECONDS' services/service_auditor_agent.py` - shows `120`
- `grep -n 'CONSUMER_STALL_DETECTED_TOTAL' services/service_auditor_agent.py` - 2 lines (import + .add())
- `.venv/bin/ruff check services/service_auditor_agent.py` - clean
- `systemctl is-active indicagent-service-auditor` - active
- `systemctl is-active indicagent-intelligence-pipeline` - active
- `grep -n 'def circuit_breakers' src/intelligence/pipeline/executor.py` - found with @property decorator
- `grep -n 'bar_e2e_latency_ms' services/intelligence_pipeline_agent.py` - 2 lines (create + record)
- `grep -n 'self._executor.circuit_breakers' services/intelligence_pipeline_agent.py` - 1 line
- `grep -n 'self._executor._plugin_circuit_breakers' services/intelligence_pipeline_agent.py` - 0 lines
- `grep -n 'intelligence_pipeline.cb_scan_failed' services/intelligence_pipeline_agent.py` - 1 line
- `.venv/bin/pytest tests/unit/ -q` - 4052 passed, 31 skipped (no regressions)

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `services/service_auditor_agent.py` - contains `_STALL_THRESHOLD_SECONDS = 120` and `CONSUMER_STALL_DETECTED_TOTAL.add(1, {"unit": unit})`
- `src/intelligence/pipeline/executor.py` - contains `circuit_breakers` @property returning `self._plugin_circuit_breakers`
- `services/intelligence_pipeline_agent.py` - contains `bar_e2e_latency_ms`, `_cb_open_reported`, `intelligence_pipeline.cb_open`, `intelligence_pipeline.cb_closed`, `intelligence_pipeline.cb_scan_failed`, `plugin_id=` kwarg, `self._executor.circuit_breakers`
- Commits 040e2809, 9c930677, c67f4e88 all present in git log
