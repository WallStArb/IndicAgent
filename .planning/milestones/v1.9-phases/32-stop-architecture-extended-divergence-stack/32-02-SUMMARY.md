---
phase: 32-stop-architecture-extended-divergence-stack
plan: 02
subsystem: signal-lifecycle
tags: [chandelier, trailing-stop, staleness, shadow-tracking, condition-expired, lifecycle-tracker]
dependency_graph:
  requires: [32-01]
  provides: [chandelier-trailing-stop, staleness-score, condition-expired-path, shadow-tracking]
  affects: [signal_lifecycle_service, lifecycle_tracker, signal_ledger]
tech_stack:
  patterns: [pure-function-with-injected-state, in-place-mutation, shadow-tracking, tighten-monotonic]
key_files:
  modified:
    - src/intelligence/trading/lifecycle_tracker.py
    - services/signal_lifecycle_service.py
    - tests/unit/intelligence/test_lifecycle_tracker.py
    - tests/unit/service_tests/test_lifecycle_freshness.py
    - tests/unit/service_tests/test_signal_lifecycle_service.py
decisions:
  - Chandelier state mutated in-place via dict parameter to keep evaluate_signal() pure (no state ownership)
  - Shadow tracking uses explicit remaining_ttl_bars = ttl_bars - bars_elapsed (not undefined counter)
  - Vol source priority: garch_sigma_at_fire > atr_14 > zero (no Chandelier if both zero)
  - staleness_consecutive reset to 0 on service restart (conservative; avoids spurious condition_expired)
  - Tightening-only invariant: long stop only moves up, short stop only moves down
metrics:
  duration_minutes: 10
  completed_date: 2026-03-17
  tasks_completed: 2
  files_modified: 5
  tests_added: 17
---

# Phase 32 Plan 02: Chandelier Trailing Stop + Staleness Tracking Summary

Chandelier trailing stop and staleness-based condition_expired added to signal lifecycle layer. Tracker remains pure — all state (highest_high, lowest_low, staleness counters) injected from the service. Shadow tracking continues monitoring expired signals for counterfactual analysis.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Chandelier trailing stop + staleness score in lifecycle_tracker.py | 08b40ea | lifecycle_tracker.py, test_lifecycle_tracker.py |
| 2 | Chandelier state management + staleness + shadow tracking in signal_lifecycle_service.py | f97b480 | signal_lifecycle_service.py, test files |

## What Was Built

### Task 1: lifecycle_tracker.py (pure functions)

**`compute_chandelier_stop(direction, highest_high, lowest_low, vol, multiplier=3.0)`**
- Long: `highest_high - 3*vol`
- Short: `lowest_low + 3*vol`
- Vol = garch_sigma or atr_14 (caller's choice)

**`compute_staleness_score(hmm_regime_now, hmm_regime_at_fire, garch_sigma_now, garch_sigma_at_fire)`**
- `regime_drift = 1.0` if regimes differ (both non-None), else 0.0
- `sigma_component = min(1.0, log(max(ratio, 1.0)) / log(3.0))`
- `score = 0.6 * regime_drift + 0.4 * sigma_component`
- reason = "both" | "hmm_regime_flip" | "vol_drift"

**`evaluate_signal()` extended with new params:**
- `chandelier_state: dict | None` — injected, mutated in-place after no-exit bar
- `staleness_consecutive_bars: int` — consecutive bars with score > 0.5
- `staleness_score: float` — current bar's score
- Chandelier stop check fires BEFORE standard stop/target check
- condition_expired fires when `consecutive >= 3 and score > 0.5`
- Return type unchanged: `Transition | None`

### Task 2: signal_lifecycle_service.py (state management)

**New state dicts in `__init__`:**
- `_chandelier_state`: `signal_id → {trailing_stop, highest_high, lowest_low, vol, vol_source, history}`
- `_staleness_consecutive`: `signal_id → int`
- `_shadow_signals`: `signal_id → {start_ts, remaining_ttl, direction, entry, targets, stop, shadow_mae, shadow_mfe, symbol, timeframe}`

**Per-bar processing:**
- Chandelier initialized on first active bar with garch_sigma_at_fire > atr_14 priority
- `chandelier_vol_source` written to DB at initialization time (COALESCE guard)
- Staleness score computed per bar; consecutive counter incremented/reset
- `evaluate_signal()` called with injected Chandelier + staleness state
- Post-eval: trailing_stop_price JSONB history appended to DB per bar

**condition_expired handler:**
- Cleans up `_chandelier_state` and `_staleness_consecutive` on any exit
- On `condition_expired`: computes `remaining_ttl = ttl_bars - bars_elapsed`, adds to `_shadow_signals`
- Writes `shadow_tracking_start_ts` to DB

**Shadow signal loop (post active-signal loop):**
- Decrements `remaining_ttl` per bar
- Updates `shadow_mae` / `shadow_mfe` from bar close price
- On TTL expiry: writes `shadow_mae`, `shadow_mfe`, `shadow_outcome` to DB

**Startup re-seeding (`_reseed_chandelier_state()`):**
- Reads `trailing_stop_price` JSONB + `chandelier_vol_source` from DB for each active signal
- Restores last known trailing stop; resets staleness_consecutive to 0 (conservative)

## Tests

65 tests in `tests/unit/intelligence/test_lifecycle_tracker.py` (60 existing + 5 new service integration tests):
- `TestComputeChandelierStop` — formula, long/short, custom multiplier
- `TestChandelierTightening` — monotonic tightening for long and short
- `TestChandelierStopExit` — exit when price breaches trailing stop
- `TestComputeStalenessScore` — regime flip, vol drift, both, none, None guards
- `TestConditionExpired` — 3-bar confirmation, 2-bar no-fire, low score no-fire, return type
- `TestChandelierServiceStateManagement` — init on first active bar, atr fallback, cleanup on stop exit, staleness increment, shadow registration on condition_expired

Existing service test helpers updated in `test_lifecycle_freshness.py` and `test_signal_lifecycle_service.py` to set new `_chandelier_state`, `_staleness_consecutive`, `_shadow_signals` attributes (required by `__new__` pattern).

## Deviations from Plan

**[Rule 1 - Bug] Fixed missing state dict initialization in existing test helpers**
- **Found during:** Task 2 verification
- **Issue:** `_make_service()` and `_make_svc_with_db()` in existing tests use `__new__` pattern; new `__init__` attrs not set caused `AttributeError` on `_chandelier_state`
- **Fix:** Added three state dicts to all `__new__`-based test helpers
- **Files modified:** `test_lifecycle_freshness.py`, `test_signal_lifecycle_service.py`
- **Commit:** f97b480

## Self-Check: PASSED
