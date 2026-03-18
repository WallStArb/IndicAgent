---
phase: 35-calibration-tod-multiplier-cis-kalman-filter
plan: "03"
subsystem: signal-generator
tags: [kalman-filter, cis-score, shadow-mode, confidence-calibration, dashboard]
dependency_graph:
  requires:
    - 35-01  # LedgerEntry calibration fields (raw_cis_score, filtered_cis_score, calibrated_confidence, regime_type_at_fire)
    - 35-02  # calibrated_confidence sort key in aggregator; _cis_kalman_state stub in __init__
  provides:
    - KAL-01  # CIS Kalman filter running every bar per (symbol, tf)
    - KAL-02  # New fire condition + shadow fallback; raw/filtered CIS in LedgerEntry
  affects:
    - services/signal_generator_service.py
    - dashboard/src/components/drill-panel.tsx
    - dashboard/src/lib/types.ts
tech_stack:
  added:
    - "1D local-level Kalman filter (predict+update) applied to CIS score"
    - "Per-TF Q/R parameters loaded from config/kalman_parameters.json at import time"
  patterns:
    - "_cis_kalman_update() as pure standalone function (same recursion as KalmanTrendPlugin)"
    - "Shadow tagging via _kalman_shadow flag on selected_signal dict"
    - "Suppression reason propagated to LedgerEntry.staleness_trigger_reason"
key_files:
  created:
    - config/kalman_parameters.json
  modified:
    - services/signal_generator_service.py
    - tests/unit/service_tests/test_signal_generator_calibration.py
    - dashboard/src/components/drill-panel.tsx
    - dashboard/src/lib/types.ts
decisions:
  - "Used Path/json directly (not aliased _Path/_json) since both already imported at module level"
  - "Removed pre-existing unused get_active_contracts import during lint pass (Rule 1 auto-fix)"
  - "dashboard/src/components/signal-card.tsx does not exist — confidence headline updated in drill-panel.tsx (compact row + expanded header) which is the actual rendered signal display"
metrics:
  duration: "~15 minutes"
  tasks_completed: 3
  tasks_total: 3
  files_created: 1
  files_modified: 4
  tests_added: 5
  completed_date: "2026-03-18"
---

# Phase 35 Plan 03: CIS Kalman Filter + Shadow Fire Condition Summary

**One-liner:** 1D local-level Kalman filter smooths CIS scores per (symbol, tf) before fire condition; old-pass/new-fail signals shadow-written with suppression reason; raw/filtered/calibrated confidence trio surfaces in dashboard drill panel.

## Completed Tasks

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | config/kalman_parameters.json with cis_kalman block | 098ecee | config/kalman_parameters.json |
| 2 | CIS Kalman filter + shadow fire condition in signal_generator_service.py | 6bc46ec | services/signal_generator_service.py, tests/unit/service_tests/test_signal_generator_calibration.py |
| 3 | Dashboard calibrated_confidence headline + drill panel trio | 52c843a | dashboard/src/components/drill-panel.tsx, dashboard/src/lib/types.ts |

## What Was Built

### Task 1: config/kalman_parameters.json
Created `config/kalman_parameters.json` with `cis_kalman` block. Q=0.01 is uniform (process noise is TF-independent). R varies by TF: 1m=0.08 (highest noise → most weight on prior), 1h=0.02 (smoothest → most weight on new observation). Loaded at import time via `_load_cis_kalman_params()` with graceful fallback to `_CIS_KALMAN_DEFAULTS`.

### Task 2: CIS Kalman Filter in Signal Generator Service

**Module-level additions:**
- `_CIS_KALMAN_DEFAULTS` — fallback Q/R per TF
- `_load_cis_kalman_params()` — loads from config file, never crashes on missing file
- `_CIS_KALMAN_PARAMS` — module-level dict populated at import
- `_cis_kalman_update()` — pure function, same predict+update recursion as `KalmanTrendPlugin`

