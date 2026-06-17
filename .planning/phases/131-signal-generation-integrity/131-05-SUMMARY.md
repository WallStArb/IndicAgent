---
plan: 131-05
phase: 131
subsystem: intelligence/trading
tags: [bug-fix, gate-ordering, vwap-reversion, state-machine, unit-tests]
dependency_graph:
  requires: [131-03, 131-04]
  provides: [AnchoredVWAPReversion reclaim detection, near-zero-exit gate fix]
  affects: [trad_AnchoredVWAPReversion signal emissions]
tech_stack:
  added: []
  patterns: [near-zero-exit detection, departure-state lifecycle, D-04 gate ordering]
key_files:
  created:
    - tests/unit/test_anchored_vwap_reversion.py (TestNearZeroExitReclaim class added)
  modified:
    - src/intelligence/trading/anchored_vwap_reversion.py
decisions:
  - Use sigma_buffer (list conversion) for departure direction recovery on near-zero-exit bars
  - Clear departure state on ALL early-return paths within near-zero-exit branch
  - Use departure_sigma (historical magnitude) for confidence scoring on near-zero-exit bars
metrics:
  duration_minutes: 5
  completed_date: "2026-06-17"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 131 Plan 05: AnchoredVWAPReversion Gate Ordering Fix Summary

One-liner: Restructured compute_full() gate ordering so reclaim detection runs BEFORE departure state is cleared on near-zero-exit bars, enabling signal emission for the first time.

## What Was Built

Fixed the gate ordering bug in `trad_AnchoredVWAPReversion` that caused zero emissions despite 6,462 ESM6 1m bars with sigma >= 1.5.

**Root cause:** The reclaim bar is precisely the bar where `abs(sigma)` drops from >= sigma_min back toward zero. The original code checked `if abs(sigma) < sigma_min:` and immediately cleared departure state + returned `no_signal()` before the reclaim check ran. The plugin always cleared state on the reclaim bar without detecting it.

**Fix (D-04 invariant):** Restructured compute_full() with `_is_near_zero_exit` flag:
1. When `abs(sigma) < sigma_min` AND `departure_sigma is not None` - set `_is_near_zero_exit = True`
2. Departure onset tracking skipped on near-zero-exit bars
3. Direction recovered from `sigma_buffer` (convert deque to list, find last abs >= sigma_min entry)
4. All downstream gates (velocity, reclaim, HMM, Hurst, dedup, ATR, frame) evaluate normally
5. State cleared on ALL early-return paths within the near-zero-exit branch
6. State cleared AFTER `make_signal_from_frame()` on the happy path, BEFORE returning signal

**Confidence scoring:** Uses `departure_sigma` (historical departure magnitude) instead of current sigma (~0 on reclaim bar) to avoid collapsing sigma_magnitude factor to zero.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| T-01 | Fix gate ordering in compute_full() | b976de05 | src/intelligence/trading/anchored_vwap_reversion.py |
| T-02 | Unit tests for near-zero-exit reclaim | ca81b253 | src/intelligence/trading/anchored_vwap_reversion.py (deque fix), tests/unit/test_anchored_vwap_reversion.py |

## Verification

- `grep -n "_is_near_zero_exit" anchored_vwap_reversion.py` returns 15 matches
- `grep -n "state.departure_sigma = None"` - final clear at line 371, after `make_signal_from_frame` at line 353
- Import smoke test: passes
- `pytest tests/unit/ -q`: 4759 passed, 0 failures
- `pytest tests/unit/test_anchored_vwap_reversion.py -v`: 6/6 passed (4 pre-existing + 2 new)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed deque slice notation error**
- **Found during:** T-02 test writing (test execution)
- **Issue:** `state.sigma_buffer[:-1]` failed with `TypeError: sequence index must be integer, not 'slice'` - `deque` does not support slice notation
- **Fix:** Convert to list first: `buf_list = list(state.sigma_buffer)` then `buf_list[:-1]`
- **Files modified:** src/intelligence/trading/anchored_vwap_reversion.py
- **Commit:** ca81b253

## Self-Check

Files exist:
- [x] src/intelligence/trading/anchored_vwap_reversion.py - FOUND
- [x] tests/unit/test_anchored_vwap_reversion.py (TestNearZeroExitReclaim) - FOUND

Commits exist:
- [x] b976de05 - FOUND
- [x] ca81b253 - FOUND

## Self-Check: PASSED
