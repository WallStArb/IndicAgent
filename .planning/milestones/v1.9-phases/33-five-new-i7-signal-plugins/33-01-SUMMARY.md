---
plan: 33-01
phase: 33-five-new-i7-signal-plugins
status: complete
completed_at: 2026-03-17
---

# Plan 33-01 Summary: FailedBreakout + ORB15 + ORB30 Plugins

## What Was Built

Three I7 signal plugins with full TDD coverage:

1. **`trad_FailedBreakout`** (`src/intelligence/trading/failed_breakout.py`) — BOS reversal detector. Fires when price closes back through a BOS level within 3 bars, indicating a failed breakout. `regime_type="mean_reversion"`. Tracks BOS state across bars.

2. **`trad_ORB15`** (`src/intelligence/trading/orb15.py`) — 15-minute opening range breakout. Accumulates the 09:30-09:45 ET range, fires on the first post-range breakout bar with ≥1.5× volume expansion. `regime_type="trend"`. Applies gap bias confidence adjustment.

3. **`trad_ORB30`** (`src/intelligence/trading/orb30.py`) — 30-minute opening range breakout. Identical to ORB15 but with a 09:30-10:00 ET accumulation window. Independent statistical tracking.

## Key Decisions

- Plugins are separate classes (not shared base) for independent statistical tracking and registration clarity per plan spec.
- `_in_window()` helper duplicated per-file to avoid cross-tier imports.
- ORB15 test `test_gap_bias_boosts_long_confidence` required bumping breakout close from 5025→5050 because `make_ohlcv` adds 0.2% spread to bar highs during range accumulation, raising `orb_high` to ~5025.

## Test Results

28 tests pass across 3 test files:
- `test_failed_breakout.py` — 9 tests
- `test_orb15.py` — 10 tests
- `test_orb30.py` — 6 tests (excluding min_lookback guard and module instance checks)

## Commits

- `feat(33-01): implement trad_FailedBreakout plugin with TDD tests`
- `feat(33-01): implement trad_ORB15 and trad_ORB30 plugins with TDD tests`

## Self-Check: PASSED

All must_haves verified:
- ✓ FailedBreakout fires on BOS + close-back-through within 3 bars
- ✓ FailedBreakout returns no_signal when bos_detected==0 or window exceeds 3 bars
- ✓ ORB15 accumulates 09:30-09:45 ET range, fires on breakout with volume expansion
- ✓ ORB30 accumulates 09:30-10:00 ET range, fires on breakout with volume expansion
- ✓ Both ORBs return no_signal outside 09:30-11:30 ET window
- ✓ All artifact files exist with correct class names and plugin instances
- ✓ All plugins use `from .trade_framer import frame_trade`
