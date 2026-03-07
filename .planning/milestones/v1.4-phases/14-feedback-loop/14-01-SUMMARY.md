---
phase: 14-feedback-loop
plan: 01
subsystem: testing
tags: [tdd, pytest, setup-performance, feedback-loop, aggregator, signal-generator]

# Dependency graph
requires:
  - phase: 12-signal-integrity
    provides: signal_ledger with outcome + pnl_r columns (labeled training data)
  - phase: 14-feedback-loop context
    provides: FEED-01/02/03 behavioral contracts defined in 14-CONTEXT.md
provides:
  - TDD RED phase: 3 failing test files encoding FEED-01, FEED-02, FEED-03 contracts
  - compute_setup_performance contract (FEED-01 win_rate/avg_pnl_r/sample_size/sharpe_ratio)
  - Promotion gate contract (FEED-02: n<30 excluded, n>=30 included)
  - Aggregator perf_multiplier rank adjustment contract (FEED-03 aggregator side)
  - Signal generator _load_perf_weights + Redis refresh loop contract (FEED-03 service side)
affects:
  - 14-02-PLAN (implementation: setup_performance_updater module)
  - 14-03-PLAN (implementation: aggregator perf_weights kwarg + signal generator refresh loop)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD RED: module-level ImportError for non-existent modules causes pytest collection ERROR (expected)"
    - "TDD RED: TypeError from missing kwargs verified via direct call — no mock required"
    - "__new__ pattern for service tests: manually set _perf_weights = {} in factory (Plan 03 __init__ will set it)"

key-files:
  created:
    - tests/unit/intelligence/test_setup_performance_updater.py
    - tests/unit/intelligence/test_aggregator_perf.py
    - tests/unit/service_tests/test_signal_generator_perf_weights.py
  modified: []

key-decisions:
  - "Module-level import in test_setup_performance_updater.py causes ImportError at collection time — all tests ERROR in RED (expected, correct TDD RED behavior)"
  - "test_build_all_ranked_module_importable intentionally PASSES in RED — existing module is importable, only the new kwarg is missing"
  - "env_prefix (not _env_prefix) is the correct attribute name in SignalGeneratorService — verified from service source"
  - "Ruff auto-fixed import ordering in two test files (stdlib before third-party grouping)"

patterns-established:
  - "Perf multiplier contract: adjusted_rank = composite_rank * perf_multiplier, sorted ascending (lower = higher priority)"
  - "Neutral multiplier = 1.0: setups not in perf_weights dict receive no boost or suppression"
  - "Redis key pattern: {env_prefix}setup_performance:weights (matches llm_scores cache pattern)"

requirements-completed: [FEED-01, FEED-02, FEED-03]

# Metrics
duration: 3min
completed: 2026-03-06
---

# Phase 14 Plan 01: Feedback Loop RED Phase Tests Summary

**TDD RED: 3 failing test files encoding behavioral contracts for setup performance computation (FEED-01), promotion gate n>=30 (FEED-02), and perf_multiplier aggregator rank adjustment + Redis weight refresh (FEED-03)**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-06T21:56:49Z
- **Completed:** 2026-03-06T21:59:39Z
- **Tasks:** 3
- **Files modified:** 3 (all new)

## Accomplishments

- Wrote 11-test suite for `compute_setup_performance` covering empty input, FEED-02 promotion gate (n<30 excluded), win_rate formula, sharpe_ratio type, multi-setup, 30-day rolling window, null pnl_r exclusion
- Wrote 9-test suite for `_build_all_ranked` perf_weights extension: outperformer promotion, neutral multiplier fallback, adjusted_rank on output, sort by adjusted_rank ascending, aggregate() kwarg propagation
- Wrote 6-test suite for `SignalGeneratorService._load_perf_weights`: Redis hit/miss/invalid-JSON handling, env_prefix key construction, _perf_weights attribute existence, perf_weights passed to aggregate()

## Task Commits

1. **Tasks 1-3: RED phase test suite (all 3 files)** - `9d56fbd` (test)

## Files Created/Modified

- `tests/unit/intelligence/test_setup_performance_updater.py` - compute_setup_performance behavioral contract (FEED-01 + FEED-02)
- `tests/unit/intelligence/test_aggregator_perf.py` - perf_multiplier rank adjustment + aggregate() kwarg contract (FEED-03 aggregator)
- `tests/unit/service_tests/test_signal_generator_perf_weights.py` - _load_perf_weights + Redis key pattern contract (FEED-03 service)

## Decisions Made

- Module-level import in test_setup_performance_updater.py is the correct RED approach — collection ERROR means all tests in the file are marked ERROR, which is valid RED state
- `test_build_all_ranked_module_importable` intentionally passes in RED (existing module is importable — only the new `perf_weights` kwarg is missing in RED)
- `env_prefix` confirmed as the correct attribute name (not `_env_prefix`) by reading service source directly

## Deviations from Plan

None — plan executed exactly as written. Ruff auto-fixed import ordering (stdlib/third-party grouping) in two files, which is normal pre-commit hygiene.

## Issues Encountered

None — all three test files collected cleanly (except the expected ImportError for non-existent module), all behavioral tests fail in RED phase as required.

## Next Phase Readiness

- Plan 02: Implement `src/intelligence/setup_performance_updater.py` with `compute_setup_performance()` — test_setup_performance_updater.py turns GREEN
- Plan 03: Add `perf_weights` kwarg to `_build_all_ranked()` and `aggregate()`, add `_load_perf_weights()` to `SignalGeneratorService` — remaining RED tests turn GREEN

---
*Phase: 14-feedback-loop*
*Completed: 2026-03-06*
