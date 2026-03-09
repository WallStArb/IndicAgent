---
phase: 21-efficiency-optimizations
plan: "04"
subsystem: observability
tags: [metrics, sampling, prometheus, plugin-execution, documentation, testing]
dependency_graph:
  requires: []
  provides: [EFF-04]
  affects:
    - src/core/service_utils.py
    - tests/unit/service_tests/test_indicator_service_sampling.py
    - tests/unit/service_tests/test_market_analysis_service_sampling.py
tech_stack:
  added: []
  patterns:
    - modulo-sampling for Prometheus write pressure reduction
    - per-(plugin, tier) counter isolation
key_files:
  created:
    - tests/unit/service_tests/test_indicator_service_sampling.py
    - tests/unit/service_tests/test_market_analysis_service_sampling.py
  modified:
    - src/core/service_utils.py
decisions:
  - "PLUGIN_METRICS_SAMPLE_RATE=10 documented with explicit modulo pattern and rationale"
  - "Error path records every call without sampling — safety invariant pinned by tests"
  - "Per-(plugin, tier) counter independence verified — cross-contamination between tiers confirmed absent"
metrics:
  duration: 223
  completed_date: "2026-03-09"
  tasks_completed: 3
  files_changed: 3
---

# Phase 21 Plan 04: Plugin Metrics Sampling Optimization Summary

**One-liner:** Documented PLUGIN_METRICS_SAMPLE_RATE modulo-sampling pattern and pinned behavior with 18 new tests across both indicator and market analysis services.

## What Was Done

The modulo sampling for Prometheus plugin metrics was already implemented correctly in both services. This plan:

1. Enhanced the `PLUGIN_METRICS_SAMPLE_RATE` constant in `src/core/service_utils.py` with a full documentation block explaining the usage pattern, the mathematical reduction (1 - 1/N with N=10 gives 90%), and the rationale (hot-path overhead reduction while preserving full error coverage).

2. Created `tests/unit/service_tests/test_indicator_service_sampling.py` with 9 tests covering:
   - 10 calls records exactly once at count=10
   - 25 calls records at counts 10 and 20
   - Sampling skips all non-multiples of SAMPLE_RATE
   - Per-plugin counter independence
   - First call never records
   - Error path records every call
   - Error path does not increment success counter
   - Integration: `_run_i1_plugins` increments `_i1_call_counts`
   - Integration: error path records without sampling

3. Created `tests/unit/service_tests/test_market_analysis_service_sampling.py` with 9 tests covering:
   - Same modulo semantics as indicator service
   - Per-(plugin, tier) tuple isolation (same plugin in different tiers are independent)
   - Cross-tier calls do not affect each other across 6 tiers (I2/I3/I4/I5/SMC/I6)
   - Integration: `_run_tier` increments `_plugin_call_counts` using `compute_full`
   - Integration: error path records every failure

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect method name in market_analysis integration test**
- **Found during:** Task 3 test run
- **Issue:** Initial test used `mock_plugin.compute` but the service calls `p.compute_full(frames)` — the mock's `compute` method was never invoked, causing the error-recording assertion to fail (0 records instead of 7)
- **Fix:** Changed both error plugin and success plugin mocks to set `compute_full` instead of `compute`
- **Files modified:** `tests/unit/service_tests/test_market_analysis_service_sampling.py`
- **Commit:** b81f35d

## Self-Check: PASSED

Files created/modified:
- FOUND: /home/bg/dev/indicagent/src/core/service_utils.py (modified)
- FOUND: /home/bg/dev/indicagent/tests/unit/service_tests/test_indicator_service_sampling.py (created)
- FOUND: /home/bg/dev/indicagent/tests/unit/service_tests/test_market_analysis_service_sampling.py (created)

Commits:
- bc83c85: docs(21-04): document PLUGIN_METRICS_SAMPLE_RATE modulo sampling pattern
- 15f052e: test(21-04): verify modulo sampling in indicator_service._run_i1_plugins
- b81f35d: test(21-04): verify modulo sampling in market_analysis_service._run_tier

Test suite: 1403 passing (was 1385 before this plan — 18 new tests added)
