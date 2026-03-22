---
phase: 47-shadow-mode-graduation
plan: "01"
subsystem: intelligence-pipeline
tags: [shadow-mode, regime-gate, prometheus, weight-updater, settings]
dependency_graph:
  requires: []
  provides: [parametric-regime-gate, shadow-plugin-monitoring]
  affects: [signal_generator_service, weight_updater]
tech_stack:
  added: []
  patterns: [bootstrap-ci, prometheus-gauges, settings-fields]
key_files:
  created:
    - tests/unit/intelligence/test_shadow_stats.py
  modified:
    - src/config/settings.py
    - src/intelligence/pipeline/regime_gate.py
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py
    - tests/unit/intelligence/pipeline/test_regime_gate.py
    - tests/unit/intelligence/test_aggregator.py
    - tests/unit/service_tests/test_signal_generator_service.py
    - src/observability/metrics.py
    - src/intelligence/weight_updater.py
decisions:
  - "Safety-floor defaults (0.30/1) maximize labeled training data for Phase 49 ML"
  - "SHADOW-01 empirical validation deferred: N=0 regime-suppressed signals with outcomes"
  - "Bootstrap CI lower bound (95%, 2000 samples, seed=42) as promotion gate criterion"
metrics:
  duration_seconds: 641
  completed_date: "2026-03-22"
  tasks_completed: 3
  files_modified: 9
---

# Phase 47 Plan 01: Regime Gate Parametrization + Shadow Plugin Stats Summary

## One-liner

Parametric HMM regime gate with safety floor defaults (0.30/1) via env vars; shadow stats monitoring emitting 6 Prometheus gauges per 30-min weight-updater cycle for trad_DualDivergence promotion tracking.

## What Was Built

### Task 1: Parametric regime gate (SHADOW-01, D-01 through D-05)

The HMM regime gate was hardcoded with thresholds `_REGIME_PROB_MIN=0.55` and `_REGIME_DUR_MIN=3`. These constants were removed from `aggregator.py` and replaced with:

1. **Settings fields** — `regime_prob_min: float = Field(default=0.30)` and `regime_dur_min: int = Field(default=1)` configurable via `REGIME_PROB_MIN` / `REGIME_DUR_MIN` env vars.
2. **Parametric signature** — `apply_regime_gate(..., *, prob_min=0.30, dur_min=1)` keyword-only params.
3. **Service threading** — `signal_generator_service` stores `self._regime_prob_min` and `self._regime_dur_min` from Settings at startup, passes them to `apply_regime_gate()`.
4. **aggregator._regime_gate_signals()** — updated to accept the same parametric thresholds with matching defaults.

The lowered defaults (0.30/1 vs old 0.55/3) act as safety floors: signals with regime prob >= 0.30 and duration >= 1 now pass through to `signal_ledger`, building labeled training data for Phase 49 ML to learn optimal thresholds from data.

### Task 2: SHADOW-01 Empirical Validation

**Query result:**

```
 total_regime_suppressed | with_outcomes | wins | losses
-------------------------+---------------+------+--------
                       0 |             0 |    0 |      0
```

**SHADOW-01 empirical validation: N=0 regime-suppressed signals with outcomes.**

Insufficient data for threshold analysis (requires N >= 200). This is the expected path — the whole point of lowering to safety floors is that we do not yet have the data to optimize, and the safety floor enables data collection.

**Dated decision log (2026-03-22):**
- Safety-floor defaults (`REGIME_PROB_MIN=0.30`, `REGIME_DUR_MIN=1`) applied as prerequisite — these maximize future data collection.
- Empirical threshold optimization explicitly deferred to Phase 49 per D-03.
- Phase 49 will build XGBoost classifiers on `intelligence_features + signal_ledger` including regime-suppressed outcomes — ML will learn where threshold signal quality actually inflects.

### Task 3: Shadow plugin stats monitoring (SHADOW-04, D-06 through D-10)

Six Prometheus gauges registered at module level in `src/observability/metrics.py`:
- `shadow_n_resolved` — count of resolved shadow signals
- `shadow_win_rate` — win rate (WIN_OUTCOMES / total)
- `shadow_ev_r` — mean E[PnL_R]
- `shadow_ev_ci_lower` — 95% bootstrap CI lower bound on E[PnL_R]
- `shadow_days_to_gate` — projected days to reach N=100 at current fire rate
- `shadow_promotion_ready` — 1 when N >= 100 AND ci_lower > 0

