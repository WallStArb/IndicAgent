---
created: 2026-02-27T00:00:00.000Z
title: Wire timeframe matrix to live per-TF signal data
area: ui
files:
  - dashboard/src/components/trading-dashboard.tsx
  - dashboard/src/hooks/use-market-stream.ts
---

## Problem

The TF matrix (row of 1m/5m/15m/1h dots per symbol card) is not wired to live signal direction data. Each dot should show signal direction for that timeframe (e.g. green for LONG, red for SHORT, grey for no signal).

## Solution

Wire `tfSignals` state (already populated from SSE `signal_data` events in `use-market-stream.ts`) to the TF matrix component. Each dot reads `tfSignals[symbol][tf].direction` and renders the appropriate colour.
