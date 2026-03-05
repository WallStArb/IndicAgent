---
phase: 12-signal-integrity
plan: "04"
subsystem: signal-lifecycle
tags: [signal-lifecycle, regime-suppressed, shadow-signals, tdd, virtual-activation, mae-mfe, counterfactual]

# Dependency graph
requires:
  - phase: 12-signal-integrity/12-03
    provides: "regime_suppressed status written to signal_ledger; _SELECT_ACTIVE_SQL includes regime_suppressed"
  - phase: 12-signal-integrity/12-01
    provides: "test_lifecycle_shadow.py RED tests; virtual-activation pattern documented"
provides:
  - "Shadow signal virtual-activation: regime_suppressed signals tracked for MAE/MFE/outcome without zone-activation"
  - "signal_lifecycle_service handles regime_suppressed branch before normal pending/active paths"
  - "Shadow signals exit with status='regime_suppressed' + 8-class outcome (counterfactual data)"
  - "5 new lifecycle service tests confirming shadow signal contracts GREEN"
affects:
  - 12-signal-integrity
  - signal-lifecycle-service
  - SIGINT-05

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Virtual-activation: pass status='active' override to evaluate_signal() for regime_suppressed signals"
    - "Shadow signal MAE/MFE: initialized on first-bar-encounter, not at load — handles both startup and first-stream-bar"
    - "Status preservation: update_signal_status(status='regime_suppressed') on exit — never promotes to 'active'"

key-files:
  created:
    - "none — tests appended to existing test file"
  modified:
    - "services/signal_lifecycle_service.py — regime_suppressed branch in _evaluate_signals_against_bar()"
    - "tests/unit/service_tests/test_signal_lifecycle_service.py — 5 new shadow signal tests"

key-decisions:
  - "Shadow signals initialized on first-bar-encounter (not separate startup query) — simpler, handles both startup and stream-first-bar cases"
  - "_activated_at[sid] set from signal timestamp (virtual activation at signal bar close)"
  - "Shadow signal exit: status='regime_suppressed' passed to update_signal_status — no new DB function needed"
  - "Shadow signal continue-path: early continue after regime_suppressed block skips normal pending/active re-evaluation"

patterns-established:
  - "regime_suppressed gate check at top of per-signal loop — clear separation from pending/active logic"
  - "Virtual-activation pattern: {**sig_with_extras, 'status': 'active'} override for evaluate_signal()"

requirements-completed: [SIGINT-05]

# Metrics
duration: 4min
completed: "2026-03-04"
---

# Phase 12 Plan 04: Shadow Signal Virtual-Activation Summary

**regime_suppressed signals virtually activated at signal bar close — MAE/MFE tracked counterfactually across full lifetime, 8-class outcome recorded with status='regime_suppressed' preserved throughout**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-04T23:32:17Z
- **Completed:** 2026-03-04T23:36:05Z
- **Tasks:** 2 (Task 1 already done via Plan 03; Task 2 TDD RED+GREEN)
- **Files modified:** 2

## Accomplishments

- Shadow signal virtual-activation implemented in `signal_lifecycle_service._evaluate_signals_against_bar()` — regime_suppressed signals skip zone-activation and evaluate as immediately-active
- `_mae`/`_mfe` initialized on first-bar-encounter for regime_suppressed signals (handles both startup-load and stream-first-bar)
- Shadow signal exits recorded with `status='regime_suppressed'` (never promoted to `'active'`) — counterfactual outcome data preserved in DB
- 5 new service-level tests confirming all shadow signal contracts GREEN
- Full unit suite: 1117 passing, 0 ruff errors on modified files

## Task Commits

1. **Task 1: Extend get_active_signals SQL** - already committed in `2cf3ec0` (Plan 03)
   - `_SELECT_ACTIVE_SQL` and `_SELECT_ACTIVE_BY_SYMBOL_SQL` already include `'regime_suppressed'`
   - `test_get_active_signals_query_includes_regime_suppressed` was already GREEN

2. **Task 2: Shadow signal virtual-activation** (TDD)
   - RED: `117f674` — 5 failing tests in `test_signal_lifecycle_service.py`
   - GREEN: `23216af` — shadow signal branch in `_evaluate_signals_against_bar()`

**Plan metadata:** committed

## Files Created/Modified

- `/home/bg/dev/indicagent/services/signal_lifecycle_service.py` — regime_suppressed branch in `_evaluate_signals_against_bar()` with virtual-activation, MAE/MFE tracking, and exit handling
- `/home/bg/dev/indicagent/tests/unit/service_tests/test_signal_lifecycle_service.py` — 5 new tests: startup init, active override, zone check skipped, MAE/MFE accumulation, TTL exit with 8-class outcome

## Decisions Made

- **Shadow signal initialization on first-bar-encounter:** Rather than a separate startup scan, the lifecycle service initializes `_mae`/`_mfe` on the first time a shadow signal passes through `_evaluate_signals_against_bar`. This avoids needing a separate initialization step and handles the case where a shadow signal arrives via stream after the service has been running. The `sid not in self._mae` check is idempotent.

- **status='regime_suppressed' on exit:** The existing `update_signal_status()` signature accepts any status string. No new DB function needed — we pass `status="regime_suppressed"` directly, which writes the exit fields (outcome, mae, mfe, bars_in_trade, exit_at) while preserving the status. This means a "closed" shadow signal's final row has: `status='regime_suppressed'`, `exit_at` set, `outcome` set — clearly identifiable as counterfactual.

- **_activated_at from signal timestamp:** Shadow signals use their `timestamp` field (when the signal generator fired them) as the virtual activation time. This makes `bars_in_trade` meaningful — it measures how long the hypothetical trade would have run.

## Deviations from Plan

### Task 1 Already Implemented

**Observation:** `_SELECT_ACTIVE_SQL` and `_SELECT_ACTIVE_BY_SYMBOL_SQL` already included `'regime_suppressed'` from Plan 03 commit `2cf3ec0`. The plan noted this as Task 1, but it was done earlier.

**Handling:** Verified tests passed GREEN without any additional changes. Documented in task commits above. No code changes needed for Task 1.

---

**Total deviations:** 1 (Task 1 pre-implemented in Plan 03)
**Impact on plan:** No scope creep. All success criteria met.

## Issues Encountered

None — plan executed cleanly. The virtual-activation pattern confirmed viable via Plan 01 RED tests; implementation straightforward with the documented approach.

## Next Phase Readiness

- SIGINT-05 complete — shadow signal counterfactual tracking fully wired
- All 4 SIGINT requirements (01-05) now implemented across Plans 12-01 through 12-04
- Phase 12 complete — ready for Phase 13: Data Completeness
- Shadow signal outcome data will accumulate in `signal_ledger` with `status='regime_suppressed'` and valid 8-class outcomes — provides empirical basis for tuning regime gate threshold in future

---
*Phase: 12-signal-integrity*
*Completed: 2026-03-04*
