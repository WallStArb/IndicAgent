---
phase: "112"
fixed_at: "2026-06-02T22:10:00Z"
review_path: ".planning/phases/112-intelligence-pipeline-signal-integrity/112-REVIEW.md"
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 112: Code Review Fix Report

**Fixed at:** 2026-06-02T22:10:00Z
**Source review:** `.planning/phases/112-intelligence-pipeline-signal-integrity/112-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (3 Critical + 6 Warning)
- Fixed: 9
- Skipped: 0

## Fixed Issues

### CR-01: Dead `raw_cis is None` check in `signal_processor.py`

**Files modified:** `src/intelligence/pipeline/signal_processor.py`, `tests/unit/pipeline/test_signal_processor.py`
**Commits:** 5ce1b662, 19e5b85a
**Applied fix:** Removed the 24-line DLQ early-exit block guarded by `if raw_cis is None`. Added a defensive `float(cis_result.cis_score or 0.0)` coercion to prevent a crash if a scorer implementation bug produces None (type contract violation). Also removed the now-unused `SIGNAL_PROCESSOR_CIS_NULL_TOTAL` import. Updated `test_process_returns_dlq_payload_on_cis_null` to `test_process_handles_cis_none_defensively`, asserting no exception and no DLQ routing (None coerced to 0.0, direction=0 path, no winner).

### CR-02: Inconsistent circuit breaker defaults in `intelligence_pipeline.py` / `executor.py`

**Files modified:** `src/intelligence/pipeline/executor.py`
**Commit:** b852217c
**Applied fix:** Changed `_get_plugin_cb()` lazy-init from `CircuitBreaker(failure_threshold=10, timeout_sec=60, enabled=True)` to `CircuitBreaker(failure_threshold=3, timeout_sec=300, enabled=False)` to match the shadow-mode defaults used by `_build_plugin_circuit_breakers()`. Added docstring explaining the alignment.

### CR-03: `confidence_calibrator.py` uses wrong column alias

**Files modified:** `src/intelligence/ml/confidence_calibrator.py`, `tests/unit/intelligence/test_confidence_calibrator.py`
**Commits:** edf02ed8, 19e5b85a, 2befc6ce
**Applied fix:** Renamed SQL alias `cis_score AS confidence` to `cis_score AS x_input` in the calibration query. Updated the downstream `r["confidence"]` list comprehension to `r["x_input"]`. Added a comment explaining this table holds CIS-level calibration curves. Updated both `_make_rows()` in the test and the `test_fit_curve_returns_correct_shapes` helper to use `x_input` key.

### WR-01: `apply_quality_gate()` called with wrong second arg in `signal_processor.py`

**Files modified:** `src/intelligence/pipeline/signal_processor.py`
**Commit:** a19080de
**Applied fix:** Replaced the `features` dict pass-through with an explicit `thresholds` dict: `{"hurst_quality": features.get("hurst_trend_quality", 1.0), "entropy_quality": features.get("entropy_quality", 1.0), "drift_penalty": cache_snapshot.drift_penalties.get(symbol, 1.0)}`. This matches the documented parameter contract of `apply_quality_gate()`.

### WR-02: `_compute_perf_multipliers()` misleading docstring in `setup_performance_updater.py`

**Files modified:** `src/intelligence/setup_performance_updater.py`
**Commit:** 515f59ba
**Applied fix:** Rewrote the docstring to explicitly state ascending sort semantics: "Best Sharpe -> multiplier=0.5 -> ranks first. Worst Sharpe -> multiplier~1.5 -> ranks last." Also added a note on the n=1 fallback explaining why multiplier=1.0 (neutral) intentionally ranks below an unvalidated setup's warm-up penalty under ascending sort.

### WR-03: `output_queue.py` drain loop re-raises on publish failure, killing the loop

**Files modified:** `src/intelligence/pipeline/output_queue.py`, `tests/unit/pipeline/test_output_queue_integration.py`
**Commits:** 84e34c60, 19e5b85a
**Applied fix:** Replaced `if first_exc is not None: raise first_exc` with a comment explaining why the re-raise is intentionally absent — re-raising kills the loop and drops all remaining queued items. Updated `test_drain_loop_calls_task_done_on_publish_exception` to assert no exception is raised (instead of `pytest.raises(RuntimeError)`).

### WR-04: `activated_at` not normalized in `_load_signal()` in `signal_tracker.py`

**Files modified:** `services/signal_tracker.py`
**Commit:** 557c45c7
**Applied fix:** Added module-level helper `_parse_optional_ts()` that applies the same `fromisoformat(value.replace("Z", "+00:00"))` normalization used for the mandatory `timestamp` field, handling None/empty/already-datetime/malformed cases. Updated `canonical["activated_at"]` assignment to call `_parse_optional_ts(raw.get("activated_at"))`.

### WR-05: Remove dead `_cis_kalman_update()` function from `signal_processor.py`

**Files modified:** `src/intelligence/pipeline/signal_processor.py`, `tests/unit/pipeline/test_signal_processor.py`
**Commit:** 21f9ba9e
**Applied fix:** Removed the 9-line `_cis_kalman_update()` function (dead since Design B migration moved Kalman to `CISScorer._apply_cis_kalman()`). Added a tombstone comment. Updated `test_module_level_helpers_exist` to assert `not hasattr(mod, "_cis_kalman_update")` instead of `callable(mod._cis_kalman_update)`.

### WR-06: BB aliases injected as None in `feature_flattening.py`

**Files modified:** `src/intelligence/pipeline/feature_flattening.py`
**Commit:** edd4b5e2
**Applied fix:** Added `if bb_20_2_mid/upper/lower is not None:` guards around each BB alias assignment, consistent with the `if v is not None:` filter applied to all other `model_dump()` fields in `build_flat_features()`.

---

_Fixed: 2026-06-02T22:10:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
