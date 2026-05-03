---
phase: 078-i8-alpha-feedback-loop
plan: "04"
subsystem: llm-writer
tags: [calibration, brier-score, ece, probabilistic-forecast, llm-model-scores]
dependency_graph:
  requires: []
  provides: [brier_score, calibration_slope, ece columns on llm_model_scores]
  affects: [services/llm_writer_service.py, production/migrations/079_llm_model_scores_calibration.sql]
tech_stack:
  added: [numpy.polyfit for OLS calibration slope]
  patterns: [pure helper functions at module level for testability, second fetch for per-row confidence data]
key_files:
  created:
    - production/migrations/079_llm_model_scores_calibration.sql
  modified:
    - services/llm_writer_service.py
    - tests/unit/service_tests/test_llm_writer_service.py
decisions:
  - Use a second fetch (_SELECT_CONFIDENCE_ROWS_SQL) for raw confidence+outcome rows rather than expanding the aggregate query — keeps the aggregate SQL clean and avoids expensive GROUP BY with array_agg
  - calibration_slope returns None (not 0) when std(conf) < 1e-9 or std(outcome) < 1e-9 — prevents degenerate polyfit and signals "insufficient variance" explicitly
  - N<10 threshold gates all three metrics to NULL — consistent with SCORE_MIN_N_OUTCOMES = 30 for is_significant but lower (10) for calibration since 10 points suffice for a meaningful Brier/slope estimate
  - numpy import added at module level (not inside function) — numpy is already a transitive dep; no new requirement
metrics:
  duration: "~8 minutes"
  completed: "2026-04-30"
  tasks_completed: 2
  files_changed: 3
---

# Phase 78 Plan 04: LLM Model Scores Calibration Metrics Summary

Brier score, calibration slope, and ECE added to `llm_model_scores` with full probabilistic-forecast computation in `_recompute_scores`.

## What Was Built

- **Migration 079**: Three nullable `DOUBLE PRECISION` columns on `llm_model_scores` — `brier_score`, `calibration_slope`, `ece`. Idempotent (`ADD COLUMN IF NOT EXISTS`). Applied to live DB.
- **`_brier_score(conf, outcome)`**: `mean((conf - outcome)^2)` — 0.0 = perfect, 1.0 = worst case.
- **`_calibration_slope(conf, outcome)`**: OLS slope via `numpy.polyfit`; 1.0 = perfect calibration, <1 = over-confident. Returns `None` on zero-variance confidence or outcome.
- **`_ece(conf, outcome, n_bins=10)`**: Expected Calibration Error over 10 equal-width confidence bins. Empty bins contribute 0.
- **`_recompute_scores`** updated: fetches raw confidence+outcome rows via `_SELECT_CONFIDENCE_ROWS_SQL`, builds per-group arrays, computes all three metrics (NULL when N<10), passes them as `$13/$14/$15` in the updated upsert SQL.
- **6 unit tests** (TDD RED→GREEN): brier perfect/worst, calibration slope perfect/zero-variance, ECE perfect/overconfident.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed two existing tests broken by second fetch call**
- **Found during:** Task 2 GREEN phase (full test run after implementation)
- **Issue:** `test_recompute_scores_passes_symbol_in_params` and `test_recompute_scores_defaults_symbol_to_star_when_null` used `AsyncMock(return_value=...)` for `db_manager.fetch`, but `_recompute_scores` now calls `fetch` twice. The second call returned the aggregate rows again causing `KeyError: 'confidence'`.
- **Fix:** Changed both tests to `AsyncMock(side_effect=[aggregate_rows, []])` — first call returns aggregate rows, second returns empty list (no confidence data available).
- **Files modified:** `tests/unit/service_tests/test_llm_writer_service.py`
- **Commit:** 8c3bffe9

## Known Stubs

None — all three metrics are computed from real `llm_calls` data. NULL values indicate insufficient data (N<10), not stubs.

## Threat Flags

None — only aggregate float values written. No PII. T-078-04-02 mitigated: pure functions unit-tested; upsert uses EXCLUDED path only. T-078-04-03 mitigated: second fetch runs same 15-min cadence as existing recompute.

## Self-Check

Files exist:
- production/migrations/079_llm_model_scores_calibration.sql: FOUND
- services/llm_writer_service.py: FOUND (modified)
- tests/unit/service_tests/test_llm_writer_service.py: FOUND (modified)

Commits:
- c0d978fd: chore(078-04): migration 079
- 20985439: test(078-04): RED tests
- 8c3bffe9: feat(078-04): GREEN implementation

## Self-Check: PASSED
