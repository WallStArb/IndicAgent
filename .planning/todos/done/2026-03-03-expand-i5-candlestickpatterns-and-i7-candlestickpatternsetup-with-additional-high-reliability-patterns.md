---
created: 2026-03-03T12:15:55.701Z
title: Expand I5 CandlestickPatterns and I7 CandlestickPatternSetup with additional high-reliability patterns
area: general
files:
  - src/intelligence/patterns/candlestick_patterns.py
  - src/intelligence/trading/candlestick_pattern_setup.py
---

## Research

Full pattern catalog, priority matrix, detection logic, I7 confidence scores, futures adaptations, and open questions:

**`docs/ideas/candlestick-pattern-expansion-research.md`**

## Problem

Phase 10 implements `CandlestickPatternSetup` (I7) consuming 6 directional patterns already detected by I5 `CandlestickPatternsPlugin`. Several high-reliability patterns are not yet detected at the I5 layer and unavailable to I7. Research doc above catalogs 18 additional patterns across two tiers.

## Solution

Two-step expansion (implement after Phase 10 implementation is complete):

**Tier 1 (10 new I5 fields) — high priority:**
- `harami_bull`, `harami_bear`, `harami_cross_bull`, `harami_cross_bear`
- `dark_cloud_cover`, `piercing_line`
- `three_white_soldiers`, `three_black_crows`
- `morning_star`, `evening_star`

**Tier 2 (8 new I5 fields) — medium priority:**
- `dragonfly_doji`, `gravestone_doji`
- `marubozu_bull`, `marubozu_bear`
- `tweezer_top`, `tweezer_bottom`
- `three_inside_up`, `three_inside_down`

**I7 priority stack** (highest base confidence first):
Three Soldiers/Crows (0.72) > Morning/Evening Star (0.65) > Three Inside Up/Down (0.65) > Dragonfly/Gravestone Doji (0.62) > Harami Cross (0.58) > Marubozu (0.58) > Hammer/Shooting Star (0.57) > Engulfing (0.55) > Dark Cloud/Piercing (0.55) > Harami (0.52) > Tweezer (0.52) > Pin Bar (0.50)

**`min_lookback` bump:** 2 → 3 (needed for 3-bar patterns).
