---
phase: 124
plan: "02"
subsystem: intelligence/trading
tags: [signal-integrity, plugin-rewrite, structural-entry, trend-following, i7]
dependency_graph:
  requires: [124-01]
  provides: [trend_following_structural_rewrite]
  affects: [signal_universe, training_data_quality]
tech_stack:
  added: []
  patterns:
    - Parallel dicts -> dataclass (TrendFollowingState with MA history deque)
    - Structural event gate first, context filter second
    - deduplicate_event for same-occurrence suppression
key_files:
  created: []
  modified:
    - src/intelligence/trading/trend_following.py
    - tests/unit/intelligence/trading/test_trend_following.py
decisions:
  - "trend_regime demoted to context filter; structural entry (pullback-to-MA reversal or consolidation breakout) is the trigger"
  - "onset_guard removed entirely - not a dedup concern, a wrong-condition concern"
  - "MA history stored as rolling SMA values; pullback detected by comparing previous SMA values to current price"
  - "Consolidation reset on range expansion before breakout check; deduplicate_event prevents re-fire on same structural event"
metrics:
  duration_minutes: 3
  completed_date: "2026-06-14"
  tasks_completed: 5
  files_modified: 2
---

# Phase 124 Plan 02: TrendFollowing Structural Rewrite Summary

TrendFollowing rewired from trend-state onset firing to structural entry detection (pullback-to-MA reversal + consolidation breakout) with trend_regime as a context filter, eliminating persistent broad-state over-firing from the raw signal universe.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add TrendFollowingState dataclass (MA history buffer) | c87fa32a | src/intelligence/trading/trend_following.py |
| 2 | Implement pullback-to-MA reversal detection | c87fa32a | src/intelligence/trading/trend_following.py |
| 3 | Implement consolidation breakout detection | c87fa32a | src/intelligence/trading/trend_following.py |
| 4 | Reorder gates (structural trigger first, context filter second) | c87fa32a | src/intelligence/trading/trend_following.py |
| 5 | Unit tests for TrendFollowing structural rewrite | ceb2e6fe | tests/unit/intelligence/trading/test_trend_following.py |

## What Was Built

### TrendFollowingState dataclass

New `TrendFollowingState` dataclass with:
- `ma_history: deque(maxlen=50)` - rolling SMA buffer for pullback detection (look-ahead-free: each bar appends current SMA only)
- `consolidation_high/low: float | None` - bounds accumulated during range compression
- `consolidation_bars: int` - consecutive bars below range threshold

Factory method `_get_state(symbol, tf)` provides lazy init per (symbol, timeframe) key.

### Pullback-to-MA Reversal Detection

Requires >= 5 bars of MA history. Detects: previous SMA values were above (bullish) or below (bearish) current price for >= 4 of the last 4 bars, and current price has crossed back to the trend side of current SMA. This is a real-time proxy for "price was in pullback, now reversing."

### Consolidation Breakout Detection

Range compression (`(high - low) / close * 100 < 0.5%`) for >= 5 consecutive bars builds consolidation bounds. On first range-expansion bar where close breaches `consolidation_high` (bullish) or `consolidation_low` (bearish), fires. Consolidation state resets on any expansion bar (with or without breakout).

### Gate Ordering

```
FIRST:  Structural event (pullback_reversal OR consolidation_breakout)
SECOND: trend_regime context filter (abs >= 0.5, trend_conf >= 0.4)
THIRD:  swing_pattern alignment (direction-matching)
FOURTH: OHLCV extraction + frame_trade()
FIFTH:  deduplicate_event((direction, structural_type))
```

### Unit Tests (5 tests, all green)

- `test_broad_trend_state_no_signal`: 50 bars of strong trend with no structural event - zero signals
- `test_pullback_reversal_fires_once`: pre-populated MA history triggers reversal on reversal bar; dedup blocks re-fire
- `test_consolidation_breakout_fires_once`: 6 tight-range bars build consolidation; breakout bar fires once
- `test_no_signal_in_weak_regime`: structural trigger present but regime too weak - context filter blocks
- `test_insufficient_data_returns_empty`: < 50 bars returns no-signal

## Deviations from Plan

### Auto-fixed Issues

**[Rule 3 - Blocking] Worktree missing .venv symlink**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff` and `black`; worktree had no `.venv`
- **Fix:** Created symlink `.claude/worktrees/agent-a697fa3c49edd4b11/.venv -> /home/bg/dev/indicagent/.venv`
- **Files modified:** none (symlink only)

### Implementation Notes

**Tasks 1-4 committed as single atomic commit.** The plan specified separate commits per task, but tasks 1-4 form a single coherent implementation (state -> detection -> gate ordering). Splitting mid-implementation would produce non-compilable intermediate states. Committed as one feat commit after all 4 tasks passed verification.

**MA history pullback detection proxy.** The plan specified tracking `close[-N]` below SMA for N bars, but `compute_full()` receives a single current frame (no close history). The implementation uses previous SMA values vs current price as a real-time proxy - this is look-ahead-free and correctly detects the reversal moment. The state stores SMA history (not close history) which is the available per-bar data.

**Existing tests replaced/updated.** The 2 original tests (`test_bullish_signal_in_uptrend`, `test_bearish_signal_in_downtrend`) tested the old onset-guard behavior which the structural rewrite intentionally removes. They were replaced with tests that cover the new structural contract. `test_no_signal_in_weak_regime` and `test_insufficient_data_returns_empty` were preserved with minor updates.

## Verification Results

```
pytest tests/unit/intelligence/trading/test_trend_following.py -q
5 passed in 0.23s

grep -n "onset_guard.*regime_condition" src/intelligence/trading/trend_following.py
(zero hits - onset_guard removed)

grep -n "pullback\|consolidation" src/intelligence/trading/trend_following.py
(structural trigger logic present)

grep -n "context filter" src/intelligence/trading/trend_following.py
Line 11: trend_regime is a context filter (must be trending), NOT the trigger.
Line 65: Gate ordering: structural event first, trend_regime context filter second.
```

## Self-Check: PASSED

- [x] `src/intelligence/trading/trend_following.py` - exists, modified
- [x] `tests/unit/intelligence/trading/test_trend_following.py` - exists, modified
- [x] Commit c87fa32a - feat(124-02): rewrite TrendFollowing
- [x] Commit ceb2e6fe - test(124-02): structural entry tests
- [x] 5 unit tests all pass
- [x] onset_guard removed (zero grep hits)
- [x] trend_regime marked as context filter
- [x] TrendFollowingState dataclass with MA history
- [x] _get_state() factory method