`_bootstrap_ci_lower()` helper: 2000 bootstrap samples, fixed seed=42 for reproducibility, returns `float('-inf')` when fewer than 10 samples.

`compute_shadow_plugin_stats()` wired into `run_weight_update()` (30-min cadence) in an independent try/except block. 0-row case logs INFO (not error), emits all zeros gracefully.

When `promotion_ready=1`, logs WARNING with actionable instruction: "set IS_SHADOW=False in dual_divergence.py".

## Tests

- **test_regime_gate.py**: 13 tests (7 existing updated + 6 new parametric interface tests)
- **test_shadow_stats.py**: 9 new tests covering bootstrap CI edge cases, 0-row case, 50-row below-gate, 120-row positive CI, 120-row negative CI, and days-to-gate projection arithmetic

Full unit suite: 2734 passed (excluding 1 pre-existing failure in `test_time_of_day_gating.py` unrelated to this plan — `RollMonitor.update_volume()` signature mismatch from Phase 46.1 tws_daemon changes).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated aggregator._regime_gate_signals() to use parametric thresholds**
- **Found during:** Task 1 — ruff reported `F821 Undefined name '_REGIME_PROB_MIN'`
- **Issue:** `aggregator._regime_gate_signals()` (private helper used by `aggregate()`) still referenced the deleted module-level constants
- **Fix:** Added `prob_min` and `dur_min` keyword params to `_regime_gate_signals()` with same safety-floor defaults
- **Files modified:** `src/intelligence/trading/aggregator.py`
- **Commit:** 14db9b4

**2. [Rule 1 - Bug] Updated test_aggregator.py tests using old threshold probe values**
- **Found during:** Task 1 test run — 2 tests in `TestRegimeEligibilityFilter` and 2 in `TestShadowSignals` used probe values between the old threshold (0.55) and new safety floor (0.30)
- **Issue:** Tests expected suppression at prob=0.50/0.54 and duration=2, which now pass the new gate
- **Fix:** Updated probe values to be below the new safety floors (prob=0.20, duration=0)
- **Files modified:** `tests/unit/intelligence/test_aggregator.py`
- **Commit:** 14db9b4

**3. [Rule 2 - Missing Critical] Added _regime_prob_min/_regime_dur_min to test service factory**
- **Found during:** Task 1 service test run — `AttributeError: 'SignalGeneratorService' object has no attribute '_regime_prob_min'`
- **Issue:** `_make_svc_for_pipeline()` uses `__new__` pattern bypassing `__init__`, so new instance attributes must be manually set per CLAUDE.md convention
- **Fix:** Added `svc._regime_prob_min = 0.30` and `svc._regime_dur_min = 1` to factory
- **Files modified:** `tests/unit/service_tests/test_signal_generator_service.py`
- **Commit:** 14db9b4

## SHADOW-01 Empirical Validation (Required by must_haves)

Date: 2026-03-22

```sql
SELECT COUNT(*) AS total_regime_suppressed, COUNT(CASE WHEN outcome IS NOT NULL THEN 1 END) AS with_outcomes
FROM signal_ledger WHERE status = 'regime_suppressed';
-- Result: total=0, with_outcomes=0
```

Analysis: N=0 resolved regime-suppressed signals. Threshold bucket analysis deferred (minimum N=200 required). Safety-floor defaults applied. Phase 49 will perform empirical threshold optimization.

## Known Stubs

None — all Prometheus gauges emit real values (0 is the correct value when signal_ledger is empty).

## Self-Check: PASSED

All key files confirmed present. All acceptance criteria verified:
- regime_prob_min/regime_dur_min in settings.py
- _REGIME_MAP still in aggregator.py (type mapping preserved)
- prob_min/dur_min in regime_gate.py signature
- prob_min threaded through signal_generator_service
- All 6 SHADOW_* gauges in metrics.py
- compute_shadow_plugin_stats and _bootstrap_ci_lower in weight_updater.py
- compute_shadow_plugin_stats wired into run_weight_update
- shadow_promotion_ready WARNING log present
