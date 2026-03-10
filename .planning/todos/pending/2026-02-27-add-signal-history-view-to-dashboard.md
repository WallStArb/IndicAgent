---
created: 2026-02-27T00:00:00.000Z
title: Add signal history view to dashboard
area: ui
files:
  - dashboard/src/components/
  - src/api/routes/signals.py
---

## Problem

There is no way to browse recent signal history on the dashboard. The `GET /api/signals/{symbol}` endpoint exists and supports pagination, but it's not surfaced in the UI.

## Solution

Add a signal history panel or drill-down view showing recent signals for the selected symbol: entry/stop/targets, RR ratio, outcome (if resolved), and timestamp. Connect to `GET /api/signals/{symbol}?limit=20`. Either a scrollable panel within the symbol card or a separate overlay/drawer.
