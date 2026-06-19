---
phase: 112-intelligence-pipeline-signal-integrity
plan: "04"
subsystem: intelligence-pipeline
tags: [wave-isolation, frames-migration, output-queue, circuit-breakers, health-monitor, otel-single-definition]
dependency_graph:
  requires: [PIPE-INT-03]
  provides: [PIPE-INT-04]
  affects: [executor, output_queue, per_key_worker_manager, intelligence_pipeline, plugin-tiers]
tech_stack:
  added: []
  patterns: [weighted-fair-queue, otel-single-definition, wave-isolation-contract, typed-tier-access]
key_files:
  created:
    - tests/unit/intelligence/test_no_legacy_features_access.py
    - tests/unit/intelligence/test_wave_isolation.py
  modified:
    - src/intelligence/pipeline/output_queue.py
    - src/intelligence/pipeline/executor.py
    - src/intelligence/pipeline/per_key_worker_manager.py
    - src/config/settings.py
    - services/intelligence_pipeline.py
    - tests/unit/pipeline/test_output_queue_integration.py
    - tests/unit/services/test_pipeline_backpressure.py
decisions:
  - "OutputQueue refactored to _high_queue/_low_queue; weighted-fair drain reads OUTPUT_QUEUE_DRAIN_RATIO (default 5) from settings; journal LOW-priority timeouts drop silently with intelligence_pipeline_journal_drop_total counter rather than stalling the pipeline"
  - "Circuit breakers enabled: failure_threshold=10, timeout_sec=60 — 3 failures in 300s was too aggressive for production; 10 failures in 60s better matches plugin failure modes"
  - "OTel single-definition rule (D-25): _WORKER_QUEUE_DEPTH_GAUGE and _WORKER_COUNT_GAUGE defined ONCE in per_key_worker_manager.py; intelligence_pipeline.py imports them rather than redefining, preventing duplicate OTel instrument registration"
  - "Wave isolation test uses mock plugins (not real 130+ plugins) to keep unit-test runtime fast; sentinel values in spurious tier keys prove isolation without DB/Kafka infrastructure"
  - "frames[features] migration was already complete in prior session (4-1A done); task 4-1B produced the AST-based regression test confirming zero code-level accesses remain"
metrics:
  duration_minutes: 15
  completed_date: "2026-06-02"
  tasks_completed: 5
  files_modified: 7
  tests_added: 2
---

# Phase 112 Plan 04: Pipeline Architecture Integrity Summary

One-liner: Two-queue weighted-fair OutputQueue with journal-drop counter, enabled circuit breakers (10/60), wave-isolation regression test, and OTel single-definition gauge pattern for per-key worker health monitoring.

## Tasks Completed

| Task | Name | Commit | Status |
|------|------|--------|--------|
| 4-0 | Preflight field-to-tier mapping | 24de96ce | Done (prior session) |
| 4-1A | Remove frames["features"] dual-write | edb3a70f | Done (prior session) |
| 4-1B | Plugin migration + test_no_legacy_features_access.py | 2248e002 | Done |
| 4-2 | Wave isolation regression test | 0e3cb6e2 | Done |
| 4-3 | OutputQueue dual-queue + circuit breaker enable | 8f764d02 | Done |
| 4-4 | Health monitor loop + per-key worker gauges | ba527b2e | Done |

## Changes by Task

### Task 4-1B: No-legacy-features regression test

`tests/unit/intelligence/test_no_legacy_features_access.py` walks all `.py` files under `src/intelligence/` using the Python AST (not string matching) to detect `frames["features"]` and `frames.get("features")` as executable code. The migration was already complete (all remaining matches were in comments/docstrings). Test passes with zero offenders.

### Task 4-2: Wave isolation regression test

`tests/unit/intelligence/test_wave_isolation.py` proves each of the 4 analysis waves in `_ANALYSIS_WAVES` is isolated to its declared tier dependency set. Uses lightweight mock plugins with sentinel values in spurious tier keys — FULL frames (with future-wave tier data) produce identical output to ISOLATED frames (declared deps only).

Manual spot-check (TestWaveIsolationSpotCheck): a Wave 1 mock plugin deliberately reads `frames["i5"]` (not in wave-1 declared deps). FULL frames contain a sentinel in `i5`; ISOLATED frames omit `i5`. The test catches the violation and names the differing output key. Spot-check result: the isolation test correctly detects cross-wave coupling.

