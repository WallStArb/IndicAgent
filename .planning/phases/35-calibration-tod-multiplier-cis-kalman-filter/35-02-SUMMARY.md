---
phase: 35-calibration-tod-multiplier-cis-kalman-filter
plan: "02"
subsystem: signal-aggregation
tags:
  - calibration
  - tod-multiplier
  - bayesian-smoothing
  - aggregator
  - signal-generator
dependency_graph:
  requires:
    - 35-01
  provides:
    - calibrated_confidence sort key in all_ranked
    - TOD multiplier pre-CIS application
    - calibration curve refresh loop
    - TOD multiplier refresh loop
  affects:
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py
tech_stack:
  added:
    - numpy (np.interp for isotonic curve evaluation)
    - zoneinfo (ET hour extraction for TOD)
  patterns:
    - Bayesian smoothing (alpha=20, session priors, clamp [0.7, 1.3])
    - isotonic regression calibrated_confidence as primary sort key
    - pre-CIS confidence mutation via TOD multiplier
key_files:
  created:
    - tests/unit/service_tests/test_signal_generator_calibration.py
  modified:
    - src/intelligence/trading/aggregator.py
    - services/signal_generator_service.py
decisions:
  - "calibrated_confidence is a new field — confidence is never mutated in aggregator"
  - "TOD multiplier applied pre-CIS: affects bucket contribution and signal selection, not just ranking"
  - "Bayesian formula: (alpha * prior + n * empirical_ratio) / (alpha + n), clamped [0.7, 1.3]"
  - "regime_type_at_fire COALESCE to 'any' handles NULL rows from pre-Phase-35 signals"
  - "_cis_kalman_state stub added in __init__ as placeholder for plan 03"
metrics:
  duration_minutes: 6
  completed_date: "2026-03-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
---

# Phase 35 Plan 02: TOD Multiplier + Calibrated Confidence Sort Key Summary

Bayesian TOD multiplier pre-CIS + isotonic calibrated_confidence sort key wired into aggregator and signal generator service.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | aggregator.py — calibrated_confidence sort key | 931cc27 | src/intelligence/trading/aggregator.py, tests/unit/service_tests/test_signal_generator_calibration.py |
| 2 | service — TOD multiplier + calibration curve refresh loops | 6644f57 | services/signal_generator_service.py |

## What Was Built

### Task 1: aggregator.py calibrated_confidence sort key (CAL-03)

- `_build_all_ranked()` extended with `calibration_curves` and `timeframe` kwargs
- Step 1d: `np.interp(raw_conf, breakpoints, values)` maps raw confidence through isotonic curve per `(setup_plugin, timeframe)` lookup
- `calibrated_confidence` written as a new dict key on every signal — `confidence` field is never mutated
- Sort key updated: when `calibrated_confidence` is non-None, it is the primary sort key (descending); fallback to raw `confidence` when no curve exists
- `aggregate()` signature extended with matching kwargs, passes both through to `_build_all_ranked()`
- `import numpy as np` added to aggregator
- 9 unit tests: 5 TOD Bayesian formula tests + 4 calibrated_confidence sort key tests

### Task 2: service TOD multiplier + refresh loops (TOD-01, TOD-02)

- Module-level constants: `_ET` (Eastern timezone), `_TOD_SESSION_PRIORS` dict, `_TOD_ALPHA=20.0`, `_TOD_CLAMP=(0.7, 1.3)`
- `__init__` adds `_calibration_curves`, `_tod_multipliers`, `_cis_kalman_state` (stub for plan 03)
- `_load_calibration_curves_from_db()`: queries `confidence_calibration WHERE sample_size >= 100`, builds `{(plugin_name, tf): (breakpoints, values)}`
- `_calibration_curves_refresh_loop()`: 1800s interval (30 min), mirrors `_cis_weights_refresh_loop` pattern
- `_load_tod_multipliers_from_db()`: queries `signal_ledger` with `COALESCE(regime_type_at_fire, 'any')`, computes Bayesian multiplier per `(regime_type, timeframe, hour_et)`, clamps to `[0.7, 1.3]`
- `_tod_multipliers_refresh_loop()`: 14400s interval (4h)
- `start()` calls both loaders at startup; both loops added to tasks list
- `_process_bar()` applies TOD multiplier pre-CIS immediately after `_filter_setup_cooldown()`, before alpha decay; lookup key `(regime_type, timeframe, _bar_hour_et)`; `tod_multiplier` field added to signal dict for observability
- `aggregate()` call updated with `calibration_curves=self._calibration_curves, timeframe=timeframe`

## Verification

All 9 unit tests pass. Ruff clean on aggregator.py. Pre-existing ruff issues on signal_generator_service.py (F401, E501) logged as out-of-scope — confirmed pre-existing via git stash check.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files Created
- tests/unit/service_tests/test_signal_generator_calibration.py: FOUND

### Files Modified
- src/intelligence/trading/aggregator.py: FOUND
- services/signal_generator_service.py: FOUND

### Commits
- 931cc27: feat(35-02): aggregator calibrated_confidence sort key (CAL-03): FOUND
- 6644f57: feat(35-02): TOD multiplier + calibration curve refresh loops in service: FOUND

## Self-Check: PASSED
