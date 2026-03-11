---
created: 2026-02-27T00:00:00.000Z
title: Dashboard final audit — all panels, all symbol profiles, all timeframes
area: ui
files:
  - dashboard/src/components/
---

## Problem

No systematic audit has been done across all 23 symbol profiles and all timeframe tabs. Individual panels have been verified for ES 1m but edge cases (agriculture symbols, FX, crypto, rates) may render differently or expose missing data states.

## Solution

Systematic check:
- All symbol groups (equity index, energy, metals, rates, FX, agriculture, crypto) — verify panels render correctly with live data
- All timeframes (1m/5m/15m/1h) — verify indicator, structure, SMC, and signal panels switch correctly
- All "no data" states — verify graceful empty states rather than errors/zeros when a tier hasn't produced output yet
- Fix any panel that shows zeros or undefined when the pipeline is live
