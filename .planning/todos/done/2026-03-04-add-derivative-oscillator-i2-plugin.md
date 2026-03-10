---
created: 2026-03-04T00:00:00.000Z
title: Add Derivative Oscillator I2 plugin (Constance Brown)
area: intelligence
files:
  - src/intelligence/composites/
  - src/intelligence/register_plugins.py
  - tests/unit/intelligence/composites/
---

## Problem

The pipeline has `rsi_accel` (raw RSI first-diff) but no structured zero-line oscillator built from RSI's double-smooth. The Derivative Oscillator leads MACD by ~1-2 bars and is trader-readable with clear crossover events.

## Solution

New I2 plugin consuming `rsi_14` from I1. Implementation per `docs/ideas/2nd-derivative-indicator-research.md`:

**Formula:**
1. `DS1 = EMA(RSI, 5)` — first smooth
2. `DS2 = EMA(DS1, 3)` — second smooth
3. `Signal = SMA(DS2, 9)`
4. `deriv_osc = DS2 - Signal`

**State:** `_state` keys — `ema1`, `ema2`, signal buffer (9 bars of DS2), `prev_osc`

**Outputs:** `deriv_osc`, `deriv_osc_signal`, `deriv_osc_cross_bullish`, `deriv_osc_cross_bearish`

**Warmup:** Suppress for first 26 bars (RSI=14 + double-smooth=12).

Add to `TIER_I2` in `register_plugins.py`.
