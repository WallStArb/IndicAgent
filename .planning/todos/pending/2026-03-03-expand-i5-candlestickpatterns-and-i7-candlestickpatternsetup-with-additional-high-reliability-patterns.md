---
created: 2026-03-03T12:15:55.701Z
title: Expand I5 CandlestickPatterns and I7 CandlestickPatternSetup with additional high-reliability patterns
area: general
files:
  - src/intelligence/patterns/candlestick_patterns.py
  - src/intelligence/trading/candlestick_pattern_setup.py
---

## Problem

Phase 10 implements `CandlestickPatternSetup` (I7) consuming 6 directional patterns already detected by I5 `CandlestickPatternsPlugin`. However, several high-reliability candlestick patterns are not yet detected at the I5 layer and therefore unavailable to I7:

- **Harami** (bull/bear) — 2-bar inside-candle reversal; very common, high reliability
- **Three White Soldiers** — 3 consecutive bullish bars; most reliable multi-bar bullish signal
- **Three Black Crows** — 3 consecutive bearish bars; most reliable multi-bar bearish signal
- **Morning Star** — 3-bar bullish reversal at downtrend end; classic high-reliability setup
- **Evening Star** — 3-bar bearish reversal at uptrend end; classic high-reliability setup
- **Dark Cloud Cover** — 2-bar bearish reversal in uptrend
- **Piercing Line** — 2-bar bullish reversal in downtrend

Research reference: https://trendspider.com/learning-center/popular-candlestick-patterns-and-categories/

## Solution

Two-step expansion:

1. **Extend I5 `CandlestickPatternsPlugin`** — add detection logic for the 7 patterns above. Each should output a `0.0`/`1.0` field following existing conventions (e.g. `harami_bull`, `harami_bear`, `three_soldiers`, `three_crows`, `morning_star`, `evening_star`, `dark_cloud_cover`, `piercing_line`). Multi-bar patterns need `min_lookback` updated (3 bars minimum).

2. **Extend I7 `CandlestickPatternSetupPlugin`** — add the new fields to the pattern eligibility list with appropriate base confidence scores:
   - Three Soldiers/Crows: 0.70 (highest — multi-bar confirmation)
   - Morning/Evening Star: 0.65 (3-bar structure)
   - Harami: 0.55 (matches engulfing tier)
   - Dark Cloud Cover / Piercing Line: 0.50

Priority ordering update: Three Soldiers/Crows > Morning/Evening Star > Hammer/Shooting Star > Engulfing > Harami > Dark Cloud/Piercing > Pin Bar.
