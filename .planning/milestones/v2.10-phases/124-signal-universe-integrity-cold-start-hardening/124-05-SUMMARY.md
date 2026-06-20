---
phase: 124
plan: 05
subsystem: intelligence/trading
tags: [i7-plugin, onset-guard, structural-rewrite, liquidity-sweep, signal-quality]
dependency_graph:
  requires: [124-01]
  provides: [liquidity_sweep_reclaim_rising_edge]
  affects: [signal_events, signal_ledger_full]
tech_stack:
  added: []
  patterns: [onset_guard_rising_edge, deduplicate_event_structural_anchor, close_above_acceptance]
key_files:
  created:
    - tests/unit/intelligence/test_liquidity_sweep_reclaim.py
  modified:
    - src/intelligence/trading/liquidity_sweep_reclaim.py
decisions:
  - onset_guard called before OHLCV extraction (threat model: missed transitions cause false fires if called conditionally)
  - close_above check uses close, not high, to reject wick-only reclaims
  - deduplicate_event placed after full gate chain, before emission
metrics:
  duration_minutes: 5
  completed_date: 2026-06-14
  tasks_completed: 5
  files_modified: 2
---

# Phase 124 Plan 05: LiquiditySweepReclaim Structural Rewrite Summary

**One-liner:** Replaced flat `sweep_reclaimed == 1.0` flag gate with `onset_guard` rising-edge detection and close-above body acceptance, preventing persistent-flag re-fires and wick-only false positives.

## What Was Built

`LiquiditySweepReclaimPlugin.compute_full()` rewritten with correct gate ordering:

1. `sweep_detected == 1.0` - sweep existence gate (FIRST)
2. `onset_guard(self._state, f"{state_key}_reclaim", sweep_reclaimed == 1.0)` - rising-edge (SECOND); flag staying hot at 1.0 produces False every bar after initial transition
3. `sweep_type != 0.0` - direction known (THIRD)
4. `close > sweep_level` (bullish) or `close < sweep_level` (bearish) - close-above body acceptance (FOURTH); wick-only reclaims rejected
5. OHLCV extraction + ATR + `frame_trade` (FIFTH)
6. `deduplicate_event(self._state, state_key, (sweep_level_rounded, sweep_type_int))` - prevents re-fire on same structural anchor (SIXTH)
7. Emit signal (SEVENTH)

## Tasks Completed

| Task | Description | Commit |
| ---- | ----------- | ------ |
| 1 | Rising-edge detection via onset_guard | 470ea77c |
| 2 | Close-above acceptance check | 470ea77c |
| 3 | Verify deduplicate_event with structural anchor | 470ea77c |
| 4 | Gate reorder (sweep_detected -> rising-edge -> type -> close-above -> OHLCV -> dedup -> emit) | 470ea77c |
| 5 | Unit tests: flag-stays-hot, rising-edge, wick-only, dedup | 1f0c5772 |

## Verification Results

```
pytest tests/unit/intelligence/test_liquidity_sweep_reclaim.py -v
7 passed in 0.25s
```

All plan verification checks pass:
- `grep -n "onset_guard.*reclaim"` returns rising-edge detection
- `grep -n "close.*sweep_level"` returns close-above acceptance check
- `grep -n "deduplicate_event.*sweep_level"` returns dedup call

## Deviations from Plan

**1. [Rule 1 - Bug] onset_guard placement before OHLCV extraction**
- **Found during:** Task 1 - reading state_utils.py docstring
- **Issue:** State_utils.py docstring says "PLACEMENT: call AFTER all downstream gates"; however the threat model in the plan explicitly overrides this: "onset_guard called UNCONDITIONALLY so it sees False when flag drops - enables proper rearm"
- **Resolution:** onset_guard placed after features merge and sweep_detected gate, but before OHLCV extraction - matches threat model intent (unconditional relative to sweep_detected check)

**2. [Adaptation] Test assertion style**
- **Found during:** Task 5 - first test run
- **Issue:** `no_signal()` returns `{"signal_type": "none", ...}` not `None`; initial tests used `is None` assertions
- **Fix:** Added `_is_no_signal()` helper checking for `"none"` string; all 7 tests pass

## Self-Check

Files created:
- [x] `tests/unit/intelligence/test_liquidity_sweep_reclaim.py` - exists
- [x] `src/intelligence/trading/liquidity_sweep_reclaim.py` - modified

Commits:
- [x] 470ea77c - rewrite commit
- [x] 1f0c5772 - test commit

## Self-Check: PASSED