### Task 4-3: OutputQueue dual-queue + circuit breakers

`output_queue.py` refactored from single `_queue` to `_high_queue` + `_low_queue`:
- HIGH: intelligence, i7_signals, dlq, aggregated/winner
- LOW: journal
- `drain_loop` implements weighted-fair drain: up to `OUTPUT_QUEUE_DRAIN_RATIO` (default 5) HIGH items per 1 LOW item. When HIGH is empty, LOW drains freely.
- Journal `enqueue_blocking` timeout silently drops with `intelligence_pipeline_journal_drop_total.add(1, {})` — never stalls the pipeline.
- `join()` awaits both queues. `task_done()` called on the correct queue per item via `_queue_for(priority)`.
- Cancel-requeue semantics preserved for both queues with priority tracking.
- `settings.py` gains `output_queue_drain_ratio` (alias `OUTPUT_QUEUE_DRAIN_RATIO`, default 5).
- `executor.py` `_get_plugin_cb` changed from `CircuitBreaker(failure_threshold=3, timeout_sec=300, enabled=False)` to `CircuitBreaker(failure_threshold=10, timeout_sec=60, enabled=True)`.
- All 5 `enqueue_blocking` call sites in `intelligence_pipeline.py` updated with explicit priority.

### Task 4-4: Health monitor + single-definition OTel gauges

`per_key_worker_manager.py` defines `_WORKER_QUEUE_DEPTH_GAUGE` and `_WORKER_COUNT_GAUGE` at module level (single source of truth). `enqueue()` increments `_enqueue_count` and emits both gauges every 10th call.

`intelligence_pipeline.py` health monitor loop imports (NOT redefines) both gauges and emits `max_queue_depth` + `worker_count` every 10 seconds. Guards against `_worker_manager` not yet initialized.

## Deviations from Plan

### Auto-fix: Updated existing tests for _queue -> _high_queue API change

**Found during:** Task 4-3 (after replacing single `_queue` with dual queues)
**Issue:** `test_output_queue_integration.py` and `test_pipeline_backpressure.py` directly accessed `q._queue` which no longer exists.
**Fix:** Updated both test files to use `q._high_queue` (the correct queue for default HIGH-priority enqueue).
**Files modified:** `tests/unit/pipeline/test_output_queue_integration.py`, `tests/unit/services/test_pipeline_backpressure.py`
**Commit:** ba527b2e

## Verification Gate Results

| Gate | Check | Result |
|------|-------|--------|
| 2-C | `grep -r "SETUP_PRIORITY" src/ services/` - only in comments | PASS |
| 2-B | AST scan: 0 code-level `frames["features"]` accesses | PASS |
| 2-B | `test_no_legacy_features_access.py` passes | PASS |
| 2-A | `test_wave_isolation.py` passes (6 tests) | PASS |
| 2-A | Spot-check: spurious read detected and named | PASS |
| 2-G | `_high_queue` and `_low_queue` defined | PASS |
| 2-G | `OUTPUT_QUEUE_DRAIN_RATIO` in settings + consumed in drain_loop | PASS |
| 2-G | `intelligence_pipeline_journal_drop_total` counter on LOW timeout | PASS |
| 1-E | Circuit breakers: `failure_threshold=10, enabled=True` | PASS |
| 2-E | Gauges defined ONCE in per_key_worker_manager.py | PASS |
| OTel | `grep 'point_gauge\|create_gauge' services/intelligence_pipeline.py` for two gauge names = 0 | PASS |
| Tests | `pytest tests/unit/ -q` — same 15 pre-existing failures, 0 new | PASS |

## Self-Check

Files verified to exist:
- `tests/unit/intelligence/test_no_legacy_features_access.py` - EXISTS
- `tests/unit/intelligence/test_wave_isolation.py` - EXISTS
- `src/intelligence/pipeline/output_queue.py` - EXISTS with `_high_queue`
- `src/intelligence/pipeline/per_key_worker_manager.py` - EXISTS with gauge definitions
- `src/config/settings.py` - EXISTS with `output_queue_drain_ratio`

Commits verified:
- 2248e002 (test 4-1B), 0e3cb6e2 (test 4-2), 8f764d02 (feat 4-3), ba527b2e (feat 4-4)

## Self-Check: PASSED