**`_process_bar()` additions (after `aggregate()`):**
- Kalman update every bar; state initialized on first bar with `x_est=raw_cis, P_est=R`
- New fire condition: `filtered_cis > 0.35 AND raw_cis > 0.28 AND buckets_agreeing >= 3`
- Old-pass/new-fail: sets `_kalman_shadow=True` on `result.selected_signal`; logs suppression reason
- Three suppression reason strings: `kalman_filtered_cis_low`, `raw_cis_low`, `buckets_agreeing_low`

**`build_ledger_entries()` extensions:**
- New kwargs: `raw_cis_score`, `filtered_cis_score` — threaded to every `LedgerEntry`
- `calibrated_confidence` and `regime_type_at_fire` populated on winner-only entries
- After `build_ledger_entries()` returns: if `_kalman_shadow` is set, flips `entry.is_shadow=True` and sets `staleness_trigger_reason`

**Tests added (5):**
- `test_cis_kalman_update_convergence` — repeated input converges to target in 200 steps
- `test_cis_kalman_update_state_updates` — state changes each call
- `test_cis_kalman_update_moves_toward_observation` — filtered value moves toward observation
- `test_cis_kalman_params_loaded` — all four TFs present in defaults
- `test_cis_kalman_1m_r_higher_than_1h` — noise ordering is correct

### Task 3: Dashboard Updates

**`dashboard/src/lib/types.ts`:**
Added three optional fields to `SignalData`:
- `raw_cis_score?: number | null`
- `filtered_cis_score?: number | null`
- `calibrated_confidence?: number | null`

**`dashboard/src/components/drill-panel.tsx`:**
- Signal list compact row (Row 1 confidence): uses `calibrated_confidence` when non-null, falls back to `confidence`
- Expanded view header confidence: same fallback pattern
- Added Phase 35 confidence pipeline trio section (raw/filtered/calibrated) in expanded view, conditionally rendered when any field is non-null

## Verification Results

```
Config:       python3 -c "import json; d=json.load(open('config/kalman_parameters.json')); assert 'cis_kalman' in d; print('OK')" → OK
Kalman fn:    grep matches: _cis_kalman_update/PARAMS/load (5 matches), filtered_cis/raw_cis_score (13 matches)
Shadow:       kalman_filtered_cis_low/raw_cis_low/buckets_agreeing_low each present (3 matches)
LedgerEntry:  raw_cis_score=raw_cis + filtered_cis_score=filtered both wired in call site
Tests:        14/14 passed (test_signal_generator_calibration.py)
Unit suite:   All 26+ tests passed (1 pre-existing failure in test_signals_route.py unrelated to this plan)
Ruff:         Only 1 pre-existing E501 on SQL line at 855 (not introduced by this plan)
Dashboard TS: No errors in changed files (drill-panel.tsx, types.ts)
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `get_active_contracts` import**
- **Found during:** Task 2 ruff check
- **Issue:** `get_active_contracts` was imported but never used — ruff F401 error
- **Fix:** Removed from import line; `get_active_symbols` retained (used)
- **Files modified:** services/signal_generator_service.py
- **Commit:** 6bc46ec

**2. [Deviation] `dashboard/src/components/signal-card.tsx` does not exist**
- **Found during:** Task 3 file read
- **Issue:** Plan references `signal-card.tsx` but actual codebase has `drill-panel.tsx` as the signal display component; `signal-card.tsx` only exists under `landing/` (marketing page)
- **Fix:** Applied all signal-card changes to `drill-panel.tsx` — both the compact row confidence headline and the expanded view confidence header use `calibrated_confidence` when non-null. This matches the plan's intent exactly.
- **Files modified:** dashboard/src/components/drill-panel.tsx

## Self-Check: PASSED

- config/kalman_parameters.json: FOUND
- services/signal_generator_service.py: FOUND
- dashboard/src/components/drill-panel.tsx: FOUND (modified)
- dashboard/src/lib/types.ts: FOUND (modified)
- Commit 098ecee (Task 1): FOUND
- Commit 6bc46ec (Task 2): FOUND
- Commit 52c843a (Task 3): FOUND
