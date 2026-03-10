---
created: 2026-03-04T00:00:00.000Z
title: Add AC Oscillator I1 plugin (Bill Williams)
area: intelligence
files:
  - src/intelligence/indicators/
  - src/intelligence/register_plugins.py
  - tests/unit/intelligence/indicators/
---

## Problem

No Bill Williams momentum framework in the pipeline. The Awesome Oscillator (AO) and Acceleration/Deceleration Oscillator (AC) form a new signal family — midpoint SMA-based, different from MACD's EMA-based approach. AC crosses zero before AO does, giving earlier signals.

## Solution

New I1 plugin consuming `high` and `low` OHLCV inputs. Per `docs/ideas/2nd-derivative-indicator-research.md`:

**Formula:**
1. `midpoint = (high + low) / 2`
2. `ao = SMA(midpoint, 5) - SMA(midpoint, 34)` — Awesome Oscillator
3. `ac = ao - SMA(ao, 5)` — Acceleration/Deceleration

**State:** two rolling SMA buffers (5-bar and 34-bar of midpoint, 5-bar of AO)

**Outputs:** `ao`, `ac`, `ac_bullish` (ac > 0 and rising), `ac_bearish` (ac < 0 and falling)

Add to `TIER_I1` in `register_plugins.py`. Warmup: 34 + 5 = 39 bars minimum.
