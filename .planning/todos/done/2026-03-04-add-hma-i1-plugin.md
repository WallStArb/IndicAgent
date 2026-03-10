---
created: 2026-03-04T00:00:00.000Z
title: Add Hull Moving Average (HMA) to I1 indicators
area: intelligence
files:
  - src/intelligence/indicators/ma_plugin.py
  - src/intelligence/register_plugins.py
  - tests/unit/intelligence/indicators/
---

## Problem

HMA is widely used and its 1st/2nd derivatives are cleaner signals than price-crosses-HMA. Not in the pipeline. Once HMA lands in I1, HMA acceleration follows the same pattern as `MomentumAcceleration` (trivial I2 plugin).

## Solution

Add HMA to `ma_plugin.py` or as a new `hma_plugin.py`. Per `docs/ideas/2nd-derivative-indicator-research.md`:

**Formula:**
1. `WMA1 = WMA(close, n/2)` — half-period weighted MA
2. `WMA2 = WMA(close, n)` — full-period weighted MA
3. `raw = 2 × WMA1 - WMA2`
4. `HMA = WMA(raw, sqrt(n))`

Standard period: n=20 → `hma_20`

**Outputs:** `hma_20`

Once implemented, I2 HMA acceleration becomes: `hma_slope = hma[t] - hma[t-1]`, `hma_accel = hma_slope[t] - hma_slope[t-1]`.
