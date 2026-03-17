---
phase: 33-five-new-i7-signal-plugins
plan: 02
subsystem: intelligence/trading
tags: [i7-plugins, fibonacci, vcp, session-levels, tdd]
dependency_graph:
  requires: [trade_framer.py, plugins.InputSpec]
  provides: [trad_PrevDayLevelTest, trad_SecondLegContinuation, trad_VCP]
  affects: [register_plugins.py (Plan 03), signal_generator_service]
tech_stack:
  added: []
  patterns: [stateful-plugin, session-reset-ET, tdd-red-green-refactor, trade-framer-delegation]
key_files:
  created:
    - src/intelligence/trading/prev_day_level_test.py
    - src/intelligence/trading/second_leg_continuation.py
    - src/intelligence/trading/vcp.py
    - tests/unit/intelligence/trading/test_prev_day_level_test.py
    - tests/unit/intelligence/trading/test_second_leg_continuation.py
    - tests/unit/intelligence/trading/test_vcp.py
  modified: []
decisions:
  - "VCP contraction tracking uses (range, volume) tuples; reset on new session date (ET)"
  - "SecondLeg Fib zone uses 38.2%-61.8% retracement band from swing_high; entry at 50% midpoint"
  - "PrevDayLevelTest tracks breakout state to detect continuation variant across calls"
metrics:
  duration: 392s
  completed: 2026-03-17
  tasks_completed: 2
  files_created: 6
  tests_passing: 31
key_decisions:
  - "Fib targets override frame_trade targets with measured-move extensions (100%/127.2%/161.8%)"
  - "VCP uses is_contraction = bar_range < last_range AND bar_volume <= last_vol (both gates required)"
  - "PrevDayLevelTest continuation variant tracked via _state['breakout_level'] key"
---

# Phase 33 Plan 02: PrevDayLevelTest + SecondLegContinuation + VCP Plugins Summary

Three I7 signal plugins implementing institutional magnet levels, Fibonacci measured-move continuations, and volatility contraction breakouts.

## What Was Built

**trad_PrevDayLevelTest** (`src/intelligence/trading/prev_day_level_test.py`)
- Fires fade or continuation setups within 0.5×ATR of PDH / PDL / PDC
- Fade: bearish bar at PDH → short; bullish bar at PDL → long
- Continuation: tracked via `_state` — once price breaks through a level, pullback to re-test fires continuation signal
- Confidence: +0.12 for regime-aligned variant (ranging → fade, trending → continuation), -0.05 for misaligned
- Regime context: `any` (handles both internally via variant logic)

**trad_SecondLegContinuation** (`src/intelligence/trading/second_leg_continuation.py`)
- Fires when close falls in the 38.2%-61.8% Fibonacci retracement zone of the prior swing
- Requires: HMM trend regime (1.0 bullish or 2.0 bearish), amplitude >= 1.0×ATR, swing age <= 50 bars
- Entry: 50% retracement midpoint (fib_50)
- Targets: 100%, 127.2%, 161.8% of Leg 1 amplitude — measured-move extensions override frame_trade ATR targets
- Confidence: base 0.55, +0.10 if hmm_regime_prob > 0.75, +0.05 if close near 50% retracement

**trad_VCP** (`src/intelligence/trading/vcp.py`)
- Fires on breakout bar after 3+ successive bars with decreasing H-L range and declining volume
- Regime gate: HMM regime 1.0 or 2.0 AND hmm_regime_prob >= 0.60 (definitional)
- Breakout confirmation: close > prior bar high (long) or close < prior bar low (short)
- Volume gate: expansion bar volume > last contraction volume × 1.2
- Session reset: clears contraction list on new ET date (preserves daily integrity)
- `contraction_count` field in output for ML attribution and signal audit

## Test Coverage

| Plugin | Tests | Key Behaviors Covered |
|--------|-------|----------------------|
| PrevDayLevelTest | 11 | No prior session data, price far from levels, fade near PDH/PDL/PDC, continuation after breakout, regime confidence alignment, frame_trade viability |
| SecondLegContinuation | 10 | Ranging regime gate, amplitude gate, missing/stale swing, outside fib zone, fires long/short, measured-move targets |
| VCP | 10 | Regime gate, prob gate, two contractions (no fire), three contractions (fires), direction follows HMM, session reset, contraction_count in output |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

All 6 files exist. Both commits exist (f26a135, 44a77c9). 31 tests passing.
