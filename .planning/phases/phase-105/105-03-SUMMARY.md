---
phase: 105-architecture-hotfix-sprint
plan: 03
subsystem: observability
tags: [otel, metrics, histograms, gauges, telemetry]

# Dependency graph
requires:
  - phase: 105-architecture-hotfix-sprint
    provides: research and pattern map identifying HF-8 and HF-9 metric type mismatches
provides:
  - Six SHADOW_* metrics defined as point_gauge (create_gauge) for point-in-time observation
  - Pipeline I1/I7/pipeline latency instruments as create_histogram with live .record() calls
  - _bars_processed and _pipeline_errors as monotonic counters
affects:
  - 105-04 (shadow_auditor_agent call-site .add() -> .set() change depends on gauges existing here)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "point_gauge() factory for any metric representing current absolute value (not a delta)"
    - "self._meter.create_histogram(unit='ms') for latency measurements"
    - "time.perf_counter() delta around FPE run for I1-tier latency proxy"

key-files:
  created: []
  modified:
    - src/observability/metrics.py
    - services/intelligence_pipeline_agent.py

key-decisions:
  - "SHADOW_PROMOTION_READY is a 0/1 boolean flag representing current state -> point_gauge, same as the other five"
  - "I1 latency proxied by timing the full FPE (feature_pipeline.run) call since I1-I6 are not separately timed"
  - "gauge import removed from intelligence_pipeline_agent.py as fully replaced by counter and self._meter.create_histogram"

patterns-established:
  - "Shadow governance metrics: create_gauge (point_gauge factory) + .set() at call sites"
  - "Pipeline latency metrics: create_histogram with unit='ms' and per-bar symbol/tf labels"

requirements-completed: []

# Metrics
duration: 8min
completed: 2026-05-24
---

# Phase 105 Plan 03: OTel Metric Type Fixes Summary

**OTel metric type mismatches HF-8 and HF-9 corrected: six shadow metrics converted from accumulating up_down_counters to point-in-time gauges; three pipeline latency instruments converted from gauge to histogram with live `.record()` calls; two count metrics converted to monotonic counters.**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-24T11:42:00Z
- **Completed:** 2026-05-24T11:50:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Six `SHADOW_*` metrics (`SHADOW_N_RESOLVED`, `SHADOW_WIN_RATE`, `SHADOW_EV_R`, `SHADOW_EV_CI_LOWER`, `SHADOW_DAYS_TO_GATE`, `SHADOW_PROMOTION_READY`) changed from `_meter.create_up_down_counter` to `point_gauge()` factory - eliminates N-cycle accumulation inflation in Grafana
- Three pipeline latency instruments (`_i1_latency_ms`, `_i7_latency_ms`, `_pipeline_latency`) changed from `gauge()` to `self._meter.create_histogram(unit="ms")` with live `.record()` calls - enables p50/p95/p99 in Grafana
- Two pipeline count instruments (`_bars_processed`, `_pipeline_errors`) changed from `gauge()` to `counter()` - correct monotonic semantics
- All six metric name strings are unchanged for Grafana dashboard and Alertmanager continuity

## Task Commits

Each task was committed atomically:

1. **Task 1: Shadow governance metrics -> create_gauge (HF-8 definitions)** - `77da0702` (fix)
2. **Task 2: Pipeline latency instruments -> histograms + wire .record() (HF-9)** - `47d2b2c6` (fix)

## Files Created/Modified

- `src/observability/metrics.py` - Six SHADOW_* metrics changed from create_up_down_counter to point_gauge()
- `services/intelligence_pipeline_agent.py` - Five instruments fixed (3 histograms, 2 counters); gauge import removed; .record() calls wired for all three latency histograms

## Decisions Made

- `SHADOW_PROMOTION_READY` is a 0/1 boolean current-state flag, same pattern as the other five shadow metrics - also converted to `point_gauge`
- I1-tier latency proxied by timing the full `_feature_pipeline.run()` call (covers I1-I6) since individual I1-tier execution is not separately accessible; this is documented in source via `i1_start` variable naming
- `gauge` import removed from `intelligence_pipeline_agent.py` as all five instruments now use either `counter()` or `self._meter.create_histogram()` - ruff flagged the unused import

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `gauge` import after conversion**
- **Found during:** Task 2 verification (ruff check)
- **Issue:** After converting all five instruments, the `gauge` import became unused; ruff F401 violation
- **Fix:** Removed `gauge` from the import line (`from src.observability.metrics import THREAD_POOL_WORKERS, counter`)
- **Files modified:** `services/intelligence_pipeline_agent.py`
- **Verification:** `ruff check` exits 0
- **Committed in:** 47d2b2c6 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - unused import bug)
**Impact on plan:** Necessary for lint compliance. No scope creep.

## Issues Encountered

- Worktree had no local `.venv` symlink so pre-commit hook could not find `ruff`/`black`. Fixed by creating `ln -s /home/bg/dev/indicagent/.venv` in the worktree root. This is a worktree setup issue, not a code issue.

## Next Phase Readiness

- Plan 105-04 (shadow_auditor_agent call-site fix) can now proceed: `SHADOW_*` instruments expose `.set()` as required
- Pipeline latency histograms are live; Grafana queries using `histogram_quantile` on `intelligence_pipeline_pipeline_latency_ms` will produce real percentiles
- No blockers

---
*Phase: 105-architecture-hotfix-sprint*
*Completed: 2026-05-24*
